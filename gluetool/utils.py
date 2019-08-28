# pylint: disable=too-many-lines

"""
Various helpers.
"""

import collections
import contextlib
import errno
import functools
import io
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import warnings

import bs4
import urlnormalizer
import jinja2
import requests as original_requests

# Python 2/3 compatibility
import six
from six import PY2, ensure_str, iteritems, iterkeys
from six.moves import http_client, urllib

# Don't know why pylint reports "Relative import 'ruamel.yaml', should be 'gluetool.ruamel.yaml'" :(
# pylint: disable=relative-import
import ruamel.yaml

from .glue import GlueError, SoftGlueError, GlueCommandError
from .result import Result
from .log import Logging, ContextAdapter, PackageAdapter, LoggerMixin, BlobLogger, \
    log_blob, log_dict, print_wrapper

# Type annotations
# pylint: disable=unused-import, wrong-import-order
from typing import TYPE_CHECKING, cast  # noqa
from typing import Any, Callable, Deque, Dict, List, Optional, Pattern, Tuple, TypeVar, Union  # noqa
from .log import LoggingFunctionType  # noqa

if TYPE_CHECKING:
    import logging  # noqa


# Type variable used in generic types
T = TypeVar('T')


if PY2:
    DEVNULL = io.open(os.devnull, 'wb')

else:
    # In runtime, it is guarder by `PY2`, but Python 2 Pylint still checks it, and there's no `DEVNULL`
    # in Python 2... Hence disabling `no-name-in-module`.
    from subprocess import DEVNULL  # pylint: disable=ungrouped-imports,no-name-in-module


# Patch urlnormalizer to support file:// scheme.
if 'file' not in urlnormalizer.normalizer.SCHEMES:
    urlnormalizer.normalizer.SCHEMES = urlnormalizer.normalizer.SCHEMES + ('file',)


def deprecated(func):
    # type: (Callable[..., Any]) -> Callable[..., Any]

    """
    This is a decorator which can be used to mark functions as deprecated. It will result in a warning being emitted
    when the function is used.
    """

    @functools.wraps(func)
    def new_func(*args, **kwargs):
        # type: (*Any, **Any) -> Any

        warnings.simplefilter('always', DeprecationWarning)  # turn off filter
        warnings.warn('Function {} is deprecated.'.format(func.__name__), category=DeprecationWarning,
                      stacklevel=2)
        warnings.simplefilter('default', DeprecationWarning)  # reset filter

        return func(*args, **kwargs)

    return new_func


def dict_update(dst, *args):
    # type: (Dict[Any, Any], *Dict[Any, Any]) -> Dict[Any, Any]

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
    # type: (Union[str, bool]) -> bool

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
    # type: (Union[str, List[str]], Optional[str]) -> List[str]

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
    values = [option_value] if isinstance(option_value, six.string_types) else option_value

    # Now deal with possibly multiple paths, separated by comma and some white space, inside
    # every item of the list. Split the paths in the item by the given separator, strip the
    # white space, and concatenate these lists (one for each item in the main `values` list)
    # using sum - with an empty list as a start, it works for lists just as nicely.
    return sum([
        [value.strip() for value in item.split(separator)] for item in values
    ], [])


def normalize_shell_option(option_value):
    # type: (Union[str, List[str]]) -> List[str]

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
    values = [option_value] if isinstance(option_value, six.string_types) else option_value

    # Now split each item using shlex, and merge these lists into a single one.
    return sum([
        [ensure_str(s) for s in shlex.split(value)]
        for value in values
    ], [])


def normalize_path(path):
    # type: (str) -> str

    """
    Apply common treatments on a given path:

        * replace home directory reference (``~`` and similar), and
        * convert ``path`` to a normalized absolutized version of the pathname.
    """

    return os.path.abspath(os.path.expanduser(path))


def normalize_path_option(option_value, separator=','):
    # type: (Union[str, List[str]], Optional[str]) -> List[str]

    """
    Reduce many ways how list of paths is specified by user, to a simple list of paths. See
    :py:func:`normalize_multistring_option` for more details.
    """

    return [normalize_path(path) for path in normalize_multistring_option(option_value, separator=separator)]


class IncompatibleOptionsError(SoftGlueError):
    pass


class Bunch(object):
    # pylint: disable=too-few-public-methods

    @deprecated
    def __init__(self, **kwargs):
        # type: (**Any) -> None

        self.__dict__.update(kwargs)


