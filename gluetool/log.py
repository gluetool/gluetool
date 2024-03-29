# pylint: disable=too-many-lines

"""
Logging support.

Sets up logging environment for use by ``gluetool`` and modules. Based
on standard library's :py:mod:`logging` module, augmented a bit to
support features loke colorized messages and stackable context information.

Example usage:

.. code-block:: python

   # initialize logger as soon as possible
   Logging.setup_logger()
   logger = Logging.get_logger()

   # now it's possible to use it for logging:
   logger.debug('foo!')

   # find out what your logging should look like, e.g. by parsing command-line options
   ...

   # tell logger about the final setup
   logger = Logging.setup_logger(output_file='/tmp/foo.log', level=...)

   # when you want to make logging methods easily accessible in your class, throw in
   # LoggerMixin:
   class Foo(LoggerMixin, ...):
     def __init__(self, some_logger):
         super(Foo, self).__init__(logger)

         self.debug('foo!')
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
import tabulate
from six import PY2, ensure_str, ensure_binary, iteritems, iterkeys

from .color import Colors

# Type annotations
# pylint: disable=unused-import,wrong-import-order,line-too-long
from typing import TYPE_CHECKING, Any, AnyStr, Callable, Dict, Iterable, List, MutableMapping, Optional, Tuple, Type, Union  # noqa
from typing_extensions import Protocol  # noqa
from types import TracebackType  # noqa
from mypy_extensions import Arg, DefaultArg, NamedArg, DefaultNamedArg, VarArg, KwArg  # noqa

if TYPE_CHECKING:
    # pylint: disable=cyclic-import
    import bs4  # noqa
    import gluetool  # noqa
    import gluetool.sentry  # noqa

# Type definitions
# pylint: disable=invalid-name
ExceptionInfoType = Union[
    Tuple[Optional[type], Optional[BaseException], Optional[TracebackType]],  # returned by sys.exc_info()
    Tuple[None, None, None]
]

LoggingFunctionType = Callable[
    [
        Arg(str),
        DefaultNamedArg(ExceptionInfoType, 'exc_info'),  # noqa: F821
        DefaultNamedArg(Dict[str, Any], 'extra'),  # noqa: F821
        DefaultNamedArg(bool, 'sentry')  # noqa: F821
    ],
    None
]

ContextInfoType = Tuple[int, Any]


BLOB_HEADER = '---v---v---v---v---v---'
BLOB_FOOTER = '---^---^---^---^---^---'

# Default log level is logging.INFO or logging.DEBUG if GLUETOOL_DEBUG environment variable is set
DEFAULT_LOG_LEVEL = logging.DEBUG if os.getenv('GLUETOOL_DEBUG') else logging.INFO

# Our custom "verbose" loglevel - it's even bellow DEBUG, and it *will* be lost unless
# gluetool's told to store it into a file. It's goal is to capture very verbose log records,
# e.g. raw output of commands or API responses.
VERBOSE = 5


_TRACEBACK_TEMPLATE = """
{%- set label = '{}:'.format(label) %}
---v---v---v---v---v--- {{ label | center(10) }} ---v---v---v---v---v---

At {{ stack[-1][0] }}:{{ stack[-1][1] }}, in {{ stack[-1][2] }}:

{{ exception.__class__.__module__ }}.{{ exception.__class__.__name__ }}: {{ exception }}

{% for filepath, lineno, fn, text, frame in stack %}
  File "{{ filepath }}", line {{ lineno }}, in {{ fn }}
    {{ text | default('') }}

    Local variables:{% for name in iterkeys(frame.f_locals) | sort %}
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
        # type: (str, Optional[str], Optional[Callable[..., Any]], Optional[Callable[[str], None]]) -> None

        self.writer = writer or Logging.get_logger().info

        self.intro = intro
        self.outro = outro
        self.on_finally = on_finally

    def __enter__(self):
        # type: () -> None

        self.writer('{} {}'.format(BLOB_HEADER, self.intro))

    def __exit__(self, *args, **kwargs):
        # type: (*Any, **Any) -> Optional[Any]

        self.writer('{} {}'.format(BLOB_FOOTER, self.outro or ''))

        if self.on_finally:
            return self.on_finally(*args, **kwargs)

        return None  # makes mypy happy


class StreamToLogger(object):
    """
    Fake ``file``-like stream object that redirects writes to a given logging method.
    """

    # pylint: disable=too-few-public-methods

    def __init__(self, log_fn):
        # type: (LoggingFunctionType) -> None

        self.log_fn = log_fn

        self.linebuf = []  # type: List[str]

    def write(self, buf):
        # type: (str) -> None

        for c in buf:
            if ord(c) == ord('\n'):
                self.log_fn(ensure_str(''.join(self.linebuf)))
                self.linebuf = []
                continue

            if ord(c) == ord('\r'):
                continue

            self.linebuf.append(c)


