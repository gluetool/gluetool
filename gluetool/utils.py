# pylint: disable=too-many-lines

"""
Various helpers.
"""

import collections
import contextlib
import errno
import functools
import httplib
import json
import os
import pipes
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib2
import warnings

import bs4
import urlnorm
import jinja2
import requests as original_requests

# Don't know why pylint reports "Relative import 'ruamel.yaml', should be 'gluetool.ruamel.yaml'" :(
# pylint: disable=relative-import
import ruamel.yaml

from gluetool import GlueError, SoftGlueError, GlueCommandError
from gluetool.log import Logging, ContextAdapter, log_blob, BlobLogger, format_dict, log_dict, print_wrapper, \
    PackageAdapter


try:
    # pylint: disable=ungrouped-imports
    from subprocess import DEVNULL
except ImportError:
    DEVNULL = open(os.devnull, 'wb')


def deprecated(func):
    """
    This is a decorator which can be used to mark functions as deprecated. It will result in a warning being emitted
    when the function is used.
    """

    @functools.wraps(func)
    def new_func(*args, **kwargs):
        warnings.simplefilter('always', DeprecationWarning)  # turn off filter
        warnings.warn('Function {} is deprecated.'.format(func.__name__), category=DeprecationWarning,
                      stacklevel=2)
        warnings.simplefilter('default', DeprecationWarning)  # reset filter

        return func(*args, **kwargs)

    return new_func


def dict_update(dst, *args):
    """
    Python's ``dict.update`` does not return the dictionary just updated but a ``None``. This function
    is a helper that does updates the dictionary *and* returns it. So, instead of:

    .. code-block:: python

       d.update(other)
       return d

    you can use:

    .. code-block:: python

       return dict_update(d, other)

    :param dict dst: dictionary to be updated.
    :param args: dictionaries to update ``dst`` with.
    """

    for other in args:
        assert isinstance(other, dict)

        dst.update(other)

    return dst


def normalize_bool_option(option_value):
    """
    Convert option value to Python's boolean.

    ``option_value`` is what all those internal option processing return,
    which may be a default value set for an option, or what user passed in.

    As switches, options with values can be used:

    .. code-block:: bash

       --foo=yes|no
       --foo=true|false
       --foo=1|0
       --foo=Y|N
       --foo=on|off

    With combination of ``store_true``/``store_false`` and a default value module developer
    sets for the option, simple form without value is evaluated as easily. With ``store_true``
    and ``False`` default, following option turn the feature `foo` on:

    .. code-block:: bash

       --enable-foo

    With ``store_false`` and ``True`` default, following simple option turn the feature `foo` off:

    .. code-block:: bash

       --disable-foo
    """

    if str(option_value).strip().lower() in ('yes', 'true', '1', 'y', 'on'):
        return True

    return False


def normalize_multistring_option(option_value, separator=','):
    """
    Reduce string, representing comma-separated list of items, or possibly a list of such strings,
    to a simple list of items. Strips away the whitespace wrapping such items.

    .. code-block:: bash

        foo --option value1 --option value2, value3
        foo --option value1,value2,value3

    Or, when option is set by a config file:

    .. code-block:: bash

        option = value1
        option = value1, value2, \
                 value3

    After processing, different variants can be found when ``option('option')`` is called,
    ``['value1', 'value2,value3']``, ``['value1,value2,value3']``, ``'value1'`` and ``value1, value2, value3``.

    To reduce the necessary work, use this helper function to treat such option's value,
    and get simple ``['value1', 'value2', 'value3']`` structure.
    """

    if option_value is None:
        return []

    # If the value is string, convert it to list - it comes from a config file,
    # command-line parsing always produces a list. This reduces config file values
    # to the same structure command-line produces.
    values = [option_value] if isinstance(option_value, str) else option_value

    # Now deal with possibly multiple paths, separated by comma and some white space, inside
    # every item of the list. Split the paths in the item by the given separator, strip the
    # white space, and concatenate these lists (one for each item in the main `values` list)
    # using sum - with an empty list as a start, it works for lists just as nicely.
    return sum([
        [value.strip() for value in item.split(separator)] for item in values
    ], [])


def normalize_shell_option(option_value):
    """
    Reduce string, using a shell-like syntax, or possibly a list of such strings,
    to a simple list of items. Strips away the whitespace wrapping such items.

    .. code-block:: bash

        foo --option value1 --option value2\\ value3 --option "value4 value5"

    Or, when option is set by a config file:

    .. code-block:: bash

        option = value1 value2\\ value3 "value4 value5"

    After processing, different variants can be found when ``option('option')`` is called,
    ``['value1', 'value2,value3']``, ``['value1,value2,value3']``, ``'value1'`` and ``value1, value2, value3``.

    To reduce the necessary work, use this helper function to treat such option's value,
    and get simple ``['value1', 'value2 value3', 'value4 value5']`` structure.
    """

    if not option_value:
        return []

    # If the value is string, convert it to list - it comes from a config file,
    # command-line parsing always produces a list. This reduces config file values
    # to the same structure command-line produces.
    values = [option_value] if isinstance(option_value, str) else option_value

    # Now split each item using shlex, and merge these lists into a single one.
    return sum([
        shlex.split(value) for value in values
    ], [])