class ThreadAdapter(ContextAdapter):
    """
    Custom logger adapter, adding thread name as a context.

    :param gluetool.log.ContextAdapter logger: parent logger whose methods will be used for logging.
    :param threading.Thread thread: thread whose name will be added.
    """

    def __init__(self, logger, thread):
        # type: (Union[logging.Logger, ContextAdapter], threading.Thread) -> None

        super(ThreadAdapter, self).__init__(logger, {'ctx_thread_name': (5, thread.name)})


class WorkerThread(LoggerMixin, threading.Thread):
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
        # type: (ContextAdapter, Callable[..., Any], Optional[Tuple[Any, ...]], Optional[Dict[str, Any]], **Any) -> None

        threading.Thread.__init__(self, **kwargs)
        LoggerMixin.__init__(self, ThreadAdapter(logger, self))

        self._fn = fn
        self._args = fn_args or ()
        self._kwargs = fn_kwargs or {}

        self.result = None  # type: Union[Exception, Any]

    def run(self):
        # type: () -> None

        self.debug('worker thread started')

        try:
            self.result = self._fn(*self._args, **self._kwargs)

        # pylint: disable=broad-except
        except Exception as e:
            self.error('exception raised in worker thread: {}'.format(e))
            self.result = e

        finally:
            self.debug('worker thread finished')


class StreamReader(object):
    def __init__(self, stream, name=None, block=16):
        # type: (Any, Optional[str], Optional[int]) -> None

        """
        Wrap blocking ``stream`` with a reading thread. The threads read from
        the (normal, blocking) `stream` and adds bits and pieces into the `queue`.
        ``StreamReader`` user then can check the `queue` for new data.
        """

        self._stream = stream
        self._name = name or stream.name

        # List would fine as well, however deque is better optimized for
        # FIFO operations, and it provides the same thread safety.
        self._queue = collections.deque()  # type: Deque[Union[None, str]]
        self._content = []  # type: List[str]

        def _enqueue():
            # type: () -> None

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
        # type: () -> str

        return self._name

    @property
    def content(self):
        # type: () -> str

        return ''.join(self._content)

    def wait(self):
        # type: () -> None

        self._thread.join()

    def read(self):
        # type: () -> Optional[str]

        try:
            return cast(str, self._queue.popleft())

        except IndexError:
            return None


class ProcessOutput(object):
    """
    Result of external process.
    """

    # pylint: disable=too-many-arguments,too-few-public-methods
    def __init__(self, cmd, exit_code, stdout, stderr, kwargs):
        # type: (List[str], int, Optional[str], Optional[str], Dict[str, Any]) -> None

        self.cmd = cmd
        self.kwargs = kwargs

        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def log_stream(self, stream, logger):
        # type: (str, ContextAdapter) -> None

        content = getattr(self, stream)

        if content is None:
            if stream in self.kwargs:
                logger.debug('{}:\n  command produced no output'.format(stream))
            else:
                logger.debug('{}:\n  command forwarded the output to its parent'.format(stream))

        else:
            log_blob(logger.verbose, stream, content)

    def log(self, logger):
        # type: (ContextAdapter) -> None

        logger.debug('command exited with code {}'.format(self.exit_code))

        self.log_stream('stdout', logger)
        self.log_stream('stderr', logger)