@contextlib.contextmanager  # type: ignore  # complains about incompatible type but I see no issue :/
def print_wrapper(log_fn=None, label='print wrapper'):
    # type: (Optional[LoggingFunctionType], Optional[str]) -> Iterable[None]

    """
    While active, replaces :py:data:`sys.stdout` and :py:data:`sys.stderr` streams with
    fake ``file``-like streams which send all outgoing data to a given logging method.

    :param call log_fn: A callback that is called for every line, produced by ``print``.
        If not set, a ``info`` method of ``gluetool`` main logger is used.
    :param text label: short description, presented in the intro and outro headers, wrapping
        captured output.
    """

    log_fn = log_fn or Logging.get_logger().info
    assert log_fn is not None

    fake_stream = StreamToLogger(log_fn)

    log_fn('{} {} enabled'.format(BLOB_HEADER, label))

    stdout, stderr, sys.stdout, sys.stderr = sys.stdout, sys.stderr, fake_stream, fake_stream  # type: ignore

    try:
        yield

    finally:
        sys.stdout, sys.stderr = stdout, stderr

        log_fn('{} {} disabled'.format(BLOB_FOOTER, label))


def _json_dump(struct, **kwargs):
    # type: (Any, **Any) -> str
    """
    Dump given data structure as a JSON string. Additional arguments are passed to ``json.dumps``.
    """

    # Use custom "default" handler, to at least encode obj's repr() output when
    # json encoder does not know how to encode such class
    def default(obj):
        # type: (Any) -> str

        return repr(obj)

    return json.dumps(struct, default=default, **kwargs)


def format_blob(blob):
    # type: (AnyStr) -> str

    """
    Format a blob of text for printing. Wraps the text with boundaries to mark its borders.
    """

    text_blob = ensure_str(blob)

    return '{}\n{}\n{}'.format(BLOB_HEADER, text_blob, BLOB_FOOTER)


def format_dict(dictionary):
    # type: (Any) -> str

    """
    Format a Python data structure for printing. Uses :py:func:`json.dumps` formatting
    capabilities to present readable representation of a given structure.
    """

    return _json_dump(dictionary, sort_keys=True, indent=4, separators=(',', ': '))


def format_table(table, **kwargs):
    # type: (Iterable[Iterable[str]], **Any) -> str

    """
    Format a table, represented by an iterable of rows, represented by iterables.

    Internally, ``tabulate`` is used to do the formatting. All keyword arguments are passed
    to ``tabulate`` call.

    :param list(list()) table: table to format.
    :returns: formatted table.
    """

    return tabulate.tabulate(table, **kwargs)


def format_xml(element):
    # type: (bs4.BeautifulSoup) -> str

    """
    Format an XML element, e.g. Beaker job description, for printing.

    :param element: XML element to format.
    """

    prettyfied = element.prettify()  # type: str

    return prettyfied


def log_dict(writer, intro, data):
    # type: (LoggingFunctionType, str, Any) -> None

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
        'raw_intro': intro,
        'raw_struct': data
    })


def log_blob(writer, intro, blob):
    # type: (LoggingFunctionType, str, AnyStr) -> None

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
        'raw_intro': intro,
        'raw_blob': blob
    })


def log_table(writer, intro, table, **kwargs):
    # type: (LoggingFunctionType, str, Iterable[Iterable[str]], **Any) -> None

    """
    Log a formatted table.

    All keyword arguments are passed to :py:meth:`format_table` call which does the actual formatting.

    :param callable writer: A function which is used to actually log the text. Usually a one of some logger methods.
    :param str intro: Label to show what is the meaning of the logged table.
    :param list(list()) table: table to format.
    """

    writer('{}:\n{}'.format(intro, format_table(table, **kwargs)), extra={
        'raw_intro': intro,
        'raw_table': table
    })


def log_xml(writer, intro, element):
    # type: (LoggingFunctionType, str, bs4.BeautifulSoup) -> None

    """
    Log an XML element, e.g. Beaker job description.

    :param callable writer: A function which is used to actually log the text. Usually a one of some logger methods.
    :param str intro: Label to show what is the meaning of the logged blob.
    :param element: XML element to log.
    """

    writer("{}:\n{}".format(intro, format_xml(element)), extra={
        'raw_intro': intro,
        'raw_xml': element
    })


# pylint: disable=invalid-name
def _extract_stack(tb):
    # type: (Any) -> List[Any]
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
        # type: (int, *Any, **Any) -> None

        super(SingleLogLevelFileHandler, self).__init__(*args, **kwargs)

        self.level = level

    def emit(self, record):
        # type: (logging.LogRecord) -> None

        if not record.levelno == self.level:
            return

        super(SingleLogLevelFileHandler, self).emit(record)