def normalize_path(path):
    """
    Apply common treatments on a given path:

        * replace home directory reference (``~`` and similar), and
        * convert ``path`` to a normalized absolutized version of the pathname.
    """

    return os.path.abspath(os.path.expanduser(path))


def normalize_path_option(option_value, separator=','):
    """
    Reduce many ways how list of paths is specified by user, to a simple list of paths. See
    :py:func:`normalize_multistring_option` for more details.
    """

    return [normalize_path(path) for path in normalize_multistring_option(option_value, separator=separator)]


class IncompatibleOptionsError(SoftGlueError):
    pass


class Bunch(object):
    # pylint: disable=too-few-public-methods

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ThreadAdapter(ContextAdapter):
    """
    Custom logger adapter, adding thread name as a context.

    :param gluetool.log.ContextAdapter logger: parent logger whose methods will be used for logging.
    :param threading.Thread thread: thread whose name will be added.
    """

    def __init__(self, logger, thread):
        super(ThreadAdapter, self).__init__(logger, {'ctx_thread_name': (5, thread.name)})


class WorkerThread(threading.Thread):
    """
    Worker threads gets a job to do, and returns a result. It gets a callable, ``fn``,
    which will be called in thread's ``run()`` method, and thread's ``result`` property
    will be the result - value returned by ``fn``, or exception raised during the
    runtime of ``fn``.

    :param gluetool.log.ContextAdapter logger: logger to use for logging.
    :param fn: thread will start `fn` to do the job.
    :param fn_args: arguments for `fn`
    :param fn_kwargs: keyword arguments for `fn`
    """

    def __init__(self, logger, fn, fn_args=None, fn_kwargs=None, **kwargs):
        threading.Thread.__init__(self, **kwargs)

        self.logger = ThreadAdapter(logger, self)
        self.logger.connect(self)

        self._fn = fn
        self._args = fn_args or ()
        self._kwargs = fn_kwargs or {}

        self.result = None

    def run(self):
        self.debug('worker thread started')

        try:
            self.result = self._fn(*self._args, **self._kwargs)

        # pylint: disable=broad-except
        except Exception as e:
            self.exception('exception raised in worker thread: {}'.format(str(e)))
            self.result = e

        finally:
            self.debug('worker thread finished')


class StreamReader(object):
    def __init__(self, stream, name=None, block=16):
        """
        Wrap blocking ``stream`` with a reading thread. The threads read from
        the (normal, blocking) `stream` and adds bits and pieces into the `queue`.
        ``StreamReader`` user then can check the `queue` for new data.
        """

        self._stream = stream
        self._name = name or stream.name

        # List would fine as well, however deque is better optimized for
        # FIFO operations, and it provides the same thread safety.
        self._queue = collections.deque()
        self._content = []

        def _enqueue():
            """
            Read what's available in stream and add it into the queue
            """

            while True:
                data = self._stream.read(block)

                if not data:
                    # signal EOF
                    self._queue.append('')
                    return

                self._queue.append(data)
                self._content.append(data)

        self._thread = threading.Thread(target=_enqueue)
        self._thread.daemon = True
        self._thread.start()

    @property
    def name(self):
        return self._name

    @property
    def content(self):
        return ''.join(self._content)

    def wait(self):
        self._thread.join()

    def read(self):
        try:
            return self._queue.popleft()

        except IndexError:
            return None


class ProcessOutput(object):
    """
    Result of external process.
    """

    # pylint: disable=too-many-arguments,too-few-public-methods
    def __init__(self, cmd, exit_code, stdout, stderr, kwargs):
        self.cmd = cmd
        self.kwargs = kwargs

        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def log_stream(self, stream, logger):
        content = getattr(self, stream)

        if content is None:
            if stream in self.kwargs:
                logger.debug('{}:\n  command produced no output'.format(stream))
            else:
                logger.debug('{}:\n  command forwarded the output to its parent'.format(stream))

        else:
            log_blob(logger.verbose, stream, content)

    def log(self, logger):
        logger.debug('command exited with code {}'.format(self.exit_code))

        self.log_stream('stdout', logger)
        self.log_stream('stderr', logger)