class Command(LoggerMixin, object):
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
        # type: (List[str], Optional[List[str]], Optional[ContextAdapter]) -> None

        super(Command, self).__init__(logger or Logging.get_logger())

        self.executable = executable
        self.options = options or []  # type: List[str]

        self.use_shell = False
        self.quote_args = False

        self._command = None  # type: Optional[List[str]]
        self._popen_kwargs = None  # type: Optional[Dict[str, Any]]
        self._process = None  # type: Optional[subprocess.Popen]
        self._exit_code = None  # type: Optional[int]

        self._stdout = None  # type: Optional[str]
        self._stderr = None  # type: Optional[str]

    def _apply_quotes(self):
        # type: () -> List[str]

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
        # type: () -> None

        # Collapse optionals to specific types
        assert self._process is not None

        self._stdout, self._stderr = self._process.communicate()

    def _communicate_inspect(self, inspect_callback):
        # type: (Optional[Callable[[Any, Optional[str], bool], None]]) -> None

        # Collapse optionals to specific types
        assert self._command is not None
        assert self._process is not None

        # let's capture *both* streams - capturing just a single one leads to so many ifs
        # and elses and messy code
        p_stdout = StreamReader(self._process.stdout, name='<stdout>')
        p_stderr = StreamReader(self._process.stderr, name='<stderr>')

        if inspect_callback is None:
            def stdout_write(stream, data, flush):
                # type: (Any, Optional[str], bool) -> None

                # pylint: disable=unused-argument

                if data is None:
                    return

                # Not suitable for multiple simultaneous commands. Shuffled output will
                # ruin your day. And night. And few following weeks, full of debugging, as well.
                sys.stdout.write(ensure_str(data))
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
                    inspect_callback(stream, stream.read(), False)

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

                    inspect_callback(stream, data, False)

                inspect_callback(stream, None, True)

        self._stdout, self._stderr = p_stdout.content, p_stderr.content

    def _construct_output(self):
        # type: () -> ProcessOutput

        # Collapse optionals to specific types
        assert self.logger is not None
        assert self._command is not None
        assert self._exit_code is not None
        assert self._popen_kwargs is not None

        output = ProcessOutput(self._command, self._exit_code, self._stdout, self._stderr, self._popen_kwargs)

        output.log(self.logger)

        return output

    def run(self, inspect=False, inspect_callback=None, **kwargs):
        # type: (Optional[bool], Optional[Callable[..., None]], **Any) -> ProcessOutput

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
            # type: (List[str]) -> None

            if not isinstance(items, list):
                raise GlueError('Only list of strings is accepted')

            if not all((isinstance(s, six.string_types) for s in items)):
                raise GlueError('Only list of strings is accepted, {} found'.format([(s, type(s)) for s in items]))

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
            # type: (Any) -> str

            if stream == subprocess.PIPE:
                return 'PIPE'
            if stream == DEVNULL:
                return 'DEVNULL'
            if stream == subprocess.STDOUT:
                return 'STDOUT'
            return str(stream)

        printable_kwargs = kwargs.copy()  # type: Dict[str, Any]
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
                raise GlueError("Command '{}' not found".format(ensure_str(self._command[0])))

            raise e

        self._exit_code = self._process.poll()

        output = self._construct_output()

        if self._exit_code != 0:
            raise GlueCommandError(self._command, output)

        return output


@deprecated
def run_command(cmd, logger=None, inspect=False, inspect_callback=None, **kwargs):
    # type: (List[str], Optional[ContextAdapter], bool, Optional[Callable[..., None]], **Any) -> ProcessOutput

    # pylint: disable=unused-argument

    """
    Wrapper for ``Command(...).run().

    Provided for backward compatibility.

    .. deprecated:: 1.1

        Use :py:class:`gluetool.utils.Command` instead.
    """

    return Command(cmd, logger=logger).run(**kwargs)


def check_for_commands(cmds):
    # type: (List[str]) -> None

    """ Checks if all commands in list cmds are valid """

    for cmd in cmds:
        try:
            Command(['/bin/bash', '-c', 'command -v {}'.format(cmd)]).run(stdout=DEVNULL)

        except GlueError:
            raise GlueError("Command '{}' not found on the system".format(ensure_str(cmd)))


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
        # type: (Callable[..., Any]) -> None

        self._method = method
        self.__doc__ = getattr(method, '__doc__')

    def __get__(self, obj, cls):
        # type: (Any, Any) -> Any

        # does not support class attribute access, only instance
        assert obj is not None

        # get the real value of this property
        value = self._method(obj)

        # replace cached_property instance with the value
        obj.__dict__[self._method.__name__] = value

        return value


def format_command_line(cmdline):
    # type: (List[List[str]]) -> str

    """
    Return formatted command-line.

    All but the first line are indented by 4 spaces.

    :param list cmdline: list of iterables, representing command-line split to multiple lines.
    """

    def _format_options(options):
        # type: (List[str]) -> str

        # To make code more readable, it's split to multiple lines. First, make sure each option
        # is "str", accepted by `shlex_quote` function.
        encoded_options = [ensure_str(opt) for opt in options]

        # Next, quote each option.
        # shlex_quote takes one argument, pylint thinks otherwise :/
        # pylint: disable=too-many-function-args
        quoted_options = [six.moves.shlex_quote(opt) for opt in encoded_options]

        # Finally, convert quoted options back to "text".
        decoded_options = [ensure_str(opt) for opt in quoted_options]

        return ' '.join(decoded_options)

    cmd = [_format_options(cmdline[0])]

    for row in cmdline[1:]:
        cmd.append('    ' + _format_options(row))

    return '\n'.join(cmd)