def _move_contexts(src, dst):
    # type: (Dict[str, ContextInfoType], Dict[str, ContextInfoType]) -> None

    for name in list(iterkeys(src)):
        if not name.startswith('ctx_'):
            continue

        # Drop leading "ctx_" during the move.
        dst[name[4:]] = src[name]
        del src[name]


def _add_thread_context(contexts, record):
    # type: (Dict[str, ContextInfoType], logging.LogRecord) -> None

    assert contexts is not None

    thread_name = getattr(record, 'threadName', None)

    if thread_name is None or thread_name == 'MainThread':
        return

    contexts['thread_name'] = (0, thread_name)


class ContextAdapter(logging.LoggerAdapter):
    """
    Generic logger adapter that collects "contexts", and prepends them
    to the message.

    A "context" is a descriptive string, with a priority. Contexts are then sorted
    by their priorities before inserting them into the message (lower priority means
    context will be placed closer to the beggining of the line - highest priority
    comes last.

    ``ContextAdapter`` is a corner stone of our logging infrastructure, **everything** is
    supposed to, one way or another, use this class (or one of its children) for logging.
    We should avoid using bare ``Logger`` instances because they lack context propagation,
    message routing to debug and verbose files, ``verbose`` method & ``sentry`` parameter.

    Parent class, :py:class:`logging.LoggerAdapter`, provides all common logging methods.
    We overload them with our own implementations because we want to 1) handle type annotations
    on our side, 2) let users submit messages to Sentry.

    :param logger: parent logger this adapter modifies.
    :param dict extras: additional extra keys passed to the parent class.
        The dictionary is then used to update messages' ``extra`` key with
        the information about context.
        Keys starting with `ctx_` are removed from this dictionary, and become contexts.
    :param dict(str, tuple(int obj)) contexts: mapping of context names and tuples of their priority and value.
    """

    def __init__(self,
                 logger,  # type: Union[logging.Logger, ContextAdapter]
                 extra=None,  # type: Optional[Dict[str, Any]]
                 contexts=None  # type: Optional[Dict[str, ContextInfoType]]
                ):  # noqa
        # type: (...) -> None

        extra = extra or {}
        contexts = contexts or {}

        # Adapters are chained, there is no inheritance! We cannot create any `self._contexts` and gather all contexts
        # there, because each adapter is isolated from the rest of the chain. The only things they pass between them
        # is the message and message's `extra` mapping.
        #
        # So, we use `self._contexts` to gather contexts of *this* adapter only. Contexts may be specified as entries
        # in `extra` mapping given to us, or via more explicit `contexts` parameter. When a logging method gets called,
        # it would call its instance's `log()` and `process()` methods which would update `extra` parameter, given to
        # the logging method, with our `self_contexts`. `log()` would then called underlying logger's `log()` which
        # would update `extra` with its own contexts, and so on.
        #
        # Note that `extra` in this method and `extra` passed to logging method - message's `extra` - are two
        # completely different variables. Both specify fields to add to the emitted log record, and it is expected to
        # merge message's `extra` with those of loggers and adapters, and we make sure it happens, to comply with
        # expected logging behavior.
        #
        # Since message's `extra` is encountered by all loggers and adapters in the chain, we "hijack" it to carry
        # `contexts` item in which we collect all contexts from involved adapters.

        self._contexts = {}  # type: Dict[str, ContextInfoType]

        for name in iterkeys(contexts):
            self._contexts[name] = contexts[name]

        # Remove any `ctx_*` entries from `extra` container to our dedicated store. We don't wish these contexts
        # to materialize as record fields, we only want `contexts` field to appear, containing all the contexts.
        _move_contexts(extra, self._contexts)

        super(ContextAdapter, self).__init__(logger, extra)  # type: ignore  # base class expects just Logger

        self._logger = logger

        if PY2:
            self.name = logger.name  # type: str

    def addHandler(self, *args, **kwargs):
        # type: (*Any, **Any) -> None

        self._logger.addHandler(*args, **kwargs)

    def removeHandler(self, *args, **kwargs):
        # type: (*Any, **Any) -> None

        self._logger.removeHandler(*args, **kwargs)

    def process(self, msg, kwargs):
        # type: (str, MutableMapping[str, Any]) -> Tuple[str, MutableMapping[str, Any]]

        # Original `process` overwrites `kwargs['extra']` which doesn't work for us - we want to chain adapters,
        # getting more and more contexts on the way. Therefore `update` instead of assignment.

        # kwargs are passed down the chain of loggers. Its `extra` item is a mapping of additional fields logging
        # subsystem would create in the `Logging.LogRecord` object. Context adapters cooperate by using
        # `extra['contexts']` to collect all contexts from involved adapters.

        # First, make sure `extra` exists, and that it is a dictionary.
        extra = kwargs.get('extra', {})

        if extra is None:
            extra = {}

        # If `extra` is set and it's not a dictionary, replace it with a dictionary, but save the original value.
        if not isinstance(extra, dict):
            extra = {
                'legacy-extra': extra
            }

        # Next, add our contexts to the shared aggregation mapping. Make sure to initialize it properly.
        contexts = extra.get('contexts', {})
        contexts.update(self._contexts.copy())

        # Move any contexts from `extra` to this mapping, too - it's not common but e.g. `verbose` adds
        # `ctx_verbose_tag` context this way, because `verbose` is not tied to any particular adapter.
        _move_contexts(extra, contexts)

        # Now, this is what adapters are supposed to do: merge their `self.extra` into what's been given to the logging
        # method. Note that we took care about removing any contexts from adapter's `extra` and from the `extra`
        # parameter.
        extra.update(self.extra)  # type: ignore  # `self.extra` does exist

        # Force aggregation store into the `extra` parameter - it may have been missing, see the initialization above.
        extra['contexts'] = contexts

        # Save updated `extra` value back to `kwargs`. It may have been `None`, but from now on it's a dictionary,
        # with an item dedicated to context aggregation.
        kwargs['extra'] = extra

        return msg, kwargs

    # pylint: disable=too-many-arguments,arguments-differ
    def log(self, level, msg, exc_info=None, extra=None, sentry=False):  # type: ignore  #  Signature of "log" incompatible with supertype "LoggerAdapter"
        # type: (int, str, Optional[ExceptionInfoType], Optional[Dict[str, Any]], bool) -> None

        msg, kwargs = self.process(
            msg,
            # yes, process doesn't accept **kwargs...
            {
                'exc_info': exc_info,
                'extra': extra
            }
        )

        self._logger.log(level, msg, **kwargs)

        if sentry and Logging.sentry:
            Logging.sentry.submit_message(msg, logger=self)

    def isEnabledFor(self, level):
        # type: (int) -> Any

        return self._logger.isEnabledFor(level)

    def verbose(self, msg, exc_info=None, extra=None, sentry=False):
        # type: (str, Optional[ExceptionInfoType], Optional[Dict[str, Any]], bool) -> None

        if not self.isEnabledFor(VERBOSE):
            return

        # When we are expected to emit record of VERBOSE level, make a DEBUG note
        # as well, to "link" debug and verbose outputs. With this, one might read
        # DEBUG log, and use this reference to find corresponding VERBOSE record.
        # Adding time.time() as a salt - tag is based on message hash, it may be
        # logged multiple times, leading to the same tag.
        tag = hashlib.md5(ensure_binary('{}: {}'.format(time.time(), msg))).hexdigest()

        # add verbose tag as a context, with very high priority
        extra = extra or {}

        extra['ctx_verbose_tag'] = (1000, 'VERBOSE {}'.format(tag))

        # Verbose message should give some hint. It must contain the tag, but it could also start
        # with a hint!
        keep_len = 12

        if len(msg) <= keep_len:
            hint = msg

        else:
            new_line_index = msg.find('\n')

            if new_line_index == -1:
                hint = '{}...'.format(msg[0:keep_len])

            elif new_line_index == keep_len:
                hint = msg

            elif new_line_index < keep_len:
                hint = msg[0:new_line_index]

            else:
                hint = '{}...'.format(msg[0:keep_len])

        placeholder_message = '{} (See "verbose" log for the actual message)'.format(hint)

        self.log(logging.DEBUG, placeholder_message, exc_info=exc_info, extra=extra, sentry=sentry)
        self.log(VERBOSE, msg, exc_info=exc_info, extra=extra, sentry=sentry)

    # Disabling type checking of logging methods' signatures - they differ from supertype's signatures
    # but that is on purpose.

    # pylint: disable=arguments-differ
    def debug(self, msg, exc_info=None, extra=None, sentry=False):  # type: ignore
        # type: (str, Optional[ExceptionInfoType], Optional[Dict[str, Any]], bool) -> None

        self.log(logging.DEBUG, msg, exc_info=exc_info, extra=extra, sentry=sentry)

    # pylint: disable=arguments-differ
    def info(self, msg, exc_info=None, extra=None, sentry=False):   # type: ignore
        # type: (str, Optional[ExceptionInfoType], Optional[Dict[str, Any]], bool) -> None

        self.log(logging.INFO, msg, exc_info=exc_info, extra=extra, sentry=sentry)

    # pylint: disable=arguments-differ
    def warning(self, msg, exc_info=None, extra=None, sentry=False):   # type: ignore
        # type: (str, Optional[ExceptionInfoType], Optional[Dict[str, Any]], bool) -> None

        self.log(logging.WARNING, msg, exc_info=exc_info, extra=extra, sentry=sentry)

    warn = warning  # type: ignore

    # pylint: disable=arguments-differ
    def error(self, msg, exc_info=None, extra=None, sentry=False):   # type: ignore
        # type: (str, Optional[ExceptionInfoType], Optional[Dict[str, Any]], bool) -> None

        self.log(logging.ERROR, msg, exc_info=exc_info, extra=extra, sentry=sentry)

    # pylint: disable=arguments-differ
    def exception(self, msg, exc_info=None, extra=None, sentry=False):   # type: ignore
        # type: (str, Optional[ExceptionInfoType], Optional[Dict[str, Any]], bool) -> None

        self.log(logging.ERROR, msg, exc_info=exc_info, extra=extra, sentry=sentry)