class Command(object):
    """
    Wrap an external command, its options and other information, necessary for running the command.

    The main purpose is to gather all relevant pieces into a single space, call :py:class:`subprocess.Popen`,
    and log everything.

    By default, both standard output and error output are of the process are captured and returned back to
    caller. Under some conditions, caller might want to see the output in "real-time". For that purpose,
    they can pass callable via ``inspect_callback`` parameter - such callable will be called for every received
    bit of input on both standard and error outputs. E.g.

    .. code-block:: python

       def foo(stream, s, flush=False):
           if s is not None and 'a' in s:
               print s

       Command(['/bin/foo']).run(inspect=foo)

    This example will print all substrings containing letter `a`. Strings passed to ``foo`` may be of arbitrary
    lengths, and may change between subsequent use of ``Command`` class.

    :param list executable: Executable to run. Feel free to use the whole command, including its options,
        if you have no intention to modify them before running the command.
    :param list options: If set, it's a list of options to pass to the ``executable``. Options are
        specified in a separate list to allow modifications of ``executable`` and ``options``
        before actually running the command.
    :param gluetool.log.ContextAdapter logger: Parent logger whose methods will be used for logging.


    .. versionadded:: 1.1
    """

    # pylint: disable=too-few-public-methods

    def __init__(self, executable, options=None, logger=None):
        self.logger = logger or ContextAdapter(Logging.get_logger())
        self.logger.connect(self)

        self.executable = executable
        self.options = options or []

        self.use_shell = False
        self.quote_args = False

        self._command = None
        self._popen_kwargs = None
        self._process = None
        self._exit_code = None

        self._stdout = None
        self._stderr = None

    def _apply_quotes(self):
        """
        Return options to pass to ``Popen``. Applies quotes as necessary.
        """

        if not self.quote_args:
            return self.executable + self.options

        # escape apostrophes in strings and adds them around strings with space
        return [('"{}"'.format(option.replace('"', r'\"')) if ' ' in option and not
                 (
                     (option.startswith('"') and option.endswith('"')) or
                     (option.startswith("'") and option.endswith("'")))
                 else option) for option in self.executable + self.options]

    def _communicate_batch(self):
        self._stdout, self._stderr = self._process.communicate()

    def _communicate_inspect(self, inspect_callback):
        # let's capture *both* streams - capturing just a single one leads to so many ifs
        # and elses and messy code
        p_stdout = StreamReader(self._process.stdout, name='<stdout>')
        p_stderr = StreamReader(self._process.stderr, name='<stderr>')

        if inspect_callback is None:
            def stdout_write(stream, data, flush=False):
                # pylint: disable=unused-argument

                if data is None:
                    return

                # Not suitable for multiple simultaneous commands. Shuffled output will
                # ruin your day. And night. And few following weeks, full of debugging, as well.
                sys.stdout.write(data)
                sys.stdout.flush()

            inspect_callback = stdout_write

        inputs = (p_stdout, p_stderr)

        with BlobLogger('Output of command: {}'.format(format_command_line([self._command])),
                        outro='End of command output',
                        writer=self.info):
            self.debug("output of command is inspected by the caller")
            self.debug('following blob-like header and footer are expected to be empty')
            self.debug('the captured output will follow them')

            # As long as process runs, keep calling callbacks with incoming data
            while True:
                for stream in inputs:
                    inspect_callback(stream, stream.read())

                if self._process.poll() is not None:
                    break

                # give up OS' attention and let others run
                # time.sleep(0) is a Python synonym for "thread yields the rest of its quantum"
                time.sleep(0.1)

            # OK, process finished but we have to wait for our readers to finish as well
            p_stdout.wait()
            p_stderr.wait()

            for stream in inputs:
                while True:
                    data = stream.read()

                    if data in ('', None):
                        break

                    inspect_callback(stream, data)

                inspect_callback(stream, None, flush=True)

        self._stdout, self._stderr = p_stdout.content, p_stderr.content

    def _construct_output(self):
        output = ProcessOutput(self._command, self._exit_code, self._stdout, self._stderr, self._popen_kwargs)

        output.log(self.logger)

        return output

    def run(self, inspect=False, inspect_callback=None, **kwargs):
        """
        Run the command, wait for it to finish and return the output.

        :param bool inspect: If set, ``inspect_callback`` will receive the output of command in "real-time".
        :param callable inspect_callback: callable that will receive command output. If not set, default
            "write to ``sys.stdout``" is used.
        :rtype: gluetool.utils.ProcessOutput instance
        :returns: :py:class:`gluetool.utils.ProcessOutput` instance whose attributes contain data returned
            by the child process.
        :raises gluetool.glue.GlueError: When somethign went wrong.
        :raises gluetool.glue.GlueCommandError: When command exited with non-zero exit code.
        """

        # pylint: disable=too-many-branches

        def _check_types(items):
            if not isinstance(items, list):
                raise GlueError('Only list of strings is accepted')

            if not all((isinstance(s, str) for s in items)):
                raise GlueError('Only list of strings is accepted, {} found'.format([type(s) for s in items]))

        _check_types(self.executable)
        _check_types(self.options)

        self._command = self._apply_quotes()

        if self.use_shell is True:
            self._command = [' '.join(self._command)]

        # Set default stdout/stderr, unless told otherwise
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.PIPE

        if 'stderr' not in kwargs:
            kwargs['stderr'] = subprocess.PIPE

        if self.use_shell:
            kwargs['shell'] = True

        self._popen_kwargs = kwargs

        def _format_stream(stream):
            if stream == subprocess.PIPE:
                return 'PIPE'
            if stream == DEVNULL:
                return 'DEVNULL'
            if stream == subprocess.STDOUT:
                return 'STDOUT'
            return stream

        printable_kwargs = kwargs.copy()
        for stream in ('stdout', 'stderr'):
            if stream in printable_kwargs:
                printable_kwargs[stream] = _format_stream(printable_kwargs[stream])

        log_dict(self.debug, 'command', self._command)
        log_dict(self.debug, 'kwargs', printable_kwargs)
        log_blob(self.debug, 'runnable (copy & paste)', format_command_line([self._command]))

        try:
            self._process = subprocess.Popen(self._command, **self._popen_kwargs)

            if inspect is True:
                self._communicate_inspect(inspect_callback)

            else:
                self._communicate_batch()

        except OSError as e:
            if e.errno == errno.ENOENT:
                raise GlueError("Command '{}' not found".format(self._command[0]))

            raise e

        self._exit_code = self._process.poll()

        output = self._construct_output()

        if self._exit_code != 0:
            raise GlueCommandError(self._command, output)

        return output