@deprecated
def fetch_url(url, logger=None, success_codes=(200,)):
    # type: (str, Optional[ContextAdapter], Tuple[int, ...]) -> Tuple[Any, str]

    """
    "Get me content of this URL" helper.

    Very thin wrapper around urllib. Added value is logging, and converting
    possible errors to :py:class:`gluetool.glue.GlueError` exception.

    :param url: URL to get.
    :param gluetool.log.ContextLogger logger: Logger used for logging.
    :param tuple success_codes: tuple of HTTP response codes representing successfull request.
    :returns: tuple ``(response, content)`` where ``response`` is what
      :py:func:`requests.get` returns, and ``content`` is the payload
      of the response.
    """

    logger = logger or Logging.get_logger()

    logger.debug("opening URL '{}'".format(url))

    try:
        with requests(logger=logger) as req:
            response = req.get(url)

    except urllib.error.HTTPError as exc:
        raise GlueError("Failed to fetch URL '{}': {}".format(url, exc))

    if response.status_code not in success_codes:
        raise GlueError("Unsuccessfull response from '{}'".format(url))

    return response, response.content


@contextlib.contextmanager
def requests(logger=None):
    # type: (Optional[ContextAdapter]) -> Any

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

    # Enable http_client debugging. It's being used underneath ``requests`` and ``urllib3``,
    # but it's stupid - uses "print" instead of a logger, therefore we have to capture it
    # and disable debug logging when leaving the context.
    logger = logger or Logging.get_logger()

    http_client_logger = PackageAdapter(logger, 'httplib') if PY2 else PackageAdapter(logger, 'http_client')
    http_client.HTTPConnection.debuglevel = 1  # type: ignore

    # Start capturing ``print`` statements - they are used to provide debug messages, therefore
    # using ``debug`` level.
    with print_wrapper(log_fn=http_client_logger.debug):  # type: ignore  # logger.debug signature is compatible
        # To log responses and their content, we must take a look at ``Response`` instance
        # returned by several entry methods (``get``, ``post``, ...). To do that, we have
        # a simple wrapper function.

        # ``original_method`` is the actual ``requests.foo`` (``get``, ``post``, ...), wrapper
        # calls it to do the job, and logs response when it's done.
        def _verbose_request(original_method, *args, **kwargs):
            # type: (Callable[..., Any], *Any, **Any) -> Any

            ret = original_method(*args, **kwargs)

            assert logger is not None
            log_blob(logger.debug,
                     'response content',
                     ret.content)

            return ret

        # gather the original methods...
        methods = {
            method_name: getattr(original_requests, method_name)
            for method_name in ('head', 'get', 'post', 'put', 'patch', 'delete')
        }

        # ... and replace them with our wrapper, giving it the original method as the first argument
        for method_name, original_method in iteritems(methods):
            setattr(original_requests, method_name, functools.partial(_verbose_request, original_method))

        try:
            yield original_requests

        finally:
            # put original methods back...
            for method_name, original_method in iteritems(methods):
                setattr(original_requests, method_name, original_method)

            # ... and disable http_client debugging
            http_client.HTTPConnection.debuglevel = 0  # type: ignore


def treat_url(url, logger=None):
    # type: (str, Optional[ContextAdapter]) -> str

    """
    Remove "weird" artifacts from the given URL. Collapse adjacent '.'s, apply '..', etc.

    :param text url: URL to clear.
    :param gluetool.log.ContextAdapter logger: logger to use for logging.
    :rtype: text
    :raises: gluetool.glue.GlueError: if URL is invalid
    :returns: Treated URL.
    """

    logger = logger or Logging.get_logger()

    logger.debug("treating a URL '{}'".format(url))

    norm_url = urlnormalizer.normalize_url(url)

    if norm_url is None:
        raise GlueError("'{}' does not look like an URL".format(url))

    return ensure_str(norm_url.strip())