class ModuleAdapter(ContextAdapter):
    """
    Custom logger adapter, adding module name as a context.

    :param logger: parent logger this adapter modifies.
    :param gluetool.glue.Module module: module whose name is added as a context.
    """

    # pylint: disable=too-few-public-methods

    def __init__(self, logger, module):
        # type: (ContextAdapter, gluetool.glue.Module) -> None

        super(ModuleAdapter, self).__init__(logger, contexts={'module_name': (10, module.unique_name)})


class LoggerMixin(object):
    """
    Use as a parent class (or one of them) when you want to "attach" methods of a given
    logger to class' instances.

    :param ContextAdapter logger: logger to propagate.
    """

    # pylint: disable=too-few-public-methods

    def __init__(self, logger, *args, **kwargs):
        # type: (ContextAdapter, *Any, **Any) -> None

        super(LoggerMixin, self).__init__(*args, **kwargs)  # type: ignore  # Too many arguments - it's fine...

        self.attach_logger(logger)

    def attach_logger(self, logger):
        # type: (ContextAdapter) -> None
        """
        Initialize this object's logging methods to those provided by a given ``logger``.
        """

        self.logger = logger

        self.log = logger.log
        self.verbose = logger.verbose
        self.debug = logger.debug
        self.info = logger.info
        self.warning = self.warn = logger.warning
        self.error = logger.error
        self.exception = logger.exception