@deprecated
def run_command(cmd, logger=None, **kwargs):
    """
    Wrapper for ``Command(...).run().

    Provided for backward compatibility.

    .. deprecated:: 1.1

        Use :py:class:`gluetool.utils.Command` instead.
    """

    return Command(cmd, logger=logger).run(**kwargs)


def check_for_commands(cmds):
    """ Checks if all commands in list cmds are valid """
    for cmd in cmds:
        try:
            Command(['/bin/bash', '-c', 'command -v {}'.format(cmd)]).run(stdout=DEVNULL)

        except GlueError:
            raise GlueError("Command '{}' not found on the system".format(cmd))


class cached_property(object):
    # pylint: disable=invalid-name,too-few-public-methods
    """
    ``property``-like decorator - at first access, it calls decorated
    method to acquire the real value, and then replaces itself with
    this value, making it effectively "cached". Useful for properties
    whose value does not change over time, and where getting the real
    value could penalize execution with unnecessary (network, memory)
    overhead.

    Delete attribute to clear the cached value - on next access, decorated
    method will be called again, to acquire the real value.

    Of possible options, only read-only instance attribute access is
    supported so far.
    """

    def __init__(self, method):
        self._method = method
        self.__doc__ = getattr(method, '__doc__')

    def __get__(self, obj, cls):
        # does not support class attribute access, only instance
        assert obj is not None

        # get the real value of this property
        value = self._method(obj)

        # replace cached_property instance with the value
        obj.__dict__[self._method.__name__] = value

        return value


def format_command_line(cmdline):
    """
    Return formatted command-line.

    All but the first line are indented by 4 spaces.

    :param list cmdline: list of iterables, representing command-line split to multiple lines.
    """

    def _format_options(options):
        return ' '.join([pipes.quote(opt) for opt in options])

    cmd = [_format_options(cmdline[0])]

    for row in cmdline[1:]:
        cmd.append('    ' + _format_options(row))

    return ' \\\n'.join(cmd)


@deprecated
def fetch_url(url, logger=None, success_codes=(200,)):
    """
    "Get me content of this URL" helper.

    Very thin wrapper around urllib. Added value is logging, and converting
    possible errors to :py:class:`gluetool.glue.GlueError` exception.

    :param str url: URL to get.
    :param gluetool.log.ContextLogger logger: Logger used for logging.
    :param tuple success_codes: tuple of HTTP response codes representing successfull request.
    :returns: tuple ``(response, content)`` where ``response`` is what :py:func:`urllib2.urlopen`
      returns, and ``content`` is the payload of the response.
    """

    logger = logger or Logging.get_logger()

    logger.debug("opening URL '{}'".format(url))

    try:
        response = urllib2.urlopen(url)
        code, content = response.getcode(), response.read()

    except urllib2.HTTPError as exc:
        logger.exception(exc)
        raise GlueError("Failed to fetch URL '{}': {}".format(url, exc.message))

    log_blob(logger.debug, '{}: {}'.format(url, code), content)

    if code not in success_codes:
        raise GlueError("Unsuccessfull response from '{}'".format(url))

    return response, content