def render_template(template, logger=None, **kwargs):
    # type: (Union[str, jinja2.environment.Template], Optional[ContextAdapter], **Any) -> str

    """
    Render Jinja2 template. Logs errors, and raises an exception when it's not possible
    to correctly render the template.

    :param template: Template to render. It can be either :py:class:`jinja2.environment.Template` instance,
        or a string.
    :param dict kwargs: Keyword arguments passed to render process.
    :returns: Rendered template.
    :raises gluetool.glue.GlueError: when the rednering failed.
    """

    logger = logger or Logging.get_logger()

    assert logger is not None

    try:
        def _render(template, source):
            # type: (jinja2.Template, str) -> str

            assert logger is not None

            log_blob(logger.debug, 'rendering template', source)
            log_dict(logger.verbose, 'context', kwargs)

            return ensure_str(template.render(**kwargs).strip())

        if isinstance(template, six.string_types):
            return _render(jinja2.Template(template), template)

        if isinstance(template, jinja2.environment.Template):
            if template.filename != '<template>':  # type: ignore
                with io.open(template.filename, 'r', encoding='utf-8') as f:  # type: ignore  # .filename attr exists
                    return _render(template, f.read())

            return _render(template, '<unknown template source>')

        raise GlueError('Unhandled template type {}'.format(type(template)))

    except Exception as exc:
        raise GlueError('Cannot render template: {}'.format(exc))


# pylint: disable=invalid-name
def YAML():
    # type: () -> ruamel.yaml.YAML

    """
    Provides YAML read/write interface with common settings.

    :rtype: ruamel.yaml.YAML
    """

    yaml = ruamel.yaml.YAML()
    yaml.indent(sequence=4, mapping=4, offset=2)

    return yaml


def from_yaml(yaml_string):
    # type: (str) -> Any

    """
    Convert YAML in a string into Python data structures.

    Uses internal YAML parser to produce result. Paired with :py:func:`load_yaml` and their
    JSON siblings to provide unified access to JSON and YAML.
    """

    return YAML().load(yaml_string)


def load_yaml(filepath, logger=None):
    # type: (str, Optional[ContextAdapter]) -> Any

    """
    Load data stored in YAML file, and return their Python representation.

    :param text filepath: Path to a file. ``~`` or ``~<username>`` are expanded before using.
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

        log_dict(logger.debug, "loaded YAML data from '{}'".format(filepath), data)

        return data

    except ruamel.yaml.YAMLError as e:
        raise GlueError("Unable to load YAML file '{}': {}".format(filepath, e))


def dump_yaml(data, filepath, logger=None):
    # type: (Any, str, Optional[ContextAdapter]) -> None

    """
    Save data stored in variable to YAML file.

    :param object data: Data to store in YAML file
    :param text filepath: Path to an output file.
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
        raise GlueError("Unable to save YAML file '{}': {}".format(filepath, e))


def _json_byteify(data, ignore_dicts=False):
    # type: (Any, Optional[bool]) -> Any

    # if this is a unicode string, return it
    if isinstance(data, six.string_types):
        return data

    # if this is a list of values, return list of byteified values
    if isinstance(data, list):
        return [_json_byteify(item, ignore_dicts=True) for item in data]

    # if this is a dictionary, return dictionary of byteified keys and values
    # but only if we haven't already byteified it
    if isinstance(data, dict) and not ignore_dicts:
        return {
            _json_byteify(key, ignore_dicts=True): _json_byteify(value, ignore_dicts=True)
            for key, value in iteritems(data)
        }

    # if it's anything else, return it in its original form
    return data


def from_json(json_string):
    # type: (str) -> Any

    """
    Convert JSON in a string into Python data structures.

    Similar to :py:func:`json.loads` but uses special object hook to avoid unicode strings
    in the output..
    """

    return _json_byteify(json.loads(json_string, object_hook=_json_byteify), ignore_dicts=True)