class PackageAdapter(ContextAdapter):
    """
    Custom logger dapter, adding a package name as a context. Intended to taint log
    records produced by a 3rd party packages.

    :param logger: parent logger this adapter modifies.
    :param str name: name of the library.
    """

    def __init__(self, logger, name):
        # type: (ContextAdapter, str) -> None

        super(PackageAdapter, self).__init__(logger, contexts={'package_name': (50, name)})


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
        VERBOSE: 'V',
        logging.DEBUG: 'D',
        logging.INFO: '+',
        logging.WARNING: 'W',
        logging.ERROR: 'E',
        logging.CRITICAL: 'C'
    }

    #: Colorizers assigned to loglevels
    # pylint: disable=not-callable
    _level_color = {
        logging.INFO: lambda text: Colors.style(text, fg='green'),
        logging.WARNING: lambda text: Colors.style(text, fg='yellow'),
        logging.ERROR: lambda text: Colors.style(text, fg='red'),
        logging.CRITICAL: lambda text: Colors.style(text, fg='red')
    }  # type: Dict[int, Callable[[str], str]]

    def __init__(self, colors=True, log_tracebacks=False, prettify=False):
        # type: (bool, bool, bool) -> None

        super(LoggingFormatter, self).__init__()

        self.colors = colors
        self.log_tracebacks = log_tracebacks
        self.prettify = prettify

    @staticmethod
    def _format_exception_chain(exc_info):
        # type: (Any) -> str
        """
        Format exception chain. Start with the one we're given, and follow its `caused_by` property
        until we ran out of exceptions to format.
        """

        tmpl = jinja2.Template(_TRACEBACK_TEMPLATE)

        output = ['']

        # Format one exception and its traceback
        def _add_block(label, exc, trace):
            # type: (str, Exception, Any) -> None

            stack = _extract_stack(trace)

            output.append(
                ensure_str(tmpl.render(label=label, exception=exc, stack=stack, iterkeys=iterkeys))
            )

        # This is the most recent exception, we start with this one - it's often the one most visible,
        # exceptions that caused it are usualy hidden from user's sight.
        _add_block('Exception', exc_info[1], exc_info[2])

        # Iterate over any previous exceptions and format them as well.
        while getattr(exc_info[1], 'caused_by', None) is not None:
            exc_info = exc_info[1].caused_by

            _add_block('Caused by', exc_info[1], exc_info[2])

        return '\n'.join(output).strip()

    def format(self, record):
        # type: (logging.LogRecord) -> str

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
        }  # type: Dict[str, str]

        handler_logs_traceback = self.log_tracebacks is True \
            or (Logging.stderr_handler is not None and Logging.stderr_handler.level in (logging.DEBUG, VERBOSE))

        if record.exc_info and record.exc_info != (None, None, None) and handler_logs_traceback:
            fmt.append('{exc_text}')

            # \n helps formatting - logging would add formatted chain right after the leading message
            # without starting new line. We must do it, to make report more readable.
            values['exc_text'] = '\n\n' + LoggingFormatter._format_exception_chain(record.exc_info)

        # Add record contexts to the message formatting string
        contexts = getattr(record, 'contexts', {})

        if contexts:
            # we don't have access to log record any time sooner, therefore adding thread context here
            _add_thread_context(contexts, record)

            # Sorted by priorities, the higher the priority, the more on the right the context should stand
            # in the message:
            #
            #   [ctx prio 10] [ctx prio 20] [ctx prio 1000]
            #
            # We're inserting contexts into `fmt` one by one, at the same spot. Once inserted, following inserts
            # will shift the context more to the right. That means the higher priority contexts should be inserted
            # sooner.
            #
            # [ctx prio 1000] => [ctx prio 20] [ctx prio 1000] => [ctx prio 10] [ctx prio 20] [ctx prio 1000]
            #
            # Regular sort would yield contexts by their priorities from lower to higher ones, therefore reversed flag.
            # That way we'd start inserting higher priority contexts sooner than lower priority ones.

            # Mypy is not happy about lambda function: https://github.com/python/mypy/issues/9656#issuecomment-718284938
            sorted_contexts = sorted(
                iterkeys(contexts),
                key=lambda ctx_name: contexts[ctx_name][0],  # type: ignore
                reverse=True
            )

            for name in sorted_contexts:
                _, value = contexts[name]

                fmt.insert(2, '[{%s}]' % name)
                values[name] = value

        # format message
        msg = ' '.join(fmt).format(**values)

        if self.colors and record.levelno in self._level_color:
            msg = self._level_color[record.levelno](msg)

        return msg


