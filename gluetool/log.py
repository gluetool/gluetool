"""
Logging support.

Sets up logging environment for use by ``gluetool`` and modules. Based
on standard library's :py:mod:`logging` module, augmented a bit to
support features loke colorized messages and stackable context information.

Example usage:

.. code-block:: python

   # initialize logger as soon as possible
   logger = Logging.create_logger()

   # now it's possible to use it for logging:
   logger.debug('foo!')

   # or connect it with current instance (if you're doing all this
   # inside some class' constructor):
   logger.connect(self)

   # now you can access logger's methods directly:
   self.debug('foo once again!')

   # find out what your logging should look like, e.g. by parsing command-line options
   ...

   # tell logger about the final setup
   logger = Logging.create_logger(output_file='/tmp/foo.log', level=...)

   # and, finally, create a root context logger - when we create another loggers during
   # the code flow, this context logger will be in the root of this tree of loggers.
   logger = ContextAdapter(logger)

   # don't forget to re-connect with the context logger if you connected your instance
   # with previous logger, to make sure helpers are set correctly
   logger.connect(self)
"""

import atexit
import contextlib
import hashlib
import json
import logging
import os
import sys
import time
import traceback

import jinja2

from .color import Colors


BLOB_HEADER = '---v---v---v---v---v---'
BLOB_FOOTER = '---^---^---^---^---^---'

# Default log level is logging.INFO or logging.DEBUG if GLUETOOL_DEBUG environment variable is set
DEFAULT_LOG_LEVEL = logging.DEBUG if os.getenv('GLUETOOL_DEBUG') else logging.INFO

# Add our custom "verbose" loglevel - it's even bellow DEBUG, and it *will* be lost unless
# gluetool's told to store it into a file. It's goal is to capture very verbose log records,
# e.g. raw output of commands or API responses.
logging.VERBOSE = 5
logging.addLevelName(logging.VERBOSE, 'VERBOSE')


# Methods we "patch" logging.Logger and logging.LoggerAdapter with
def verbose_logger(self, message, *args, **kwargs):
    if not self.isEnabledFor(logging.VERBOSE):
        return

    # When we are expected to emit record of VERBOSE level, make a DEBUG note
    # as well, to "link" debug and verbose outputs. With this, one might read
    # DEBUG log, and use this reference to find corresponding VERBOSE record.
    # Adding time.time() as a salt - tag is based on message hash, it may be
    # logged multiple times, leading to the same tag.
    tag = hashlib.md5('{}: {}'.format(time.time(), message)).hexdigest()

    # add verbose tag as a context, with very high priority
    if 'extra' not in kwargs:
        kwargs['extra'] = {}

    kwargs['extra']['ctx_verbose_tag'] = (1000, 'VERBOSE {}'.format(tag))

    # Verbose message should give some hint. It must contain the tag, but it could also start
    # with a hint!
    keep_len = 12

    if len(message) <= keep_len:
        hint = message

    else:
        new_line_index = message.find('\n')

        if new_line_index == -1:
            hint = '{}...'.format(message[0:keep_len])

        elif new_line_index == keep_len:
            hint = message

        elif new_line_index < keep_len:
            hint = message[0:new_line_index]

        else:
            hint = '{}...'.format(message[0:keep_len])

    verbose_message = '{} (See "verbose" log for the actual message)'.format(hint)

    # pylint: disable-msg=protected-access
    self._log(logging.DEBUG, verbose_message, args, **kwargs)
    self._log(logging.VERBOSE, message, args, **kwargs)


def verbose_adapter(self, message, *args, **kwargs):
    message, kwargs = self.process(message, kwargs)
    self.logger.verbose(message, *args, **kwargs)


def warn_sentry(self, message, *args, **kwargs):
    """
    Beside calling the original the ``warning`` method (stored as ``self.orig_warning``),
    this one also submits warning to the Sentry server when asked to do so by a keyword
    argument ``sentry`` set to ``True``.
    """

    if 'sentry' in kwargs:
        report_to_sentry = kwargs['sentry'] and getattr(self, 'sentry_submit_warning', None) is not None
        del kwargs['sentry']

    else:
        report_to_sentry = False

    self.orig_warning(message, *args, **kwargs)

    if report_to_sentry:
        self.sentry_submit_warning(message, logger=self, **kwargs)