@contextlib.contextmanager
def requests(logger=None):
    """
    Wrap :py:mod:`requests` with few layers providing us with the logging and better insight into
    what has been happening when ``requests`` did their job.

    Used as a context manager, yields a patched ``requests`` module. As long as inside the context,
    detailed information about HTTP traffic are logged via given logger.

    .. note::

       The original ``requests`` library is returned, with slight modifications for better integration
       with ``gluetool`` logging facilities. Each and every ``requests`` API feature is available
       and , hopefully, enhancements applied by this wrapper wouldn't interact with ``requests``
       functionality.

    .. code-block:: python

       with gluetool.utils.requests() as R:
           R.get(...).json()
           ...

           r = R.post(...)
           assert r.code == 404
           ...

    :param logger: used for logging.
    :returns: :py:mod:`requests` module.
    """

    # Enable httplib debugging. It's being used underneath ``requests`` and ``urllib3``,
    # but it's stupid - uses "print" instead of a logger, therefore we have to capture it
    # and disable debug logging when leaving the context.
    logger = logger or Logging.get_logger()
    httplib_logger = PackageAdapter(logger, 'httplib')

    httplib.HTTPConnection.debuglevel = 1

    # Start capturing ``print`` statements - they are used to provide debug messages, therefore
    # using ``debug`` level.
    with print_wrapper(log_fn=httplib_logger.debug):
        # To log responses and their content, we must take a look at ``Response`` instance
        # returned by several entry methods (``get``, ``post``, ...). To do that, we have
        # a simple wrapper function.

        # ``original_method`` is the actual ``requests.foo`` (``get``, ``post``, ...), wrapper
        # calls it to do the job, and logs response when it's done.
        def _verbose_request(original_method, *args, **kwargs):
            ret = original_method(*args, **kwargs)

            log_blob(logger.debug, 'response content', ret.text)

            return ret

        # gather the original methods...
        methods = {
            method_name: getattr(original_requests, method_name)
            for method_name in ('head', 'get', 'post', 'put', 'patch', 'delete')
        }

        # ... and replace them with our wrapper, giving it the original method as the first argument
        for method_name, original_method in methods.iteritems():
            setattr(original_requests, method_name, functools.partial(_verbose_request, original_method))

        try:
            yield original_requests

        finally:
            # put original methods back...
            for method_name, original_method in methods.iteritems():
                setattr(original_requests, method_name, original_method)

            # ... and disable httplib debugging
            httplib.HTTPConnection.debuglevel = 0


def treat_url(url, logger=None):
    """
    Remove "weird" artifacts from the given URL. Collapse adjacent '.'s, apply '..', etc.

    :param str url: URL to clear.
    :param gluetool.log.ContextAdapter logger: logger to use for logging.
    :rtype: str
    :returns: Treated URL.
    """

    logger = logger or Logging.get_logger()

    logger.debug("treating a URL '{}'".format(url))

    try:
        url = str(urlnorm.norm(url))

    except urlnorm.InvalidUrl as exc:
        # urlnorm cannot handle localhost: https://github.com/jehiah/urlnorm/issues/3
        if exc.message == "host u'localhost' is not valid":
            pass

        else:
            raise exc

    return url.strip()


def render_template(template, logger=None, **kwargs):
    """
    Render Jinja2 template. Logs errors, and raises an exception when it's not possible
    to correctly render the template.

    :param template: Template to render. It can be either :py:class:`jinja2.environment.Template` instance,
        or a string.
    :param dict kwargs: Keyword arguments passed to render process.
    :rtype: str
    :returns: Rendered template.
    :raises gluetool.glue.GlueError: when the rednering failed.
    """

    logger = logger or Logging.get_logger()

    try:
        def _render(template):
            log_blob(logger.debug, 'rendering template', template.source)
            log_dict(logger.verbose, 'context', kwargs)

            return str(template.render(**kwargs).strip())

        if isinstance(template, (str, unicode)):
            source, template = template, jinja2.Template(template)
            template.source = source

            return _render(template)

        if isinstance(template, jinja2.environment.Template):
            if template.filename != '<template>':
                with open(template.filename, 'r') as f:
                    template.source = f.read()

            else:
                template.source = '<unknown template source>'

            return _render(template)

        raise GlueError('Unhandled template type {}'.format(type(template)))

    except Exception as exc:
        raise GlueError('Cannot render template: {}'.format(exc))


# pylint: disable=invalid-name
def YAML():
    """
    Provides YAML read/write interface with common settings.

    :rtype: ruamel.yaml.YAML
    """

    yaml = ruamel.yaml.YAML()
    yaml.indent(sequence=4, mapping=4, offset=2)

    return yaml


def from_yaml(yaml_string):
    """
    Convert YAML in a string into Python data structures.

    Uses internal YAML parser to produce result. Paired with :py:func:`load_yaml` and their
    JSON siblings to provide unified access to JSON and YAML.
    """

    return YAML().load(yaml_string)


def load_yaml(filepath, logger=None):
    """
    Load data stored in YAML file, and return their Python representation.

    :param str filepath: Path to a file. ``~`` or ``~<username>`` are expanded before using.
    :param gluetool.log.ContextLogger logger: Logger used for logging.
    :rtype: object
    :returns: structures representing data in the file.
    :raises gluetool.glue.GlueError: if it was not possible to successfully load content of the file.
    """

    if not filepath:
        raise GlueError('File path is not valid: {}'.format(filepath))

    logger = logger or Logging.get_logger()

    real_filepath = normalize_path(filepath)

    logger.debug("attempt to load YAML from '{}' (maps to '{}')".format(filepath, real_filepath))

    if not os.path.exists(real_filepath):
        raise GlueError("File '{}' does not exist".format(filepath))

    try:
        with open(real_filepath, 'r') as f:
            data = YAML().load(f)

        logger.debug("loaded YAML data from '{}':\n{}".format(filepath, format_dict(data)))

        return data

    except ruamel.yaml.YAMLError as e:
        raise GlueError("Unable to load YAML file '{}': {}".format(filepath, str(e)))