def load_json(filepath, logger=None):
    # type: (str, Optional[ContextAdapter]) -> Any

    """
    Load data stored in JSON file, and return their Python representation.

    :param text filepath: Path to a file. ``~`` or ``~<username>`` are expanded before using.
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
            log_dict(logger.debug, "loaded JSON data from '{}'".format(filepath), data)

            return data

    except Exception as exc:
        raise GlueError("Unable to load JSON file '{}': {}".format(filepath, exc))


def _load_yaml_variables(data, enabled=True, logger=None):
    # type: (Any, bool, Optional[ContextAdapter]) -> Callable[[str], Union[str, List[str]]]
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
        # type: (str) -> str

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
    context = {}  # type: Dict[str, Any]

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
        # type: (Union[str, List[str]]) -> Union[str, List[str]]

        if isinstance(s, six.string_types):
            return render_template(s, logger=logger, **context)

        if isinstance(s, list):
            return [
                render_template(t, logger=logger, **context)
                for t in s
            ]

        raise GlueError("Don't know how to render object of type {}".format(type(s)))

    return _render_template


class SimplePatternMap(LoggerMixin, object):
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
        # type: (str, Optional[ContextAdapter], bool) -> None

        super(SimplePatternMap, self).__init__(logger or Logging.get_logger())

        pattern_map = load_yaml(filepath, logger=self.logger)

        if pattern_map is None:
            raise GlueError("pattern map '{}' does not contain any patterns".format(filepath))

        _render_template = _load_yaml_variables(pattern_map, enabled=allow_variables, logger=self.logger)

        self._compiled_map = []  # type: List[Tuple[Pattern[str], str]]

        for pattern_dict in pattern_map:
            if not isinstance(pattern_dict, dict):
                raise GlueError("Invalid format: '- <pattern>: <result>' expected, '{}' found".format(pattern_dict))

            pattern = next(iterkeys(pattern_dict))
            result = pattern_dict[pattern].strip()

            # Apply variables if requested.
            pattern = _render_template(pattern)
            result = _render_template(result)

            log_dict(logger.debug,  # type: ignore  # logger.debug signature is compatible
                     "rendered mapping '{}'".format(pattern),
                     result)

            try:
                pattern = re.compile(pattern)

            except re.error as exc:
                raise GlueError("Pattern '{}' is not valid: {}".format(pattern, exc))

            self._compiled_map.append((pattern, result))

    def match(self, s):
        # type: (str) -> str

        """
        Try to match ``s`` by the map. If the match is found - the first one wins - then its
        transformation is applied to the ``s``.

        :rtype: text
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


class PatternMap(LoggerMixin, object):
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

    :param text filepath: Path to a YAML file with map definition.
    :param dict spices: apping between `spices` and their `makers`.
    :param gluetool.log.ContextLogger logger: Logger used for logging.
    :param bool allow_variables: if set, both patterns and converters are first treated as templates,
        and as such are rendered before doing anything else. Map may contain special comments,
        ``# !include <path>``, where path refers to a YAML file providing the necessary variables.
    """

    def __init__(self,
                 filepath,  # type: str
                 spices=None,  # type: Optional[Dict[str, Callable[..., Callable[[Any, str], str]]]]
                 logger=None,  # type: Optional[ContextAdapter]
                 allow_variables=False  # type: bool
                ):  # noqa
        # type: (...) -> None

        super(PatternMap, self).__init__(logger or Logging.get_logger())

        spices = spices or {}

        pattern_map = load_yaml(filepath, logger=self.logger)

        if pattern_map is None:
            raise GlueError("pattern map '{}' does not contain any patterns".format(filepath))

        _render_template = _load_yaml_variables(pattern_map, enabled=allow_variables, logger=self.logger)

        def _create_simple_repl(repl):
            # type: (str) -> Callable[[Pattern[str], str], str]

            def _replace(pattern, target):
                # type: (Pattern[str], str) -> Any

                """
                Use `repl` to construct image from `target`, honoring all backreferences made by `pattern`.
                """

                self.debug("pattern '{}', repl '{}', target '{}'".format(pattern.pattern, repl, target))

                try:
                    return pattern.sub(repl, target)

                except re.error as e:
                    raise GlueError("Cannot transform pattern '{}' with target '{}', repl '{}': {}".format(
                        pattern.pattern, target, repl, e))

            return _replace

        self._compiled_map = []  # type: List[Tuple[Pattern[str], List[Callable[[Pattern[str], str], str]]]]

        for pattern_dict in pattern_map:
            log_dict(self.debug, 'pattern dict', pattern_dict)

            if not isinstance(pattern_dict, dict):
                raise GlueError("Invalid format: '- <pattern>: <transform>' expected, '{}' found".format(pattern_dict))

            # There is always just a single key, the pattern.
            pattern_key = next(iterkeys(pattern_dict))

            # Apply variables if requested.
            pattern = _render_template(pattern_key)
            converter_chains = _render_template(pattern_dict[pattern_key])

            # Given how YAML works, `pattern` is a string, but the type of `_render_template` return value
            # is Union[str, List[str]] - this covers possible lists on the right side of the equation.
            # To make mypy happy, let's collapse type of `pattern`.
            assert isinstance(pattern, six.string_types)

            log_dict(logger.debug,  # type: ignore  # logger.debug signature is compatible
                     "rendered mapping '{}'".format(pattern),
                     converter_chains)

            if isinstance(converter_chains, six.string_types):
                converter_chains = [converter_chains]

            try:
                compiled_pattern = re.compile(pattern)

            except re.error as e:
                raise GlueError("Pattern '{}' is not valid: {}".format(pattern, e))

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

            self._compiled_map.append((compiled_pattern, compiled_chains))

    def match(self, s, multiple=False):
        # type: (str, bool) -> Union[str, List[str]]

        """
        Try to match ``s`` by the map. If the match is found - the first one wins - then its
        conversions are applied to the ``s``.

        There can be multiple conversions for a pattern, by default only the product of
        the first one is returned. If ``multiple`` is set to ``True``, list of all products
        is returned instead.

        :rtype: text
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

        raise GlueError("Could not match string '{}' with any pattern".format(s), sentry_fingerprint=[s])