logging.Logger.orig_warning = logging.Logger.warning
logging.Logger.warning = warn_sentry
logging.Logger.warn = warn_sentry

logging.LoggerAdapter.orig_warning = logging.LoggerAdapter.warning
logging.LoggerAdapter.warning = warn_sentry
logging.LoggerAdapter.warn = warn_sentry

logging.Logger.verbose = verbose_logger
logging.LoggerAdapter.verbose = verbose_adapter


_TRACEBACK_TEMPLATE = """
{%- set label = '{}:'.format(label) %}
---v---v---v---v---v--- {{ label | center(10) }} ---v---v---v---v---v---

At {{ stack[-1][0] }}:{{ stack[-1][1] }}, in {{ stack[-1][2] }}:

{{ exception.__class__.__module__ }}.{{ exception.__class__.__name__ }}: {{ exception.message }}

{% for filepath, lineno, fn, text, frame in stack %}
  File "{{ filepath }}", line {{ lineno }}, in {{ fn }}
    {{ text | default('') }}

    Local variables:{% for name in frame.f_locals.iterkeys() | sort %}
        {{ name }} = {{ frame.f_locals[name] }}
    {%- endfor %}
{% endfor %}
---^---^---^---^---^---^----------^---^---^---^---^---^---
"""


class BlobLogger(object):
    """
    Context manager to help with "real time" logging - some code may produce output continuously,
    e.g. when running a command and streaming its output to our stdout, and yet we still want to
    wrap it with boundaries and add a header.

    This code:

    .. code-block:: python

       with BlobLogger('ls of root', outro='end of ls'):
           subprocess.call(['ls', '/'])

    will lead to the output similar to this:


    .. code-block:: bash

       [20:30:50] [+] ---v---v---v---v---v--- ls of root
       bin  boot  data  dev ...
       [20:30:50] [+] ---^---^---^---^---^--- end of ls

    .. note::

       When you already hold the data you wish to log, please use :py:func:`gluetool.log.log_blob`
       or :py:func:`gluetool.log.log_dict`. The example above could be rewritten using ``log_blob``
       by using :py:meth:`subprocess.check_output` and passing its return value to ``log_blob``.
       ``BlobLogger`` is designed to wrap output whose creation caller don't want to (or cannot)
       control.

    :param str intro: Label to show what is the meaning of the logged data.
    :param str outro: Label to show by the final boundary to mark the end of logging.
    :param callable on_finally: When set, it will be called in ``__exit__`` method. User of
        this context manager might need to flush used streams or close resources even in case
        the exception was raised while inside the context manager. ``on_finally`` is called
        with all arguments the ``__exit__`` was called, and its return value is returned by
        ``__exit__`` itself, therefore it can examine possible exceptions, and override them.
    :param callable writer: A function which is used to actually log the text. Usually a one of some logger methods.
    """

    # pylint: disable=too-few-public-methods

    def __init__(self, intro, outro=None, on_finally=None, writer=None):
        self.writer = Logging.get_logger().info if writer is None else writer

        self.intro = intro
        self.outro = outro
        self.on_finally = on_finally

    def __enter__(self):
        self.writer('{} {}'.format(BLOB_HEADER, self.intro))

    def __exit__(self, *args, **kwargs):
        self.writer('{} {}'.format(BLOB_FOOTER, self.outro or ''))

        if self.on_finally:
            return self.on_finally(*args, **kwargs)


class StreamToLogger(object):
    """
    Fake ``file``-like stream object that redirects writes to a given logging method.
    """

    # pylint: disable=too-few-public-methods

    def __init__(self, log_fn):
        self.log_fn = log_fn

        self.linebuf = []

    def write(self, buf):
        for c in buf:
            if ord(c) == ord('\n'):
                self.log_fn(''.join(self.linebuf))
                self.linebuf = []
                continue

            if ord(c) == ord('\r'):
                continue

            self.linebuf.append(c)