def dump_yaml(data, filepath, logger=None):
    """
    Save data stored in variable to YAML file.

    :param object data: Data to store in YAML file
    :param str filepath: Path to an output file.
    :raises gluetool.glue.GlueError: if it was not possible to successfully save data to file.
    """
    if not filepath:
        raise GlueError("File path is not valid: '{}'".format(filepath))

    logger = logger or Logging.get_logger()

    real_filepath = normalize_path(filepath)
    dirpath = os.path.dirname(real_filepath)

    if not os.path.exists(dirpath):
        raise GlueError("Cannot save file in nonexistent directory '{}'".format(dirpath))

    try:
        with open(real_filepath, 'w') as f:
            YAML().dump(data, f)
            f.flush()

    except ruamel.yaml.YAMLError as e:
        raise GlueError("Unable to save YAML file '{}': {}".format(filepath, str(e)))


def _json_byteify(data, ignore_dicts=False):
    # if this is a unicode string, return its string representation
    if isinstance(data, unicode):
        return data.encode('utf-8')

    # if this is a list of values, return list of byteified values
    if isinstance(data, list):
        return [_json_byteify(item, ignore_dicts=True) for item in data]

    # if this is a dictionary, return dictionary of byteified keys and values
    # but only if we haven't already byteified it
    if isinstance(data, dict) and not ignore_dicts:
        return {
            _json_byteify(key, ignore_dicts=True): _json_byteify(value, ignore_dicts=True)
            for key, value in data.iteritems()
        }

    # if it's anything else, return it in its original form
    return data


def from_json(json_string):
    """
    Convert JSON in a string into Python data structures.

    Similar to :py:func:`json.loads` but uses special object hook to avoid unicode strings
    in the output..
    """

    return _json_byteify(json.loads(json_string, object_hook=_json_byteify), ignore_dicts=True)


def load_json(filepath, logger=None):
    """
    Load data stored in JSON file, and return their Python representation.

    :param str filepath: Path to a file. ``~`` or ``~<username>`` are expanded before using.
    :param gluetool.log.ContextLogger logger: Logger used for logging.
    :rtype: object
    :returns: structures representing data in the file.
    :raises gluetool.glue.GlueError: if it was not possible to successfully load content of the file.
    """

    if not filepath:
        raise GlueError('File path is not valid: {}'.format(filepath))

    logger = logger or Logging.get_logger()

    real_filepath = normalize_path(filepath)

    logger.debug("attempt to load JSON from '{}' (maps to '{}')".format(filepath, real_filepath))

    if not os.path.exists(real_filepath):
        raise GlueError("File '{}' does not exist".format(filepath))

    try:
        with open(real_filepath, 'r') as f:
            data = _json_byteify(json.load(f, object_hook=_json_byteify), ignore_dicts=True)
            logger.debug("loaded JSON data from '{}':\n{}".format(filepath, format_dict(data)))

            return data

    except Exception as exc:
        raise GlueError("Unable to load JSON file '{}': {}".format(filepath, str(exc)))


def _load_yaml_variables(data, enabled=True, logger=None):
    """
    Load all variables from files referenced by a YAML, and return function to render a string
    as a template using these variables. The files containing variables are mentioned in comments,
    in a form ``# !include <filepath>`` form.

    :param data: data loaded from a YAML file.
    :param bool enabled: when set to ``False``, variables are not loaded and a simple no-op
        function is returned.
    :param gluetool.log.ContextLogger logger: Logger used for logging.
    :returns: Function accepting a string and returning a rendered template.
    """

    logger = logger or Logging.get_logger()

    def _render_template_nop(s):
        return s

    if not enabled:
        return _render_template_nop

    # Our YAML reader preserves comments, they are accessible via `ca` attribute of the
    # YAML data structure (which behaves like a dict or list, but it has additional
    # powers).
    if not hasattr(data, 'ca') or not hasattr(data.ca, 'comment') or len(data.ca.comment) <= 1:
        logger.debug('when looking for !import directives, no comments found in YAML data')

        return _render_template_nop

    # Ok, so this YAML data contains comments. Check their values to find `!include` directives.
    # Load referenced files and merged them into a single context.
    context = {}

    for comment in data.ca.comment[1]:
        value = comment.value.strip()

        if not value.startswith('# !include'):
            continue

        try:
            variables_map_path = shlex.split(value[2:])[1]

        except Exception as exc:
            raise GlueError("Cannot extract filename to include from '{}': {}".format(value, exc))

        logger.debug("loading variables from '{}'".format(variables_map_path))

        context.update(load_yaml(variables_map_path, logger=logger))

    def _render_template(s):
        if isinstance(s, str):
            return render_template(s, logger=logger, **context)

        if isinstance(s, list):
            return [
                render_template(t, logger=logger, **context)
                for t in s
            ]

        raise GlueError("Don't know how to render object of type {}".format(type(s)))

    return _render_template