# The type of `wait` is a bit complicated: callback returns `Result` instance with either valid value A, or
# error B. `wait` us supposed to return `A` when finished successfully - it raises an timeout exception otherwise
# anyway, so there's no returning of B. So, given that `check` returns value of type `Result[T, E]`, we can
# deduce that `wait` must return value of type T. The trick is to use `T` in both `WaitCheckType` and
# `wait` signature.

#: Generic type for callbacks used by :py:func:`wait` function. Accepts no arguments, returns an instance
#: of :py:class:`gluetool.result.Result`.
WaitCheckType = Callable[[], Result[T, Any]]


def wait(label, check, timeout=None, tick=30, logger=None):
    # type: (str, WaitCheckType[T], Optional[int], int, Optional[ContextAdapter]) -> T
    """
    Wait for a condition to be true.

    :param text label: printable label used for logging.
    :param callable check: called to test the condition. It must be of type :py:data:`WaitCheckType`: takes
        no arguments, must return instance of :py:class:`gluetool.Result`. If the result is valid, the condition
        is assumed to pass the check and waiting ends.
    :param int timeout: fail after this many seconds. ``None`` means test forever.
    :param int tick: test condition every ``tick`` seconds.
    :param gluetool.log.ContextAdapter logger: parent logger whose methods will be used for logging.
    :raises gluetool.glue.GlueError: when ``timeout`` elapses while condition did not pass the check.
    :returns: if the condition became true, the value returned by the ``check`` function
        is returned. It is unpacked from the ``Result`` returned by ``check``.
    """

    if not isinstance(tick, int):
        raise GlueError('Tick must be an integer')

    if tick < 0:
        raise GlueError('Tick must be a positive integer')

    logger = logger or Logging.get_logger()

    if timeout is not None:
        end_time = time.time() + timeout

    def _timeout():
        # type: () -> str

        return '{} seconds'.format(int(end_time - time.time())) if timeout is not None else 'infinite'

    logger.debug("waiting for condition '{}', timeout {}, check every {} seconds".format(label, _timeout(),
                                                                                         tick))

    while timeout is None or time.time() < end_time:
        logger.debug("calling callback function")

        check_result = check()

        if check_result.is_ok:
            logger.debug('check passed, assuming success')

            return check_result.unwrap()

        logger.debug("check failed with '{}', assuming failure".format(check_result.value))

        logger.debug('{} left, sleeping for {} seconds'.format(_timeout(), tick))
        time.sleep(tick)

    raise GlueError("Condition '{}' failed to pass within given time".format(label))


def new_xml_element(tag_name, _parent=None, **attrs):
    # type: (str, Optional[Any], **str) -> Any

    """
    Create new XML element.

    :param text tag_name: Name of the element.
    :param element _parent: If set, the newly created element will be appended to this element.
    :param dict attrs: Attributes to set on the newly created element.
    :returns: Newly created XML element.
    """

    element = bs4.BeautifulSoup('', 'xml').new_tag(tag_name)

    for name, value in iteritems(attrs):
        element[name] = value

    if _parent is not None:
        _parent.append(element)

    return element