@contextlib.contextmanager
def print_wrapper(log_fn=None, label='print wrapper'):
    """
    While active, replaces :py:data:`sys.stdout` and :py:data:`sys.stderr` streams with
    fake ``file``-like streams which send all outgoing data to a given logging method.

    :param call log_fn: A callback that is called for every line, produced by ``print``.
        If not set, a ``info`` method of ``gluetool`` main logger is used.
    :param str label: short description, presented in the intro and outro headers, wrapping
        captured output.
    """

    log_fn = log_fn or Logging.get_logger().info

    fake_stream = StreamToLogger(log_fn)

    log_fn('{} {} enabled'.format(BLOB_HEADER, label))

    stdout, stderr, sys.stdout, sys.stderr = sys.stdout, sys.stderr, fake_stream, fake_stream

    try:
        yield

    finally:
        sys.stdout, sys.stderr = stdout, stderr

        log_fn('{} {} disabled'.format(BLOB_FOOTER, label))


def format_blob(blob):
    """
    Format a blob of text for printing. Wraps the text with boundaries to mark its borders.
    """

    return '{}\n{}\n{}'.format(BLOB_HEADER, blob, BLOB_FOOTER)


def format_dict(dictionary):
    """
    Format a Python data structure for printing. Uses :py:func:`json.dumps` formatting
    capabilities to present readable representation of a given structure.
    """

    # Use custom "default" handler, to at least encode obj's repr() output when
    # json encoder does not know how to encode such class
    def default(obj):
        return repr(obj)

    return json.dumps(dictionary, sort_keys=True, indent=4, separators=(',', ': '), default=default)


def format_xml(element):
    """
    Format an XML element, e.g. Beaker job description, for printing.

    :param element: XML element to format.
    """

    return element.prettify(encoding='utf-8')


def log_dict(writer, intro, data):
    """
    Log structured data, e.g. JSON responses or a Python ``list``.

    .. note::

       For logging unstructured "blobs" of text, use :py:func:`gluetool.log.log_blob`. It does not
       attempt to format the output, and wraps it by header and footer to mark its boundaries.

    .. note::

       Using :py:func:`gluetool.log.format_dict` directly might be shorter, depending on your your code.
       For example, this code:

       .. code-block:: python

          self.debug('Some data:\\n{}'.format(format_dict(data)))

       is equivalent to:

       .. code-block:: python

          log_dict(self.debug, 'Some data', data)

       If you need more formatting, or you wish to fit more information into a single message, using
       logger methods with ``format_dict`` is a way to go, while for logging a single structure ``log_dict``
       is more suitable.

    :param callable writer: A function which is used to actually log the text. Usually a one of some logger methods.
    :param str intro: Label to show what is the meaning of the logged structure.
    :param str blob: The actual data to log.
    """

    writer('{}:\n{}'.format(intro, format_dict(data)), extra={
        'raw-struct': data
    })


def log_blob(writer, intro, blob):
    """
    Log "blob" of characters of unknown structure, e.g. output of a command or response
    of a HTTP request. The blob is preceded by a header and followed by a footer to mark
    exactly the blob boundaries.

    .. note::

       For logging structured data, e.g. JSON or Python structures, use :py:func:`gluetool.log.log_dict`. It will
       make structure of the data more visible, resulting in better readability of the log.

    :param callable writer: A function which is used to actually log the text. Usually a one of some logger methods.
    :param str intro: Label to show what is the meaning of the logged blob.
    :param str blob: The actual blob of text.
    """

    writer("{}:\n{}".format(intro, format_blob(blob)), extra={
        'raw-blob': blob
    })


def log_xml(writer, intro, element):
    """
    Log an XML element, e.g. Beaker job description.

    :param callable writer: A function which is used to actually log the text. Usually a one of some logger methods.
    :param str intro: Label to show what is the meaning of the logged blob.
    :param element: XML element to log.
    """

    writer("{}:\n{}".format(intro, format_xml(element)), extra={
        'raw-xml': element
    })


# pylint: disable=invalid-name
def _extract_stack(tb):
    """
    Construct a "stack" by merging two sources of data:

    1. what's provided by ``traceback.extract_tb()``, i.e. ``(filename, lineno, fnname, text)`` tuple for each frame;
    2. stack frame objects, hidden inside traceback object and available via following links from one frame to another.

    :rtype: list(list(str, int, str, str, frame))
    """

    stack = []

    extracted_tb = traceback.extract_tb(tb)

    trace_iter = tb
    while trace_iter:
        stack.append(list(extracted_tb.pop(0)) + [trace_iter.tb_frame])
        trace_iter = trace_iter.tb_next

    return stack