class SimplePatternMap(object):
    # pylint: disable=too-few-public-methods

    """
    `Pattern map` is a list of ``<pattern>``: ``<result>`` pairs. ``Pattern`` is a
    regular expression used to match a string, ``result`` is what the matching
    string maps to.

    Basically an ordered dictionary with regexp matching of keys, backed by an YAML file.

    :param str filepath: Path to a YAML file with map definition.
    :param gluetool.log.ContextLogger logger: Logger used for logging.
    :param bool allow_variables: if set, both patterns and converters are first treated as templates,
        and as such are rendered before doing anything else. Map may contain special comments,
        ``# !include <path>``, where path refers to a YAML file providing the necessary variables.
    """

    def __init__(self, filepath, logger=None, allow_variables=False):
        self.logger = logger or Logging.get_logger()
        logger.connect(self)

        pattern_map = load_yaml(filepath, logger=self.logger)

        if pattern_map is None:
            raise GlueError("pattern map '{}' does not contain any patterns".format(filepath))

        _render_template = _load_yaml_variables(pattern_map, enabled=allow_variables, logger=self.logger)

        self._compiled_map = []

        for pattern_dict in pattern_map:
            if not isinstance(pattern_dict, dict):
                raise GlueError("Invalid format: '- <pattern>: <result>' expected, '{}' found".format(pattern_dict))

            pattern = pattern_dict.keys()[0]
            result = pattern_dict[pattern].strip()

            # Apply variables if requested.
            pattern = _render_template(pattern)
            result = _render_template(result)

            log_dict(logger.debug, "rendered mapping '{}'".format(pattern), result)

            try:
                pattern = re.compile(pattern)

            except re.error as exc:
                raise GlueError("Pattern '{}' is not valid: {}".format(pattern, str(exc)))

            self._compiled_map.append((pattern, result))

    def match(self, s):
        """
        Try to match ``s`` by the map. If the match is found - the first one wins - then its
        transformation is applied to the ``s``.

        :rtype: str
        :returns: if matched, output of the corresponding transformation.
        """

        self.debug("trying to match string '{}' with patterns in the map".format(s))

        for pattern, result in self._compiled_map:
            self.debug("testing pattern '{}'".format(pattern.pattern))

            match = pattern.match(s)
            if match is None:
                continue

            self.debug('  matched!')
            return result

        raise GlueError("Could not match string '{}' with any pattern".format(s))