class JSONLoggingFormatter(logging.Formatter):
    """
    Custom logging formatter producing a JSON dictionary describing the log record.
    """

    def __init__(self, colors=False, log_tracebacks=False, prettify=False):
        # type: (bool, bool, bool) -> None
        # pylint: disable=unused-argument

        super(JSONLoggingFormatter, self).__init__()

        if prettify:
            self._emit = format_dict

        else:
            self._emit = _json_dump  # type: ignore

    @staticmethod
    def _format_exception_chain(serialized, exc_info):
        # type: (Dict[str, Any], ExceptionInfoType) -> None
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
            # type: (Optional[BaseException], Optional[TracebackType]) -> None

            if exc:
                exc_module, exc_class, exc_message = exc.__class__.__module__, exc.__class__.__name__, str(exc)

            else:
                exc_module, exc_class, exc_message = '', '', ''

            stack = _extract_stack(tb) if tb else []

            serialized['caused_by'].append({
                'exception': {
                    'class': '{}.{}'.format(exc_module, exc_class),
                    'message': exc_message
                },
                'traceback': [
                    {
                        'filename': filename,
                        'lineno': lineno,
                        'fnname': fnname,
                        'text': text,
                        'locals': {
                            local_var_name: {
                                'type': type(local_var_value),
                                'value': local_var_value
                            } for local_var_name, local_var_value in iteritems(frame.f_locals)
                        }
                    }
                    for filename, lineno, fnname, text, frame in stack
                ]
            })

        _add_cause(exc_info[1], exc_info[2])

        while exc_info[1] and getattr(exc_info[1], 'caused_by', None) is not None:
            exc_info = exc_info[1].caused_by  # type: ignore  # it *does* have `caused_by` attribute

            _add_cause(exc_info[1], exc_info[2])

    def format(self, record):
        # type: (logging.LogRecord) -> str

        # Construct a huuuuge dictionary describing the event
        serialized = {
            field: getattr(record, field, None)
            for field in (
                # LogRecord properties
                'args', 'created', 'exc_info', 'exc_text', 'filename', 'funcName', 'levelname', 'levelno',
                'lineno', 'module', 'msecs', 'msg', 'name', 'pathname', 'process', 'processName',
                'relativeCreated', 'thread', 'threadName',
                # our custom fields
                'raw_blob', 'raw_struct', 'raw_table', 'raw_xml', 'raw_intro'
            )
        }

        serialized['message'] = record.getMessage()

        contexts = getattr(record, 'contexts', {})

        if contexts:
            # we don't have access to log record any time sooner, therefore adding thread context here
            _add_thread_context(contexts, record)

            serialized['contexts'] = {
                name: {
                    'priority': contexts[name][0],
                    'value': contexts[name][1]
                }
                for name in iterkeys(contexts)
            }

        else:
            serialized['contexts'] = {}

        if record.exc_info:
            JSONLoggingFormatter._format_exception_chain(serialized, record.exc_info)

        return ensure_str(self._emit(serialized))