class SingleLogLevelFileHandler(logging.FileHandler):
    def __init__(self, level, *args, **kwargs):
        super(SingleLogLevelFileHandler, self).__init__(*args, **kwargs)

        self.level = level

    def emit(self, record):
        if not record.levelno == self.level:
            return

        super(SingleLogLevelFileHandler, self).emit(record)


class ContextAdapter(logging.LoggerAdapter):
    """
    Generic logger adapter that collects "contexts", and prepends them
    to the message.

    "context" is any key in ``extra`` dictionary starting with ``ctx_``,
    whose value is expected to be tuple of ``(priority, value)``. Contexts
    are then sorted by their priorities before inserting them into the message
    (lower priority means context will be placed closer to the beggining of
    the line - highest priority comes last.

    :param logging.Logger logger: parent logger this adapter modifies.
    :param dict extras: additional extra keys passed to the parent class.
        The dictionary is then used to update messages' ``extra`` key with
        the information about context.
    """

    def __init__(self, logger, extra=None):
        super(ContextAdapter, self).__init__(logger, extra or {})

        self.warn = self.warning
        self.sentry_submit_warning = getattr(logger, 'sentry_submit_warning', None)

    def process(self, msg, kwargs):
        """
        Original ``process`` overwrites ``kwargs['extra']`` which doesn't work
        for us - we want to chain adapters, getting more and more contexts
        on the way. Therefore ``update`` instead of assignment.
        """

        if 'extra' not in kwargs:
            kwargs['extra'] = {}

        kwargs['extra'].update(self.extra)
        return msg, kwargs

    def connect(self, parent):
        """
        Create helper methods in ``parent``, by assigning adapter's methods to its
        attributes. One can then call ``parent.debug`` and so on, instead of less
        readable ``parent.logger.debug``.

        Simply instantiate adapter and call its ``connect`` with an object as
        a ``parent`` argument, and the object will be enhanced with all these
        logging helpers.

        :param parent: object to enhance with logging helpers.
        """

        parent.debug = self.debug
        parent.verbose = self.verbose
        parent.info = self.info
        parent.warn = self.warning
        parent.error = self.error
        parent.exception = self.exception


class ModuleAdapter(ContextAdapter):
    """
    Custom logger adapter, adding module name as a context.

    :param logging.Logger logger: parent logger this adapter modifies.
    :param gluetool.glue.Module module: module whose name is added as a context.
    """

    def __init__(self, logger, module):
        super(ModuleAdapter, self).__init__(logger, {'ctx_module_name': (10, module.unique_name)})


class PackageAdapter(ContextAdapter):
    """
    Custom logger dapter, adding a package name as a context. Intended to taint log
    records produced by a 3rd party packages.

    :logging.Logger logger: parent logger this adapter modifies.
    :param str name: name of the library.
    """

    def __init__(self, logger, name):
        super(PackageAdapter, self).__init__(logger, {'ctx_package_name': (50, name)})