class PatternMap(object):
    # pylint: disable=too-few-public-methods

    """
    `Pattern map` is a list of ``<pattern>``: ``<converter>`` pairs. ``Pattern`` is a
    regular expression used to match a string, ``converter`` is a function that transforms
    a string into another one, accepting the pattern and the string as arguments.

    It is defined in a YAML file:

    .. code-block:: yaml

       ---
       - 'foo-(\\d+)': 'bar-\\1'
       - 'baz-(\\d+)': 'baz, find_the_most_recent, append_dot'
       - 'bar-(\\d+)':
         - 'bar, find_the_most_recent, append_dot'
         - 'bar, find_the_oldest, append_dot'

    Patterns are the keys in each pair, while ``converter`` is a string (or list of strings),
    consisting of multiple items, separated by comma. The first item is **always** a string,
    let's call it ``R``. ``R``, given input string ``S1`` and the pattern, is used to transform
    ``S1`` to a new string, ``S2``, by calling ``pattern.sub(R, S1)``. ``R`` can make use of anything
    :py:meth:`re.sub` supports, including capturing groups.

    If there are other items in the ``converter`` string, they are names of `spices`, additional
    functions that will be called with ``pattern`` and the output of the previous spicing function,
    starting with ``S2`` in the case of the first `spice`.

    To allow spicing, user of ``PatternMap`` class must provide `spice makers` - mapping between
    `spice` names and functions that generate spicing functions. E.g.:

    .. code-block:: python

       def create_spice_append_dot(previous_spice):
           def _spice(pattern, s):
               s = previous_spice(pattern, s)
               return s + '.'
           return _spice

    ``create_spice_append_dot`` is a `spice maker`, used during creation of a pattern map after
    its definition is read, ``_spice`` is the actual spicing function used during the transformation
    process.

    There can be multiple converters for a single pattern, resulting in multiple values returned
    when the input string matches the corresponding pattern.

    :param str filepath: Path to a YAML file with map definition.
    :param dict spices: apping between `spices` and their `makers`.
    :param gluetool.log.ContextLogger logger: Logger used for logging.
    :param bool allow_variables: if set, both patterns and converters are first treated as templates,
        and as such are rendered before doing anything else. Map may contain special comments,
        ``# !include <path>``, where path refers to a YAML file providing the necessary variables.
    """

    def __init__(self, filepath, spices=None, logger=None, allow_variables=False):
        self.logger = logger or Logging.get_logger()
        logger.connect(self)

        spices = spices or {}

        pattern_map = load_yaml(filepath, logger=self.logger)

        if pattern_map is None:
            raise GlueError("pattern map '{}' does not contain any patterns".format(filepath))

        _render_template = _load_yaml_variables(pattern_map, enabled=allow_variables, logger=self.logger)

        def _create_simple_repl(repl):
            def _replace(pattern, target):
                """
                Use `repl` to construct image from `target`, honoring all backreferences made by `pattern`.
                """

                self.debug("pattern '{}', repl '{}', target '{}'".format(pattern.pattern, repl, target))

                try:
                    return pattern.sub(repl, target)

                except re.error as e:
                    raise GlueError("Cannot transform pattern '{}' with target '{}', repl '{}': {}".format(
                        pattern.pattern, target, repl, str(e)))

            return _replace

        self._compiled_map = []

        for pattern_dict in pattern_map:
            log_dict(logger.debug, 'pattern dict', pattern_dict)

            if not isinstance(pattern_dict, dict):
                raise GlueError("Invalid format: '- <pattern>: <transform>' expected, '{}' found".format(pattern_dict))

            # There is always just a single key, the pattern.
            pattern_key = pattern_dict.keys()[0]

            # Apply variables if requested.
            pattern = _render_template(pattern_key)
            converter_chains = _render_template(pattern_dict[pattern_key])

            log_dict(logger.debug, "rendered mapping '{}'".format(pattern), converter_chains)

            if isinstance(converter_chains, str):
                converter_chains = [converter_chains]

            try:
                pattern = re.compile(pattern)

            except re.error as e:
                raise GlueError("Pattern '{}' is not valid: {}".format(pattern, str(e)))

            compiled_chains = []

            for chain in converter_chains:
                converters = [s.strip() for s in chain.split(',')]

                # first item in `converters` is always a simple string used by `pattern.sub()` call
                converter = _create_simple_repl(converters.pop(0))

                # if there any any items left, they name "spices" to apply, one by one,
                # on the result of the first operation
                for spice in converters:
                    if spice not in spices:
                        raise GlueError("Unknown 'spice' function '{}'".format(spice))

                    converter = spices[spice](converter)

                compiled_chains.append(converter)

            self._compiled_map.append((pattern, compiled_chains))

    def match(self, s, multiple=False):
        """
        Try to match ``s`` by the map. If the match is found - the first one wins - then its
        conversions are applied to the ``s``.

        There can be multiple conversions for a pattern, by default only the product of
        the first one is returned. If ``multiple`` is set to ``True``, list of all products
        is returned instead.

        :rtype: str
        :returns: if matched, output of the corresponding transformation.
        """

        self.debug("trying to match string '{}' with patterns in the map".format(s))

        for pattern, converters in self._compiled_map:
            self.debug("testing pattern '{}'".format(pattern.pattern))

            match = pattern.match(s)
            if match is None:
                continue

            self.debug('  matched!')

            if multiple is not True:
                return converters[0](pattern, s)

            return [
                converter(pattern, s) for converter in converters
            ]

        raise GlueError("Could not match string '{}' with any pattern".format(s))


def wait(label, check, timeout=None, tick=30, logger=None):
    """
    Wait for a condition to be true.

    :param str label: printable label used for logging.
    :param callable check: called to test the condition. If its return value evaluates as ``True``,
        the condition is assumed to pass the test and waiting ends.
    :param int timeout: fail after this many seconds. ``None`` means test forever.
    :param int tick: test condition every ``tick`` seconds.
    :param gluetool.log.ContextAdapter logger: parent logger whose methods will be used for logging.
    :raises gluetool.glue.GlueError: when ``timeout`` elapses while condition did not pass the check.
    """

    if not isinstance(tick, int):
        raise GlueError('Tick must be an integer')

    if tick < 0:
        raise GlueError('Tick must be a positive integer')

    logger = logger or Logging.get_logger()

    if timeout is not None:
        end_time = time.time() + timeout

    def _timeout():
        return '{} seconds'.format(int(end_time - time.time())) if timeout is not None else 'infinite'

    logger.debug("waiting for condition '{}', timeout {}, check every {} seconds".format(label, _timeout(),
                                                                                         tick))

    while timeout is None or time.time() < end_time:
        logger.debug("calling callback function")
        ret = check()
        if ret:
            logger.debug('check passed, assuming success')
            return ret

        logger.debug("check failed with {}, assuming failure".format(ret))

        logger.debug('{} left, sleeping for {} seconds'.format(_timeout(), tick))
        time.sleep(tick)

    raise GlueError("Condition '{}' failed to pass within given time".format(label))


def new_xml_element(tag_name, _parent=None, **attrs):
    """
    Create new XML element.

    :param str tag_name: Name of the element.
    :param element _parent: If set, the newly created element will be appended to this element.
    :param dict attrs: Attributes to set on the newly created element.
    :returns: Newly created XML element.
    """

    element = bs4.BeautifulSoup('', 'xml').new_tag(tag_name)

    for name, value in attrs.iteritems():
        element[name] = value

    if _parent is not None:
        _parent.append(element)

    return element