class Logging(object):
    """
    Container wrapping configuration and access to :py:mod:`logging` infrastructure ``gluetool``
    uses for logging.
    """

    #: Logger singleton - if anyone asks for a logger, they will get this one. Needs
    #: to be properly initialized by calling :py:meth:`setup_logger`.
    adapted_logger = None  # type: ContextAdapter

    #: Bare root logger we're hiding inside ``adapted_logger``
    logger = None  # logging.Logger

    #: Stream handler printing out to stderr.
    stderr_handler = None  # type: logging.StreamHandler

    debug_file_handler = None
    verbose_file_handler = None
    json_file_handler = None

    sentry = None  # type: Optional[gluetool.sentry.Sentry]

    @staticmethod
    def get_logger():
        # type: () -> ContextAdapter

        """
        Returns a logger-like object suitable for logging stuff.

        :rtype: ContextAdapter
        :returns: an instance of ContextAdapter wrapping root logger, or ``None`` when there's no logger yet.
        """

        if Logging.logger is None:
            Logging.setup_logger()

        if Logging.adapted_logger is None:
            Logging.adapted_logger = ContextAdapter(Logging.logger)

        return Logging.adapted_logger

    # Following methods are intended for 3rd party loggers one might want to connect to our
    # logging configuration. Gluetool will configure properly its own logger and few others
    # it knows about (e.g. "requests" has one interesting), but it has no idea what other
    # loggers might be interesting for module developer. Therefore, these methods are used
    # to A) setup loggers gluetool knows about, and B) public to allow module developer
    # attach arbitrary loggers.

    @staticmethod
    def configure_logger(logger):
        # type: (logging.Logger) -> None
        """
        Configure given logger to conform with Gluetool's idea of logging. The logger is set to
        ``VERBOSE`` level, shared stderr handler is added, and Sentry integration status is
        propagated as well.

        After this method, the logger will behave like Gluetool's main logger.
        """

        logger.propagate = False

        # logger actually emits everything, handlers do filtering
        logger.setLevel(VERBOSE)

        # add stderr handler
        logger.addHandler(Logging.stderr_handler)

        # Extra handling for Jaeger logger:
        # - replace it with a context adapter to keep track of what's being done by Jaeger code,
        # - patch its `info` with `debug` - Jaeger is logging things with INFO severity, which spoils
        #   our output, DEBUG is perfectly fine for us.
        jaeger_logger = logging.getLogger('jaeger_tracing')

        if logger == jaeger_logger:
            jaeger_context_adapter = PackageAdapter(Logging.get_logger(), 'tracing')

            for attr in ('debug', 'info', 'warning', 'error', 'exception'):
                setattr(logger, attr, getattr(jaeger_context_adapter, attr))

            logger.info = logger.debug  # type: ignore

    @staticmethod
    def enable_logger_sentry(logger):
        # type: (Union[logging.Logger, ContextAdapter]) -> None

        if not Logging.sentry:
            return

        Logging.sentry.enable_logging_breadcrumbs(logger)

    @staticmethod
    def enable_debug_file(logger):
        # type: (Union[logging.Logger, ContextAdapter]) -> None

        if not Logging.debug_file_handler:
            return

        logger.addHandler(Logging.debug_file_handler)

    @staticmethod
    def enable_verbose_file(logger):
        # type: (Union[logging.Logger, ContextAdapter]) -> None

        if not Logging.verbose_file_handler:
            return

        logger.addHandler(Logging.verbose_file_handler)

    @staticmethod
    def enable_json_file(logger):
        # type: (Union[logging.Logger, ContextAdapter]) -> None

        if not Logging.json_file_handler:
            return

        logger.addHandler(Logging.json_file_handler)

    OUR_LOGGERS = (
        logging.getLogger('gluetool'),
        logging.getLogger('jaeger_tracing'),
        logging.getLogger('urllib3')
    )

    @staticmethod
    def _setup_log_file(filepath,  # type: str
                        level,  # type: int
                        limit_level=False,  # type: bool
                        formatter_class=LoggingFormatter,  # type: Type[Union[LoggingFormatter, JSONLoggingFormatter]]
                        prettify=False  # type: bool
                       ):  # noqa
        # type: (...) -> Optional[logging.FileHandler]

        if filepath is None:
            return None

        if limit_level:
            handler = SingleLogLevelFileHandler(level, filepath, 'w')  # type: logging.FileHandler

        else:
            handler = logging.FileHandler(filepath, 'w')

        handler.setLevel(level)

        formatter = formatter_class(colors=False, log_tracebacks=True, prettify=prettify)
        handler.setFormatter(formatter)

        def _close_log_file():
            # type: () -> None

            logger = Logging.get_logger()

            logger.debug("closing output file '{}'".format(filepath))

            handler.flush()
            handler.close()

            logger.removeHandler(handler)

        atexit.register(_close_log_file)

        Logging.get_logger().debug("created output file '{}'".format(filepath))

        return handler

    # pylint: disable=too-many-arguments,line-too-long
    @staticmethod
    def setup_logger(level=DEFAULT_LOG_LEVEL,  # type: int
                     debug_file=None,  # type: Optional[str]
                     verbose_file=None,  # type: Optional[str]
                     json_file=None,  # type: Optional[str]
                     json_file_pretty=False,  # type: bool
                     json_output=False,  # type: bool
                     json_output_pretty=False,  # type: bool
                     sentry=None,  # type: Optional[gluetool.sentry.Sentry]
                     show_traceback=False  # type: bool
                    ):  # noqa
        # type: (...) -> ContextAdapter

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
        :param bool json_output: if set, all logging messages sent to the terminal are emitted as
            JSON structures.
        :param int level: desired log level. One of constants defined in :py:mod:`logging` module,
            e.g. :py:data:`logging.DEBUG` or :py:data:`logging.ERROR`.
        :param bool sentry: if set, logger will be augmented to send every log message to the Sentry
            server.
        :param bool show_traceback: if set, exception tracebacks would be sent to ``stderr`` handler
            as well as to the debug file.
        :rtype: ContextAdapter
        :returns: a :py:class:`ContextAdapter` instance, set up for logging.
        """

        level = level or logging.INFO

        # store for later use by configure_logger & co.
        Logging.sentry = sentry

        if Logging.logger is None:
            # we're doing the very first setup of logging handlers, therefore create new stderr handler,
            # configure it and attach it to correct places
            Logging.stderr_handler = logging.StreamHandler()
            Logging.stderr_handler.setLevel(level)

            # create our main logger
            Logging.logger = logging.getLogger('gluetool')

            # setup all loggers we're interested in
            list(map(Logging.configure_logger, Logging.OUR_LOGGERS))

        # set formatter
        if json_output:
            Logging.stderr_handler.setFormatter(JSONLoggingFormatter(prettify=json_output_pretty))

        else:
            Logging.stderr_handler.setFormatter(LoggingFormatter())

        # set log level to new value
        Logging.stderr_handler.setLevel(level)

        # honor traceback display setup
        assert Logging.stderr_handler.formatter is not None
        Logging.stderr_handler.formatter.log_tracebacks = show_traceback  # type: ignore

        # create debug and verbose files
        if debug_file:
            Logging.debug_file_handler = Logging._setup_log_file(debug_file, logging.DEBUG)

        if verbose_file:
            Logging.verbose_file_handler = Logging._setup_log_file(verbose_file, VERBOSE, limit_level=True)

        if json_file:
            Logging.json_file_handler = Logging._setup_log_file(
                json_file,
                VERBOSE,
                formatter_class=JSONLoggingFormatter,
                prettify=json_file_pretty
            )

        # now our main logger should definitely exist and it should be usable
        logger = Logging.get_logger()

        logger.debug('logger setup: level={}, debug file={}, verbose file={}, json file={}, sentry={}, show traceback={}'.format(
            level,
            debug_file,
            verbose_file,
            json_file,
            'yes' if sentry else 'no',
            show_traceback
        ))

        # Enable Sentry
        Logging.enable_logger_sentry(logger)

        list(map(Logging.enable_logger_sentry, Logging.OUR_LOGGERS))

        # Enable debug and verbose files
        Logging.enable_debug_file(logger)
        Logging.enable_verbose_file(logger)
        Logging.enable_json_file(logger)

        list(map(Logging.enable_debug_file, Logging.OUR_LOGGERS))
        list(map(Logging.enable_verbose_file, Logging.OUR_LOGGERS))
        list(map(Logging.enable_json_file, Logging.OUR_LOGGERS))

        return logger


# Add log-level => label translation for our custom VERBOSE level
logging.addLevelName(VERBOSE, 'VERBOSE')