class LoggingFormatter(logging.Formatter):
    """
    Custom log record formatter. Produces output in form of:

    ``[stamp] [level] [ctx1] [ctx2] ... message``

    :param bool colors: if set, colorize output. Enabled by default but when used with
        file-backed destinations, colors are disabled by logging subsystem.
    :param bool log_tracebacks: if set, add tracebacks to the message. By default,
        we don't need tracebacks on the terminal, unless its loglevel is verbose enough,
        but we want them in the debugging file.
    """

    #: Tags used to express loglevel.
    _level_tags = {
        logging.VERBOSE: 'V',
        logging.DEBUG: 'D',
        logging.INFO: '+',
        logging.WARNING: 'W',
        logging.ERROR: 'E',
        logging.CRITICAL: 'C'
    }

    #: Colorizers assigned to loglevels
    _level_color = {
        logging.INFO: lambda text: Colors.style(text, fg='green'),
        logging.WARNING: lambda text: Colors.style(text, fg='yellow'),
        logging.ERROR: lambda text: Colors.style(text, fg='red'),
        logging.CRITICAL: lambda text: Colors.style(text, fg='red')
    }

    def __init__(self, colors=True, log_tracebacks=False):
        super(LoggingFormatter, self).__init__()

        self.colors = colors
        self.log_tracebacks = log_tracebacks

    @staticmethod
    def _format_exception_chain(exc_info):
        """
        Format exception chain. Start with the one we're given, and follow its `caused_by` property
        until we ran out of exceptions to format.
        """

        tmpl = jinja2.Template(_TRACEBACK_TEMPLATE)

        output = ['']

        # Don't unpack exception info to local variables - by assigning exc_info[2] (traceback) to a local
        # variable, we might introduce a circular reference between our stack and traceback, making it hard
        # for GC to collect this stack frame.

        # Format one exception and its traceback
        def _add_block(label, exc, trace):
            stack = _extract_stack(trace)

            output.append(tmpl.render(label=label, exception=exc, stack=stack))

        # This is the most recent exception, we start with this one - it's often the one most visible,
        # exceptions that caused it are usualy hidden from user's sight.
        _add_block('Exception', exc_info[1], exc_info[2])

        # Iterate over any previous exceptions and format them as well.
        while getattr(exc_info[1], 'caused_by', None) is not None:
            exc_info = exc_info[1].caused_by

            _add_block('Caused by', exc_info[1], exc_info[2])

        return '\n'.join(output).strip()

    def format(self, record):
        """
        Format a logging record. It puts together pieces like time stamp,
        log level, possibly also different contexts if there are any stored
        in the record, and finally applies colors if asked to do so.

        :param logging.LogRecord record: record describing the event.
        :rtype: str
        :returns: string representation of the event record.
        """

        fmt = ['[{stamp}]', '[{level}]', '{msg}']
        values = {
            'stamp': self.formatTime(record, datefmt='%H:%M:%S'),
            'level': LoggingFormatter._level_tags[record.levelno],
            'msg': record.getMessage()
        }

        if record.exc_info \
                and (self.log_tracebacks is True or Logging.stderr_handler.level in (logging.DEBUG, logging.VERBOSE)):
            fmt.append('{exc_text}')

            # \n helps formatting - logging would add formatted chain right after the leading message
            # without starting new line. We must do it, to make report more readable.
            values['exc_text'] = '\n\n' + LoggingFormatter._format_exception_chain(record.exc_info)

        # Handle context properties of the record
        def _add_context(context_name, context_value):
            fmt.insert(2, '[{%s}]' % context_name)
            values[context_name] = context_value

        # find all context properties attached to the record
        ctx_properties = [prop for prop in dir(record) if prop.startswith('ctx_')]

        if ctx_properties:
            # Sorting them in reverse order of priorities - we're goign to insert
            # their values into `fmt`, so the highest priority context must be
            # inserted as the last one.
            sorted_ctxs = sorted(ctx_properties, key=lambda x: getattr(record, x)[0], reverse=True)

            for name in sorted_ctxs:
                _, value = getattr(record, name)

                _add_context(name, value)

        # add thread name context if we're not in the main thread
        thread_name = getattr(record, 'threadName', None)

        if thread_name is not None and thread_name != 'MainThread':
            _add_context('thread_name', thread_name)

        # format message
        msg = ' '.join(fmt).format(**values)

        if self.colors and record.levelno in self._level_color:
            msg = self._level_color[record.levelno](msg)

        return msg


