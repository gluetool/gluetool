# pylint: disable=too-many-lines

import argparse
import ConfigParser
import imp
import inspect
import logging
import os
import sys
import ast

from functools import partial

import enum
import jinja2

from .color import Colors
from .help import LineWrapRawTextHelpFormatter, option_help, docstring_to_help, trim_docstring, eval_context_help
from .log import Logging, ContextAdapter, ModuleAdapter, log_dict


DEFAULT_MODULE_CONFIG_PATHS = [
    '/etc/gluetool.d/config',
    os.path.expanduser('~/.gluetool.d/config'),
    os.path.abspath('./.gluetool.d/config')
]

DEFAULT_DATA_PATH = '{}/data'.format(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_MODULE_PATHS = [
    '{}/gluetool_modules'.format(sys.prefix)
]


class DryRunLevels(enum.IntEnum):
    """
    Dry-run levels.

    :cvar int DEFAULT: Default level - everything is allowed.
    :cvar int DRY: Well-known "dry-run" - no changes to the outside world are allowed.
    :cvar int ISOLATED: No interaction with the outside world is allowed (networks connections, reading files, etc.)
    """

    DEFAULT = 0
    DRY = 1
    ISOLATED = 2


class GlueError(Exception):
    """
    Generic ``gluetool`` exception.

    :param str message: Exception message, describing what happened.
    :param tuple caused_by: If set, contains tuple as returned by :py:func:`sys.exc_info`, describing
        the exception that caused this one to be born. If not set, constructor will try to auto-detect
        this information, and if there's no such information, instance property ``caused_by`` will be
        set to ``None``.

    :ivar str message: Exception message, describing what happened.
    :ivar tuple caused_by: If set, contains tuple as returned by :py:func:`sys.exc_info`, describing
        the exception that caused this one to be born. ``None`` otherwise.
    """
    no_sentry_exceptions = []

    def __init__(self, message, caused_by=None, **kwargs):
        super(GlueError, self).__init__(message, **kwargs)

        # if not told explicitly, try to detect the cause
        if caused_by is None:
            caused_by = sys.exc_info()

        # if there's no cause, use None to signal that fact to the rest of the world
        if caused_by == (None, None, None):
            caused_by = None

        self.caused_by = caused_by

    @property
    def submit_to_sentry(self):
        """
        Decide whether the exception should be submitted to Sentry or not. By default,
        all exceptions are submitted. Exception listed in `no_sentry_exceptions` are not submitted.

        :rtype: bool
        :returns: ``True`` when the exception should be submitted to Sentry, ``False`` otherwise.
        """
        exception_name = '.'.join([type(self).__module__, type(self).__name__])
        if exception_name in self.no_sentry_exceptions:
            return False

        return True

    def sentry_fingerprint(self, current):
        # pylint: disable=no-self-use
        """
        Default grouping of events into issues might be too general for some cases.
        This method gives users a chance to provide custom fingerprint Sentry could
        use to group events in a more suitable way.

        E.g. user might be interested in some sort of connection issues but they would
        like to have them grouped not by a traceback (which is the default method) but
        per remote host IP. For that, the Sentry integration code will call ``sentry_fingerprint``
        method of a raised exception, and the method should return new fingerprint,
        let's say ``[<exception class name>, <remote IP>]``, and Sentry will group events
        using this fingerprint.

        :param list(str) current: current fingerprint. Usually ``['{{ default }}']`` telling
            Sentry to use its default method, but it could already be more specific.
        :rtype: list(str)
        :returns: new fingerprint, e.g. ``['FailedToConnectToAPI', '10.20.30.40']``
        """

        return current

    def sentry_tags(self, current):
        # pylint: disable=no-self-use
        """
        Add, modify or remove tags attached to a Sentry event, reported when the exception
        was raised.

        Most common usage would be an addition of tags, e.g. ``remote-host`` to allow search
        for events related to the same remote address.

        :param dict(str, str) current: current set of tags and their values.
        :rtype: dict(str, str)
        :returns: new set of tags. It is possible to add tags directly into ``current`` and
            then return it.
        """

        return current


class SoftGlueError(GlueError):
    """
    **Soft** errors are errors Glue Ops and/or developers shouldn't be bothered with, things that
    are up to the user to fix, e.g. empty set of tests. **Hard** errors are supposed to warn Ops/Devel
    teams about important infrastructure issues, code deficiencies, bugs and other issues that are
    fixable only by actions of Glue staff.

    However, we still must provide notification to user(s), and since we expect them to fix the issues
    that led to raising the soft error, we must provide them with as much information as possible.
    Therefore modules dealing with notifications are expected to give these exceptions a chance
    to influence the outgoing messages, e.g. by letting them provide an e-mail body template.
    """


class GlueRetryError(GlueError):
    """ Retry gluetool exception """


class GlueCommandError(GlueError):
    """
    Exception raised when external command failes.

    :param list cmd: Command as passed to gluetool.utils.run_command helper.
    :param gluetool.utils.ProcessOutput output: Process output data.

    :ivar list cmd: Command as passed to gluetool.utils.run_command helper.
    :ivar gluetool.utils.ProcessOutput output: Process output data.
    """

    def __init__(self, cmd, output, **kwargs):
        super(GlueCommandError, self).__init__("Command '{}' failed with exit code {}".format(cmd, output.exit_code),
                                               **kwargs)

        self.cmd = cmd
        self.output = output


class Failure(object):
    # pylint: disable=too-few-public-methods

    """
    Bundles exception related info. Used to inform modules in their ``destroy()`` phase
    that ``gluetool`` session was killed because of exception raised by one of modules.

    :param gluetool.glue.Module module: module in which the error happened, or ``None``.
    :param tuple exc_info: Exception information as returned by :py:func:`sys.exc_info`.

    :ivar gluetool.glue.Module module: module in which the error happened, or ``None``.
    :ivar Exception exception: Shortcut to ``exc_info[1]``, if available, or ``None``.
    :ivar tuple exc_info: Exception information as returned by :py:func:`sys.exc_info`.
    :ivar str sentry_event_id: If set, the failure was reported to the Sentry under this ID.
    """

    def __init__(self, module, exc_info):
        self.module = module
        self.exc_info = exc_info

        self.sentry_event_id = None
        self.sentry_event_url = None

        if exc_info:
            self.exception = exc_info[1]
            self.soft = isinstance(self.exception, SoftGlueError)

        else:
            self.exception = None
            self.soft = False


def retry(*args):
    """ Retry decorator
    This decorator catches given exceptions and returns
    libRetryError exception instead.

    usage: @retry(exception1, exception2, ..)
    """
    def wrap(func):
        def func_wrapper(obj, *fargs, **fkwargs):
            try:
                func(obj, *fargs, **fkwargs)
            except args as e:
                if isinstance(e, GlueError):
                    raise GlueRetryError(e.value)
                else:
                    raise GlueRetryError(e)
        return func_wrapper
    return wrap


class PipelineStep(object):
    # pylint: disable=too-few-public-methods
    """
    Step of ``gluetool``'s  pipeline - which is basically just a list of steps.

    :param str module: name to give to the module instance. This name is used e.g. in logging or when
        searching for module's config file.
    :param str actual_module: The actual module class the step uses. Usually it is same as ``module``
        but may differ, ``module`` is then a mere "alias". ``actual_module`` is used to locate
        a module class, whose instance is then given name ``module``.
    :param list(str) argv: list of options to be given to the module, in a form similar
        to :py:data:`sys.argv`.
    """

    def __init__(self, module, actual_module=None, argv=None):
        self.module = module
        self.actual_module = actual_module or module
        self.argv = argv or []

    def __repr__(self):
        return "PipelineStep('{}', actual_module='{}', argv={})".format(self.module, self.actual_module, self.argv)

    @property
    def module_designation(self):
        return self.module if self.module == self.actual_module else '{}:{}'.format(self.module, self.actual_module)


class ArgumentParser(argparse.ArgumentParser):
    """
    Pretty much the :py:class:`argparse.ArgumentParser`, it overrides just
    the :py:meth:`argparse.ArgumentParser.error` method, to catch errors and to wrap them
    into nice and common :py:class:`GlueError` instances.

    The original prints (for us) useless message, including the program name, and raises ``SystemExit``
    exception. Such action does not provide necessary information when encountered in Sentry, for example.
    """

    def error(self, message):
        """
        Must not return - raising an exception is a good way to "not return".

        :raises gluetool.glue.GlueError: When argument parser encounters an error.
        """

        raise GlueError('Parsing command-line options failed: {}'.format(message))


class Configurable(object):
    """
    Base class of two main ``gluetool`` classes - :py:class:`gluetool.glue.Glue` and :py:class:`gluetool.glue.Module`.
    Gives them the ability to use `options`, settable from configuration files and/or command-line arguments.

    :ivar dict _config: internal configuration store. Values of all options
      are stored here, regardless of them being set on command-line or by the
      configuration file.
    """

    options = {}
    """
    The ``options`` variable defines options accepted by module, and their properties::

        options = {
            <option name>: {
                <option properties>
            },
            ...
        }

    where

    * ``<option name>`` is used to `name` the option in the parser, and two formats are accepted (don't
      add any leading dashes (``-`` nor ``--``):

      * ``<long name>``
      * ``tuple(<short name>, <long name #1>, <long name #2>, ...)``

    * the first of long names (``long name #1``) is used to identify the option - other long names
      are understood by argument parser but their values are stored under ``long name #1`` option.

    * dictionary ``<option properties>`` is passed to :py:meth:`argparse.ArgumentParser.add_argument` as
      keyword arguments when the option is being added to the parser, therefore any arguments recognized
      by :py:mod:`argparse` can be used.

    It is also possible to use groups::

        options = [
            (<group name>,  <group options>),
            ...
        ]

    where

    * ``<group name>`` is the name of the group, e.g. ``Debugging options``

    * ``<group options>`` is the ``dict`` with all group options, as described above.

    This way, you can split pile of options into conceptualy closer groups of options. A single ``dict`` you would
    have is split into multiple smaller dictionaries, and each one is coupled with the group name in a ``tuple``.
    """

    required_options = []
    """Iterable of names of required options."""

    options_note = None
    """If set, it will be printed after all options as a help's epilog."""

    supported_dryrun_level = DryRunLevels.DEFAULT
    """Highest supported level of dry-run."""

    unique_name = None
    """
    Unque name of this instance. Used by modules, has no meaning elsewhere, but since dry-run
    checks are done on this level, it must be declared here to make pylint happy :/
    """

    @staticmethod
    def _for_each_option(callback, options):
        """
        Given dictionary defining options, call a callback for each of them.

        :param dict options: Dictionary of options, in a form ``option-name: option-params``.
        :param callable callback: Must accept at least 3 parameters: option name (``str``),
            all option names (short and long ones) (``tuple(str, str)``), and option params
            (``dict``).
        """

        # Sort options by their names - no code has a strong option on their order, so force
        # one to all users of this helper.
        option_names = sorted(options.keys(), key=lambda x: x[1] if isinstance(x, tuple) else x)

        for names in option_names:
            params = options[names]

            name = names[1] if isinstance(names, tuple) else names

            callback(name, names, params)

    @staticmethod
    def _for_each_option_group(callback, options):
        """
        Given set of options, call a callback for each option group.

        :param options: List of option groups, or a dict listing options directly.
        :param callable callback: Must accept at least 2 parameters: ``options`` (``dict``), listing options
            in the group, and keyword parameter ``group_name`` (``str``), which is set to group name when
            the ``options`` defines an option group.
        """

        if isinstance(options, dict):
            callback(options)

        elif isinstance(options, (list, tuple)):
            for group in options:
                if isinstance(group, dict):
                    callback(group)

                else:
                    group_name, group_options = group
                    callback(group_options, group_name=group_name)

    def __init__(self):
        super(Configurable, self).__init__()

        # Initialize configuration store
        self._config = {}

        # Initialize values in the store, and make sanity check of option names
        def _fail_name(name):
            raise GlueError("Option name must be either a string or (<letter>, <string>), '{}' found".format(name))

        def _verify_option(name, names, params):
            if isinstance(names, str):
                self._config[name] = None

            elif isinstance(names, tuple):
                if not isinstance(names[0], str) or len(names[0]) != 1:
                    _fail_name(name)

                if not isinstance(names[1], str) or len(names[1]) < 2:
                    _fail_name(name)

                self._config[name] = None

            else:
                _fail_name(name)

            if 'help' not in params:
                return

            # Long help texts can be written using triple quotes and docstring-like
            # formatting. Convert every help string to a single line string.
            params['help'] = option_help(params['help'])

        def _verify_options(options, **kwargs):
            # pylint: disable=unused-argument

            Configurable._for_each_option(_verify_option, options)

        Configurable._for_each_option_group(_verify_options, self.options)

    def _parse_config(self, paths):
        """
        Parse configuration files. Uses :py:mod:`ConfigParser` for the actual parsing.
        Updates module's configuration store with values found returned by the parser.

        :param list paths: List of paths to possible configuration files.
        """

        log_dict(self.debug, 'Loading configuration from following paths', paths)

        parser = ConfigParser.ConfigParser()
        parsed_paths = parser.read(paths)

        log_dict(self.debug, 'Read configuration files', parsed_paths)

        def _inject_value(name, names, params):
            # pylint: disable=unused-argument

            try:
                value = parser.get('default', name)

            except (ConfigParser.NoOptionError, ConfigParser.NoSectionError):
                return

            if 'type' in params:
                try:
                    value = params['type'](value)

                except ValueError as exc:
                    raise GlueError("Value of option '{}' expected to be '{}' but cannot be parsed: '{}'".format(
                        name, params['type'].__name__, exc.message))

            self._config[name] = value
            self.debug("Option '{}' set to '{}' by config file".format(name, value))

        def _inject_values(options, **kwargs):
            # pylint: disable=unused-argument

            Configurable._for_each_option(_inject_value, options)

        Configurable._for_each_option_group(_inject_values, self.options)

    @classmethod
    def _create_args_parser(cls, **kwargs):
        """
        Create an argument parser. Used by Sphinx to document "command-line" options
        of the module - which are, by the way, the module options as well.

        :param dict kwargs: Additional arguments passed to :py:class:`argparse.ArgumentParser`.
        """

        root_parser = ArgumentParser(**kwargs)

        def _add_option(parser, name, names, params):
            if params.get('raw', False) is True:
                final_names = (name,)
                del params['raw']

            else:
                if isinstance(names, str):
                    final_names = ('--{}'.format(name),)

                else:
                    final_names = ('-{}'.format(names[0]),) + tuple(['--{}'.format(n) for n in names[1:]])

            parser.add_argument(*final_names, **params)

        def _add_options(group_options, group_name=None):
            if group_name is None:
                group_parser = root_parser

            else:
                group_parser = root_parser.add_argument_group(group_name)

            Configurable._for_each_option(partial(_add_option, group_parser), group_options)

        Configurable._for_each_option_group(_add_options, cls.options)

        return root_parser

    def _parse_args(self, args, **kwargs):
        """
        Parse command-line arguments. Uses :py:mod:`argparse` for the actual parsing.
        Updates module's configuration store with values returned by parser.

        :param list args: arguments passed to this module. Similar to what :py:data:`sys.argv` provides on
          program level.
        """

        self.debug('Loading configuration from command-line arguments')

        # construct the parser
        parser = self._create_args_parser(**kwargs)

        # parse the added args
        args = parser.parse_args(args)

        # add the parsed args to options
        def _inject_value(name, names, params):
            # pylint: disable=unused-argument

            dest = params.get('dest', name.replace('-', '_'))

            value = getattr(args, dest)

            # if the option was not specified, skip it
            if value is None and name in self._config:
                return

            # do not replace config options with default command line values
            if name in self._config and self._config[name] is not None:
                # if default parameter used
                if 'default' in params and value == params['default']:
                    return

                # with action store_true, the default is False
                if params.get('action', '') == 'store_true' and value is False:
                    return

                # with action store_false, the default is True
                if params.get('action', '') == 'store_false' and value is True:
                    return

            self._config[name] = value
            self.debug("Option '{}' set to '{}' by command-line".format(name, value))

        def _inject_values(options, **kwargs):
            # pylint: disable=unused-argument

            Configurable._for_each_option(_inject_value, options)

        Configurable._for_each_option_group(_inject_values, self.options)

    def parse_config(self):
        """
        Public entry point to configuration parsing. Child classes must implement this
        method, e.g. by calling :py:meth:`gluetool.glue.Configurable._parse_config` which
        requires list of paths.
        """

        # E.g. self._parse_config(<list of possible configuration files>)

        raise NotImplementedError('Implement this method to enable the actual parsing')

    def parse_args(self, args):
        """
        Public entry point to argument parsing. Child classes must implement this method,
        e.g. by calling :py:meth:`gluetool.glue.Configurable._parse_args` which makes use
        of additional :py:class:`argparse.ArgumentParser` options.
        """

        # E.g. self._parse_args(args, description=...)

        raise NotImplementedError('Implement this method to enable the actual parsing')

    def check_required_options(self):
        if not self.required_options:
            self.debug('skipping checking of required options')
            return

        for name in self.required_options:
            if name not in self._config or not self._config[name]:
                raise GlueError("Missing required '{}' option".format(name))

    def option(self, *names):
        """
        Return values of given options from module's configuration store.

        :param str names: names of requested options.
        :returns: either a value or ``None`` if such option does not exist. When multiple options are requested,
            a tuple of their values is returned, for a single option its value is **not** wrapped by a tuple.
        """

        if not names:
            raise GlueError('Specify at least one option')

        values = tuple(
            self._config.get(name, None) for name in names
        )

        return values[0] if len(values) == 1 else values

    @property
    def dryrun_level(self):
        """
        Return current dry-run level. This must be implemented by class descendants
        because each one finds the necessary information in different places.
        """

        raise NotImplementedError()

    @property
    def dryrun_enabled(self):
        """
        ``True`` if dry-run level is enabled, on any level.
        """

        return self.dryrun_level != DryRunLevels.DEFAULT

    def _dryrun_allows(self, threshold, msg):
        """
        Check whether current dry-run level allows an action. If the current dry-run level
        is equal of higher than ``threshold``, then the action is not allowed.

        E.g. when action's ``threshold`` is :py:attr:`DryRunLevels.ISOLATED`, and the current
        level is :py:attr:`DryRunLevels.DRY`, the action is allowed.

        :param DryRunLevels threshold: Dry-run level the action is not allowed.
        :param str msg: Message logged (as a warning) when the action is deemed not allowed.
        :returns: ``True`` when action is allowed, ``False`` otherwise.
        """

        if self.dryrun_level >= threshold:
            self.warn('{} is not allowed by current dry-run level'.format(msg))
            return False

        return True

    def dryrun_allows(self, msg):
        """
        Checks whether current dry-run level allows an action which is disallowed on
        :py:attr:`DryRunLevels.DRY` level.

        See :py:meth:`Configurable._dryrun_allows` for detailed description.
        """

        return self._dryrun_allows(DryRunLevels.DRY, msg)

    def isolatedrun_allows(self, msg):
        """
        Checks whether current dry-run level allows an action which is disallowed on
        :py:attr:`DryRunLevels.ISOLATED` level.
        """

        return self._dryrun_allows(DryRunLevels.ISOLATED, msg)

    def check_dryrun(self):
        """
        Checks whether this object supports current dry-run level.
        """

        if not self.dryrun_enabled:
            return

        if self.dryrun_level > self.supported_dryrun_level:
            raise GlueError("Module '{}' does not support current dry-run level of '{}'".format(self.unique_name,
                                                                                                self.dryrun_level.name))

    @property
    def eval_context(self):
        """
        Return "evaluation context" - a dictionary of variable names (usually in uppercase)
        and their values, which is supposed to be used in various "evaluate *this*" operations
        like rendering of templates.

        To provide nice and readable documentation of variables, returned by a module's ``eval_context``
        property, assign a dictionary, describing these variables, to a local variable named
        ``__content__``:

        .. code-block:: python

           ...

           @property
           def eval_context(self):
               __content__ = {
                   'FOO': 'This is an important variable, extracted from clouds.'
                }

                return {
                    'FOO': 42
                }

        ``gluetool`` core will extract this information and will use it to generate different help
        texts like your module's help or a list of all known context variables.

        :rtype: dict
        """

        return {}


class Module(Configurable):
    """
    Base class of all ``gluetool`` modules.

    :param gluetool.glue.Glue glue: ``Glue`` instance owning the module.

    :ivar gluetool.glue.Glue glue: ``Glue`` instance owning the module.
    :ivar dict _config: internal configuration store. Values of all module options
      are stored here, regardless of them being set on command-line or in the
      configuration file.
    :ivar dict _overloaded_shared_functions: If a shared function added by this module
        overloades an older function of the same name, registered by a previous module,
        the overloaded one is added into this dictionary. The module can then call this
        saved function - using :py:meth:`overloaded_shared` - to implement a "chain" of
        shared functions, when one calls another, implementing the same operation.
    """

    name = None
    """Module name. Usually matches the name of the source file, no suffix."""

    description = None
    """Short module description, displayed in ``gluetool``'s module listing."""

    shared_functions = []
    """Iterable of names of shared functions exported by the module."""

    def _paths_with_module(self, roots):
        """
        Return paths cretaed by joining roots with module's unique name.

        :param list(str) roots: List of root directories.
        """

        return [os.path.join(root, self.unique_name) for root in roots]

    def __init__(self, glue, name):
        super(Module, self).__init__()

        # we need to save the unique name in case there are more aliases available
        self.unique_name = name

        self.glue = glue

        # initialize logging helpers
        self.logger = ModuleAdapter(glue.logger, self)
        self.logger.connect(self)

        # initialize data path if exists, else it will be None
        self.data_path = None

        for path in self._paths_with_module(self.glue.module_data_paths):
            if not os.path.exists(path):
                continue

            self.data_path = path
            self.debug('data file is {}'.format(path))
            break

        else:
            self.debug('no data file found')

        self._overloaded_shared_functions = {}

    @property
    def dryrun_level(self):
        return self.glue.dryrun_level

    def parse_config(self):
        self._parse_config(self._paths_with_module(self.glue.module_config_paths))

    def _generate_shared_functions_help(self):
        """
        Generate help for shared functions provided by the module.

        :returns: Formatted help, describing module's shared functions.
        """

        if not self.shared_functions:
            return ''

        from .help import functions_help

        functions = []

        for name in self.shared_functions:
            if not hasattr(self, name):
                raise GlueError("No such shared function '{}' of module '{}'".format(name, self.unique_name))

            functions.append((name, getattr(self, name)))

        return jinja2.Template(trim_docstring("""
        {{ '** Shared functions **' | style(fg='yellow') }}

        {{ FUNCTIONS }}
        """)).render(FUNCTIONS=functions_help(functions))

    def parse_args(self, args):
        epilog = [
            '' if self.options_note is None else docstring_to_help(self.options_note),
            self._generate_shared_functions_help(),
            eval_context_help(self)
        ]

        self._parse_args(args,
                         usage='{} [options]'.format(Colors.style(self.unique_name, fg='cyan')),
                         description=docstring_to_help(self.__doc__),
                         epilog='\n'.join(epilog).strip(),
                         formatter_class=LineWrapRawTextHelpFormatter)

    def destroy(self, failure=None):
        # pylint: disable-msg=no-self-use,unused-argument
        """
        Here should go any code that needs to be run on exit, like job cleanup etc.

        :param gluetool.glue.Failure failure: if set, carries information about failure that made
          ``gluetool`` to destroy the whole session. Modules might want to take actions based
          on provided information, e.g. send different notifications.
        """

        return None

    def add_shared(self):
        """
        Register module's shared functions with Glue, to allow other modules
        to use them.
        """

        for funcname in self.shared_functions:
            if self.has_shared(funcname):
                self._overloaded_shared_functions[funcname] = self.get_shared(funcname)

            self.glue.add_shared(funcname, self)

    def del_shared(self, funcname):
        self.glue.del_shared(funcname)

    def has_shared(self, funcname):
        return self.glue.has_shared(funcname)

    def require_shared(self, *names, **kwargs):
        return self.glue.require_shared(*names, **kwargs)

    def get_shared(self, funcname):
        return self.glue.get_shared(funcname)

    def execute(self):
        # pylint: disable-msg=no-self-use
        """
        In this method, modules can perform any work they deemed necessary for
        completing their purpose. E.g. if the module promises to run some tests,
        this is the place where the code belongs to.

        By default, this method does nothing. Reimplement as needed.
        """

    def sanity(self):
        # pylint: disable-msg=no-self-use
        """
        In this method, modules can define additional checks before execution.

        Some examples:

        * Advanced checks on passed options
        * Check for additional requirements (tools, data, etc.)

        By default, this method does nothing. Reimplement as needed.
        """

    def shared(self, *args, **kwargs):
        return self.glue.shared(*args, **kwargs)

    def overloaded_shared(self, funcname, *args, **kwargs):
        """
        Call a shared function overloaded by the one provided by this module. This way,
        a module can give chance to other implementations of its action, e.g. to publish
        messages on a different message bus.
        """

        if funcname not in self._overloaded_shared_functions:
            return None

        self.debug("calling overloaded shared function '{}'".format(funcname))

        return self._overloaded_shared_functions[funcname](*args, **kwargs)

    def run_module(self, module, args=None):
        self.glue.run_module(module, args or [])


class Glue(Configurable):
    # pylint: disable=too-many-public-methods

    """
    Main workhorse of the ``gluetool``. Manages modules, their instances and runs them as requested.

    :param gluetool.tool.Tool tool: If set, it's an ``gluetool``-like tool that created this instance.
        Some functionality may need it to gain access to bits like its command-name.
    :param gluetool.sentry.Sentry sentry: If set, it provides interface to Sentry.
    """

    name = 'gluetool core'

    options = [
        ('Global options', {
            ('l', 'list-modules'): {
                'help': 'List all available modules. If a GROUP is set, limits list to the given module group.',
                'action': 'append',
                'nargs': '?',
                'metavar': 'GROUP',
                'const': True
            },
            ('L', 'list-shared'): {
                'help': 'List all available shared functions.',
                'action': 'store_true',
                'default': False
            },
            ('E', 'list-eval-context'): {
                'help': 'List all available variables provided by modules in their evaluation contexts.',
                'action': 'store_true',
                'default': False,
            },
            ('r', 'retries'): {
                'help': 'Number of retries',
                'type': int,
                'default': 0
            },
            ('V', 'version'): {
                'help': 'Print version',
                'action': 'store_true'
            },
            'no-sentry-exceptions': {
                'help': 'List of exception names, which are not reported to Sentry (Default: none)',
                'action': 'append',
                'default': []
            }
        }),
        ('Output control', {
            ('c', 'colors'): {
                'help': 'Colorize logging on the terminal',
                'action': 'store_true'
            },
            ('d', 'debug'): {
                'help': 'Log debugging messages to the terminal (WARNING: very verbose!).',
                'action': 'store_true'
            },
            ('i', 'info'): {
                'help': 'Print command-line that would re-run the gluetool session',
                'action': 'store_true'
            },
            ('j', 'json-file'): {
                'help': """
                        If set, all log messages (including ``VERBOSE``) are stored in this file
                        in a form of JSON structures (default: %(default)s).
                        """,
                'default': None
            },
            ('o', 'debug-file', 'output'): {
                'help': 'Log messages with at least ``DEBUG`` level are sent to this file.'
            },
            'verbose-file': {
                'help': 'Log messages with ``VERBOSE`` level sent to this file.',
                'default': None
            },
            ('p', 'pid'): {
                'help': 'Log PID of gluetool process',
                'action': 'store_true'
            },
            ('q', 'quiet'): {
                'help': 'Silence info messages',
                'action': 'store_true'
            },
            'show-traceback': {
                'help': """
                        Display exception tracebacks on terminal (besides the debug file when ``--debug-file``
                        is used) (default: %(default)s).
                        """,
                'action': 'store_true',
                'default': False
            },
            ('v', 'verbose'): {
                'help': 'Log **all** messages to the terminal (WARNING: even more verbose than ``-d``!).',
                'action': 'store_true'
            }
        }),
        ('Directories', {
            'module-path': {
                'help': 'Specify directory with modules.',
                'metavar': 'DIR',
                'action': 'append',
                'default': []
            },
            'module-data-path': {
                'help': 'Specify directory with module data files.',
                'metavar': 'DIR',
                'action': 'append',
                'default': []
            },
            'module-config-path': {
                'help': 'Specify directory with module configuration files.',
                'metavar': 'DIR',
                'action': 'append',
                'default': []
            }
        }),
        ('Dry run options', {
            'dry-run': {
                'help': 'Modules that support this option will make no changes to the outside world.',
                'action': 'store_true',
                'default': False
            },
            'isolated-run': {
                'help': 'Modules that support this option will not interact with the outside world.',
                'action': 'store_true',
                'default': False
            }
        }),
        {
            'pipeline': {
                'raw': True,
                'help': 'List of modules and their options, passed after gluetool options.',
                'nargs': argparse.REMAINDER
            }
        }
    ]

    @property
    def module_paths(self):
        """
        List of paths in which modules reside.
        """

        from .utils import normalize_path_option
        return normalize_path_option(self.option('module-path')) or DEFAULT_MODULE_PATHS

    @property
    def module_data_paths(self):
        """
        List of paths in which module data files reside.
        """

        from .utils import normalize_path_option
        return normalize_path_option(self.option('module-data-path')) or [DEFAULT_DATA_PATH]

    @property
    def module_config_paths(self):
        """
        List of paths in which module config files reside.
        """

        from .utils import normalize_path_option
        return normalize_path_option(self.option('module-config-path')) or DEFAULT_MODULE_CONFIG_PATHS

    # pylint: disable=method-hidden
    def sentry_submit_exception(self, *args, **kwargs):
        """
        Submits exceptions to the Sentry server. Does nothing by default, unless this instance
        is initialized with a :py:class:`gluetool.sentry.Sentry` instance which actually does
        the job.

        See :py:meth:`gluetool.sentry.Sentry.submit_exception`.
        """

    # pylint: disable=method-hidden
    def sentry_submit_warning(self, *args, **kwargs):
        """
        Submits warnings to the Sentry server. Does nothing by default, unless this instance
        is initialized with a :py:class:`gluetool.sentry.Sentry` instance which actually does
        the job.

        See :py:meth:`gluetool.sentry.Sentry.submit_warning`.
        """

    def _add_shared(self, funcname, module, func):
        """
        Register a shared function. Overwrite previously registered function
        with the same name, if there was any such.

        This is a helper method for easier testability. It is not a part of public API of this class.

        :param str funcname: Name of the shared function.
        :param gluetool.glue.Module module: Module instance providing the shared function.
        :param callable func: Shared function.
        """

        self.debug("registering shared function '{}' of module '{}'".format(funcname, module.unique_name))

        self.shared_functions[funcname] = (module, func)

    def add_shared(self, funcname, module):
        """
        Register a shared function. Overwrite previously registered function
        with the same name, if there was any such.

        :param str funcname: Name of the shared function.
        :param gluetool.glue.Module module: Module instance providing the shared function.
        """

        if not hasattr(module, funcname):
            raise GlueError("No such shared function '{}' of module '{}'".format(funcname, module.name))

        self._add_shared(funcname, module, getattr(module, funcname))

    # delete a shared function if exists
    def del_shared(self, funcname):
        if funcname not in self.shared_functions:
            return

        del self.shared_functions[funcname]

    def has_shared(self, funcname):
        return funcname in self.shared_functions

    def require_shared(self, *names, **kwargs):
        warn_only = kwargs.get('warn_only', False)

        def _check(name):
            if self.has_shared(name):
                return True

            # pylint: disable=line-too-long
            msg = "Shared function '{}' is required. See `gluetool -L` to find out which module provides it.".format(name)  # Ignore PEP8Bear

            if warn_only is True:
                self.warn(msg, sentry=True)
                return False

            raise GlueError(msg)

        return all([_check(name) for name in names])

    def get_shared(self, funcname):
        if not self.has_shared(funcname):
            return None

        return self.shared_functions[funcname][1]

    def shared(self, funcname, *args, **kwargs):
        if funcname not in self.shared_functions:
            return None

        return self.shared_functions[funcname][1](*args, **kwargs)

    @property
    def eval_context(self):
        """
        Returns "global" evaluation context - some variables that are nice to have in all contexts.
        """

        # pylint: disable=unused-variable
        __content__ = {  # noqa
            'ENV': 'Dictionary representing environment variables.'
        }

        return {
            'ENV': dict(os.environ)
        }

    def _eval_context_module_caller(self):
        """
        Infere module instance calling the eval context shared function.

        :rtype: gluetool.glue.Module
        """

        stack = inspect.stack()
        log_dict(self.verbose, 'stack', stack)

        # When being called as a regular shared function, the call stack layout should be
        # as follows:
        #
        # Glue._eval_context_module_caller - this helper method, caller of inspect.stack()
        # Glue._eval_context - our caller, the actual shared function body
        # Glue.shared - shared function call dispatcher of Glue class, calls Glue._eval_context
        # Module.shared - shared function call dispatcher of Module class, calls Glue.shared internally

        # pylint: disable=too-many-boolean-expressions
        if len(stack) < 4 \
           or stack[0][3] != '_eval_context_module_caller' \
           or stack[1][3] != '_eval_context' \
           or stack[2][3] != 'shared' \
           or stack[3][3] != 'shared' \
           or 'self' not in stack[3][0].f_locals:
            self.warn('Cannot infer calling module of eval_context')
            return None

        return stack[3][0].f_locals['self']

    def _eval_context(self):
        """
        Gather contexts of all modules in a pipeline and merge them together.

        **Always** returns a unique dictionary object, therefore it is safe for caller
        to update it. The return value is not cached in any way, therefore the change
        if its content won't affect future callers.

        Provided as a shared function, registered by the Glue instance itself.

        :rtype: dict
        """

        self.debug('gather pipeline eval context')

        context = {
            'MODULE': self._eval_context_module_caller()
        }

        # first "module" is this instance - it provides eval_context as well.
        for module in [self] + self._module_instances:
            # cache the context for logging
            module_context = module.eval_context

            log_dict(module.verbose, 'eval context', module_context)

            context.update(module_context)

        return context

    #
    # Module loading
    #
    def _check_module_file(self, mfile):
        """
        Make sure the file looks like a ``gluetool`` module:

        - can be processed by Python parser,
        - imports :py:class:`gluetool.glue.Glue` and :py:class:`gluetool.glue.Module`,
        - contains child class of :py:class:`gluetool.glue.Module`.

        :param str mfile: path to a file.
        :returns: ``True`` if file contains ``gluetool`` module, ``False`` otherwise.
        :raises gluetool.glue.GlueError: when it's not possible to finish the check.
        """

        self.debug("check possible module file '{}'".format(mfile))

        try:
            with open(mfile) as f:
                node = ast.parse(f.read())

            # check for gluetool import
            def imports_gluetool(item):
                """
                Return ``True`` if item is an ``import`` statement, and imports ``gluetool``.
                """

                return (item.__class__.__name__ == 'Import' and item.names[0].name == 'gluetool') \
                    or (item.__class__.__name__ == 'ImportFrom' and item.module == 'gluetool')

            if not any((imports_gluetool(item) for item in node.__dict__['body'])):
                self.debug("  no 'import gluetool' found")
                return False

            # check for gluetool.Module class definition
            def has_module_class(item):
                """
                Return ``True`` if item is a class definition, and any of the base classes
                is gluetool.glue.Module.
                """

                if item.__class__.__name__ != 'ClassDef':
                    return False

                for base in item.bases:
                    if (hasattr(base, 'id') and base.id == 'Module') \
                            or (hasattr(base, 'attr') and base.attr == 'Module'):
                        return True

                return False

            if not any((has_module_class(item) for item in node.__dict__['body'])):
                self.debug('  no child of gluetool.Module found')
                return False

            return True

        # pylint: disable=broad-except
        except Exception as e:
            raise GlueError("Unable to check check module file '{}': {}".format(mfile, str(e)))

    def _import_module(self, import_name, filename):
        """
        Attempt to import a Python module from a file.

        :param str import_name: name assigned to the imported module.
        :param str filepath: path to a file.
        :returns: imported Python module.
        :raises gluetool.glue.GlueError: when import failed.
        """

        self.debug("try to import module '{}' from file '{}'".format(import_name, filename))

        try:
            return imp.load_source(import_name, filename)

        # pylint: disable=broad-except
        except Exception as e:
            raise GlueError("Unable to import module '{}' from '{}': {}".format(import_name, filename, str(e)))

    def _load_python_module(self, group, module_name, filepath):
        """
        Load Python module from a file, if it contains ``gluetool`` modules. If the
        file does not look like it contains ``gluetool`` modules, or when it's not
        possible to import the Python module successfully, method simply warns
        user and ignores the file.

        :param str import_name: name assigned to the imported module.
        :param str filepath: path to a file.
        :returns: loaded Python module.
        :raises gluetool.glue.GlueError: when import failed.
        """

        # Check content of the file, look for Glue and Module stuff
        try:
            if not self._check_module_file(filepath):
                return

        except GlueError as e:
            self.warn("ignoring file '{}': {}".format(module_name, e.message))
            return

        # Try to import file as a Python module
        import_name = 'gluetool.glue.{}-{}'.format(group, module_name)

        try:
            module = self._import_module(import_name, filepath)

        except GlueError as e:
            self.warn("ignoring module '{}': {}".format(module_name, e.message))
            return

        return module

    def _load_gluetool_modules(self, group, module_name, filepath):
        """
        Load ``gluetool`` modules from a file. Method attempts to import the file
        as a Python module, and then checks its content and adds all `gluetool`
        modules to internal module registry.

        :param str group: module group.
        :param str module_name: name assigned to the imported Python module.
        :param str filepath: path to a file.
        :rtype: [(module_group, module_class), ...]
        :returns: list of loaded ``gluetool`` modules
        """

        module = self._load_python_module(group, module_name, filepath)

        loaded_modules = []

        # Look for gluetool modules in imported stuff, and add them to our module registry
        for name in dir(module):
            cls = getattr(module, name)

            if not isinstance(cls, type) or not issubclass(cls, Module) or cls == Module:
                continue

            if not hasattr(cls, 'name') or not cls.name:
                raise GlueError("No name specified by module class '{}' from file '{}'".format(
                    cls.__name__, filepath))

            def add_module(mname, cls):
                if mname in self.modules:
                    raise GlueError("Name '{}' of module '{}' from '{}' is a duplicate module name".format(
                        mname, cls.__name__, filepath))

                self.debug("found module '{}', group '{}', in module '{}' from '{}'".format(
                    mname, group, module_name, filepath))

                self.modules[mname] = {
                    'class': cls,
                    'description': cls.description,
                    'group': group
                }

                loaded_modules.append((group, cls))

            # if name is a list, add more aliases to the same module
            if isinstance(cls.name, (list, tuple)):
                for mname in cls.name:
                    add_module(mname, cls)
            else:
                add_module(cls.name, cls)

        return loaded_modules

    def _load_module_path(self, ppath):
        """
        Search and load ``gluetool`` modules from a directory.

        In essence, it scans every file with ``.py`` suffix, and searches for
        classes derived from :py:class:`gluetool.glue.Module`.

        :param str ppath: directory to search for `gluetool` modules.
        """

        for root, _, files in os.walk(ppath):
            for filename in sorted(files):
                if not filename.endswith('.py'):
                    continue

                group = root.replace(ppath + '/', '')
                module_name, _ = os.path.splitext(filename)
                module_file = os.path.join(root, filename)

                self._load_gluetool_modules(group, module_name, module_file)

    def load_modules(self):
        """
        Load all available `gluetool` modules.
        """

        log_dict(self.debug, 'loading modules from these paths', self.module_paths)

        for path in self.module_paths:
            self._load_module_path(path)

    def __init__(self, tool=None, sentry=None):
        # Initialize logging methods before doing anything else.
        # Right now, we don't know the desired log level, or if
        # output file is in play, just get simple logger before
        # the actual configuration is known.
        self._sentry = sentry

        if sentry is not None:
            self.sentry_submit_exception = sentry.submit_exception
            self.sentry_submit_warning = sentry.submit_warning

        logger = Logging.create_logger(sentry=sentry, sentry_submit_warning=self.sentry_submit_warning)

        self.logger = ContextAdapter(logger)
        self.logger.connect(self)

        super(Glue, self).__init__()

        self.tool = tool

        self._dryrun_level = DryRunLevels.DEFAULT

        self.current_module = None

        # module types dictionary
        self.modules = {}

        # Materialized pipeline
        self._module_instances = []

        #: Shared function registry.
        #: funcname: (module, fn)
        self.shared_functions = {}

        self._add_shared('eval_context', self, self._eval_context)

    # pylint: disable=arguments-differ
    def parse_config(self, paths):
        self._parse_config(paths)

    def parse_args(self, args):
        module_dirs = '\n'.join(['        - {}'.format(directory) for directory in DEFAULT_MODULE_PATHS])
        data_dirs = '\n'.join(['        - {}'.format(directory) for directory in [DEFAULT_DATA_PATH]])
        module_config_dirs = '\n'.join(['        - {}'.format(directory) for directory in DEFAULT_MODULE_CONFIG_PATHS])

        epilog = trim_docstring("""
        Default paths:

            * modules are searched under (--module-path):
        {}

            * module data files are searched under (--module-data-path):
        {}

            * module configuration files are searched under (--module-config-path):
        {}

        """).format(module_dirs, data_dirs, module_config_dirs)

        self._parse_args(args,
                         usage='%(prog)s [options] [module1 [module1 options] module2 [module2 options] ...]',
                         epilog=epilog,
                         formatter_class=LineWrapRawTextHelpFormatter)

        # re-create logger - now we have all necessary configuration
        if self.option('verbose'):
            level = logging.VERBOSE

        elif self.option('debug'):
            level = logging.DEBUG

        elif self.option('quiet'):
            level = logging.WARNING

        else:
            level = logging.INFO

        import gluetool.color
        import gluetool.utils

        # enable global color support
        gluetool.color.switch(gluetool.utils.normalize_bool_option(self.option('colors')))

        debug_file = self.option('debug-file')
        verbose_file = self.option('verbose-file')
        json_file = self.option('json-file')

        if debug_file and not verbose_file:
            verbose_file = '{}.verbose'.format(debug_file)

        show_traceback = gluetool.utils.normalize_bool_option(self.option('show-traceback'))

        logger = Logging.create_logger(level=level,
                                       debug_file=debug_file,
                                       verbose_file=verbose_file,
                                       json_file=json_file,
                                       sentry=self._sentry,
                                       show_traceback=show_traceback)

        self.logger = ContextAdapter(logger)
        self.logger.connect(self)

        if level == logging.DEBUG and not verbose_file:
            # pylint: disable=line-too-long
            self.warn('Debug output enabled but no verbose destination set.')
            self.warn('Either use ``-v`` to display verbose messages on screen, or ``--verbose-file`` to store them in a file.')

        if self.option('isolated-run'):
            self._dryrun_level = DryRunLevels.ISOLATED

        elif self.option('dry-run'):
            self._dryrun_level = DryRunLevels.DRY

    @property
    def dryrun_level(self):
        return self._dryrun_level

    def _for_each_module(self, modules, callback, *args, **kwargs):
        for module in modules:
            self.current_module = module

            callback(module, *args, **kwargs)

    def destroy_modules(self, failure=None):
        if not self._module_instances:
            return

        # we will destroy modules in reverse order, which makes more sense
        self.debug('destroying all modules in reverse order')

        def _destroy(module):
            try:
                module.debug('destroying myself')
                module.destroy(failure=failure)

            # pylint: disable=broad-except
            except Exception as exc:
                destroy_failure = Failure(module=module, exc_info=sys.exc_info())

                msg = "Exception raised while destroying module '{}': {}".format(module.unique_name, exc.message)
                self.exception(msg, exc_info=destroy_failure.exc_info)
                self.sentry_submit_exception(destroy_failure, logger=self.logger)

                return destroy_failure

        self._for_each_module(reversed(self._module_instances), _destroy)

        self.current_module = None
        self._module_instances = []

    def init_module(self, module_name, actual_module_name=None):
        """
        Given a name of the module, create its instance and give it a name.

        :param str module_name: Name under which will be the module instance known.
        :param str actual_module_name: Name of the module to instantiate. It does not have to match
            ``module_name`` - ``actual_module_name`` refers to the list of known ``gluetool`` modules
            while ``module_name`` is basically an arbitrary name new instance calls itself. If it's
            not set, which is the most common situation, it defaults to ``module_name``.
        :returns: A :py:class:`Module` instance.
        """

        actual_module_name = actual_module_name or module_name

        return self.modules[actual_module_name]['class'](self, module_name)

    def run_modules(self, pipeline_desc, register=False):
        """
        Run a pipeline, consisting of multiple modules.

        :param list(PipelineStep) pipeline_desc: List of pipeline steps.
        :param bool register: If ``True``, module instance is added to a list of modules in this
            ``Glue`` instance, and it will be collected when :py:meth:`destroy_modules` gets called.
        """

        log_dict(self.debug, 'running a pipeline', pipeline_desc)

        modules = []

        for step in pipeline_desc:
            module = self.init_module(step.module, actual_module_name=step.actual_module)
            modules.append(module)

            if register is True:
                self._module_instances.append(module)

            module.parse_config()
            module.parse_args(step.argv)
            module.check_dryrun()

        def _sanity(module):
            module.sanity()
            module.check_required_options()

        self._for_each_module(modules, _sanity)

        def _execute(module):
            # We want to register module's shared function no matter how its ``execute``
            # finished or crashed. We could use ``try``-``finally`` and call add_shared there
            # but should there be an exception under ``try`` *and* should there be another
            # one under ``finally``, the first one would be lost, replaced by the later.
            # And we cannot guarantee exception-less ``add_shared``, it may have been replaced
            # by module's developer. Therefore resorting to being more verbose.
            try:
                module.execute()

            # pylint: disable=broad-except,unused-variable
            except Exception as exc:  # noqa
                # In case ``add_shared`` crashes, the original exception, raised in ``execute``,
                # is not lost since it's already captured as ``exc``. We will re-raise it when we're
                # done with ``add_shared``, and should ``add_shared`` crash, ``exc`` would be added
                # to a chain anyway.
                module.add_shared()
                raise exc.__class__, exc, sys.exc_info()[2]

            else:
                module.add_shared()

        self._for_each_module(modules, _execute)

        self.current_module = None

    def run_module(self, module_name, module_argv=None, actual_module_name=None, register=False):
        """
        Syntax sugar for :py:meth:`run_modules`, in the case you want to run just a one-shot module.

        :param str module_name: Name under which will be the module instance known.
        :param list(str) module_argv: Arguments of the module.
        :param str actual_module_name: Name of the module to instantiate. It does not have to match
            ``module_name`` - ``actual_module_name`` refers to the list of known ``gluetool`` modules
            while ``module_name`` is basically an arbitrary name new instance calls itself. If it's
            not set, which is the most common situation, it defaults to ``module_name``.
        :param bool register: If ``True``, module instance is added to a list of modules
            in this ``Glue`` instance, and it will be collected when :py:meth:`destroy_modules` gets
            called.
        """

        step = PipelineStep(module_name, actual_module=actual_module_name, argv=module_argv)

        return self.run_modules([step], register=register)

    def module_list(self):
        return sorted(self.modules)

    def module_list_usage(self, groups):
        """ Returns a string with modules description """

        if groups:
            usage = [
                'Available modules in {} group(s)'.format(', '.join(groups))
            ]
        else:
            usage = [
                'Available modules'
            ]

        # get module list
        plist = self.module_group_list()
        if not plist:
            usage.append('')
            usage.append('  -- no modules found --')
        else:
            for group in sorted(plist):
                # skip groups that are not in the list
                # note that groups is [] if all groups should be shown
                if groups and group not in groups:
                    continue
                usage.append('')
                usage.append('%-2s%s' % (' ', group))
                for key, val in sorted(plist[group].iteritems()):
                    usage.append('%-4s%-32s %s' % ('', key, val))

        return '\n'.join(usage)

    def module_group_list(self):
        """ Returns a dictionary of groups of modules with description """
        module_groups = {}
        for module in self.module_list():
            group = self.modules[module]['group']
            try:
                module_groups[group].update({
                    module: self.modules[module]['description']
                })
            except KeyError:
                module_groups[group] = {
                    module: self.modules[module]['description']
                }
        return module_groups