class JSONLoggingFormatter(logging.Formatter):
    """
    Custom logging formatter producing a JSON dictionary describing the log record.
    """

    def __init__(self, **kwargs):
        # pylint: disable=unused-argument

        super(JSONLoggingFormatter, self).__init__()

    @staticmethod
    def _format_exception_chain(serialized, exc_info):
        """
        "Format" exception chain - transform it into a bunch of JSON structures describing exceptions, stack frames,
        local variables and so on.

        Serves the same purpose as ``LoggingFormatter._format_exception_chain`` but that one produces a string,
        textual representation suitable for printing. This method produces JSON structures, suitable for, hm,
        JSON log.
        """

        serialized['caused_by'] = []

        # pylint: disable=invalid-name
        def _add_cause(exc, tb):
            exc_class = exc.__class__

            stack = _extract_stack(tb)

            serialized['caused_by'].append({
                'exception': {
                    'class': '{}.{}'.format(exc_class.__module__, exc_class.__name__),
                    'message': exc.message
                },
                'traceback': [
                    {
                        'filename': filename,
                        'lineno': lineno,
                        'fnname': fnname,
                        'text': text,
                        'locals': frame.f_locals
                    }
                    for filename, lineno, fnname, text, frame in stack
                ]
            })

        _add_cause(exc_info[1], exc_info[2])

        while getattr(exc_info[1], 'caused_by', None) is not None:
            exc_info = exc_info[1].caused_by

            _add_cause(exc_info[1], exc_info[2])

    def format(self, record):
        # Construct a huuuuge dictionary describing the event
        serialized = {
            field: getattr(record, field, None)
            for field in (
                # LogRecord properties
                'args', 'created', 'exc_info', 'exc_text', 'filename', 'funcName', 'levelname', 'levelno',
                'lineno', 'module', 'msecs', 'msg', 'name', 'pathname', 'process', 'processName',
                'relativeCreated', 'thread', 'threadName',
                # our custom fields
                'raw-blob', 'raw-struct', 'raw-xml'
            )
        }

        serialized['message'] = record.getMessage()

        if record.exc_info:
            JSONLoggingFormatter._format_exception_chain(serialized, record.exc_info)

        return format_dict(serialized)


class Logging(object):
    """
    Container wrapping configuration and access to :py:mod:`logging` infrastructure ``gluetool``
    uses for logging.
    """

    #: Logger singleton - if anyone asks for a logger, they will get this one. Needs
    #: to be properly initialized by calling :py:meth:`create_logger`.
    logger = None

    #: Stream handler printing out to stderr.
    stderr_handler = None

    debug_file_handler = None
    verbose_file_handler = None
    json_file_handler = None

    @staticmethod
    def get_logger():
        """
        Returns a logger instance.

        Expects there was a call to :py:meth:`create_logger` method before calling this method
        that would actually create and set up the logger.

        :rtype: logging.Logger
        :returns: a :py:class:`logging.Logger` instance, set up for logging, or ``None`` when there's
            no logger yet.
        """

        return Logging.logger

    # Following methods are intended for 3rd party loggers one might want to connect to our
    # logging configuration. Gluetool will configure properly its own logger and few others
    # it knows about (e.g. "requests" has one interesting), but it has no idea what other
    # loggers might be interesting for module developer. Therefore, these methods are used
    # to A) setup loggers gluetool knows about, and B) public to allow module developer
    # attach arbitrary loggers.

    @staticmethod
    def configure_logger(logger):
        """
        Configure given logger to conform with Gluetool's idea of logging. The logger is set to
        ``VERBOSE`` level, shared stderr handler is added, and Sentry integration status is
        propagated as well.

        After this method, the logger will behave like Gluetool's main logger.
        """

        logger.propagate = False
        logger.sentry_submit_warning = Logging.sentry_submit_warning

        # logger actually emits everything, handlers do filtering
        logger.setLevel(logging.VERBOSE)

        # add stderr handler
        logger.addHandler(Logging.stderr_handler)

    @staticmethod
    def enable_logger_sentry(logger):
        if not Logging.sentry:
            return

        Logging.sentry.enable_logging_breadcrumbs(logger)

    @staticmethod
    def enable_debug_file(logger):
        if not Logging.debug_file_handler:
            return

        logger.addHandler(Logging.debug_file_handler)

    @staticmethod
    def enable_verbose_file(logger):
        if not Logging.verbose_file_handler:
            return

        logger.addHandler(Logging.verbose_file_handler)

    @staticmethod
    def enable_json_file(logger):
        if not Logging.json_file_handler:
            return

        logger.addHandler(Logging.json_file_handler)

    OUR_LOGGERS = (
        logging.getLogger('gluetool'),
        logging.getLogger('urllib3')
    )

    @staticmethod
    def _setup_log_file(filepath, level, limit_level=False, formatter=LoggingFormatter):
        if filepath is None:
            return None

        if limit_level:
            handler = SingleLogLevelFileHandler(level, filepath, 'w')

        else:
            handler = logging.FileHandler(filepath, 'w')

        handler.setLevel(level)

        formatter = formatter(colors=False, log_tracebacks=True)
        handler.setFormatter(formatter)

        def _close_log_file():
            logger = Logging.get_logger()

            logger.debug("closing output file '{}'".format(filepath))

            handler.flush()
            handler.close()

            logger.removeHandler(handler)

        atexit.register(_close_log_file)

        Logging.get_logger().debug("created output file '{}'".format(filepath))

        return handler

    # pylint: disable=too-many-arguments
    @staticmethod
    def create_logger(level=DEFAULT_LOG_LEVEL,
                      debug_file=None, verbose_file=None, json_file=None,
                      sentry=None, sentry_submit_warning=None,
                      show_traceback=False):
        """
        Create and setup logger.

        This method is called at least twice:

          - when :py:class:`gluetool.glue.Glue` is instantiated: only a ``stderr`` handler is set up,
            with loglevel being ``INFO``;
          - when all arguments and options are processed, and Glue instance can determine desired
            log level, whether it's expected to stream debugging messages into a file, etc. This
            time, method only modifies propagates necessary updates to already existing logger.

        :param str debug_file: if set, new handler will be attached to the logger, streaming
            messages of at least ``DEBUG`` level into this this file.
        :param str verbose_file: if set, new handler will be attached to the logger, streaming
            messages of ``VERBOSE`` log levels into this this file.
        :param str json_file: if set, all logging messages are sent to this file in a form
            of JSON structures.
        :param int level: desired log level. One of constants defined in :py:mod:`logging` module,
            e.g. :py:data:`logging.DEBUG` or :py:data:`logging.ERROR`.
        :param bool sentry: if set, logger will be augmented to send every log message to the Sentry
            server.
        :param callable sentry_submit_warning: if set, it is used by ``warning`` methods of derived
            loggers to submit warning to the Sentry server, if asked by a caller to do so.
        :param bool show_traceback: if set, exception tracebacks would be sent to ``stderr`` handler
            as well as to the debug file.
        :rtype: logging.Logger
        :returns: a :py:class:`logging.Logger` instance, set up for logging.
        """

        level = level or logging.INFO

        # store for later use by configure_logger & co.
        Logging.sentry = sentry
        Logging.sentry_submit_warning = sentry_submit_warning

        if Logging.logger is None:
            # we're doing the very first setup of logging handlers, therefore create new stderr handler,
            # configure it and attach it to correct places
            Logging.stderr_handler = logging.StreamHandler()
            Logging.stderr_handler.setLevel(level)

            # create our main logger
            Logging.logger = logging.getLogger('gluetool')

            # setup all loggers we're interested in
            map(Logging.configure_logger, Logging.OUR_LOGGERS)

        # set formatter
        Logging.stderr_handler.setFormatter(LoggingFormatter())

        # set log level to new value
        Logging.stderr_handler.setLevel(level)

        # honor traceback display setup
        Logging.stderr_handler.formatter.log_tracebacks = show_traceback

        # create debug and verbose files
        Logging.debug_file_handler = Logging._setup_log_file(debug_file, logging.DEBUG)
        Logging.verbose_file_handler = Logging._setup_log_file(verbose_file, logging.VERBOSE, limit_level=True)
        Logging.json_file_handler = Logging._setup_log_file(json_file, logging.VERBOSE, formatter=JSONLoggingFormatter)

        # now our main logger should definitely exist and it should be usable
        logger = Logging.get_logger()

        # Enable Sentry
        Logging.enable_logger_sentry(logger)

        map(Logging.enable_logger_sentry, Logging.OUR_LOGGERS)

        # Enable debug and verbose files
        Logging.enable_debug_file(logger)
        Logging.enable_verbose_file(logger)
        Logging.enable_json_file(logger)

        map(Logging.enable_debug_file, Logging.OUR_LOGGERS)
        map(Logging.enable_verbose_file, Logging.OUR_LOGGERS)
        map(Logging.enable_json_file, Logging.OUR_LOGGERS)

        logger.debug("logger set up: level={}, debug file={}, verbose file={}, json file={}".format(level,
                                                                                                    debug_file,
                                                                                                    verbose_file,
                                                                                                    json_file))

        return logger
