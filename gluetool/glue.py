# pylint: disable=too-many-lines

import argparse
import collections
import ConfigParser
import imp
import inspect
import logging
import os
import sys
import warnings
import ast

from functools import partial

import enum
import jinja2
import mock
import pkg_resources

from .action import Action
from .color import Colors, switch as switch_colors
from .help import LineWrapRawTextHelpFormatter, option_help, docstring_to_help, trim_docstring, eval_context_help
from .log import Logging, LoggerMixin, ContextAdapter, ModuleAdapter, log_dict, VERBOSE

# Type annotations
# pylint: disable=unused-import,wrong-import-order
from typing import TYPE_CHECKING, cast, overload, Any, Callable, Dict, Iterable, List, Optional, NoReturn  # noqa
from typing import Sequence, Tuple, Type, Union, NamedTuple  # noqa
from types import TracebackType  # noqa
from .log import LoggingFunctionType, ExceptionInfoType  # noqa

if TYPE_CHECKING:
    import gluetool.color  # noqa
    import gluetool.utils  # noqa

# Type definitions
# pylint: disable=invalid-name
SharedType = Callable[..., Any]


DEFAULT_MODULE_CONFIG_PATHS = [
    '/etc/gluetool.d/config',
    os.path.expanduser('~/.gluetool.d/config'),
    os.path.abspath('./.gluetool.d/config')
]

DEFAULT_DATA_PATH = '{}/data'.format(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_MODULE_ENTRY_POINTS = [
    'gluetool.modules'
]

DEFAULT_MODULE_PATHS = [
    '{}/gluetool_modules'.format(sys.prefix)
]

#
# NOTE: pipelines and shared functions.
#
# Each `Glue` instance manages one or more pipelines. The main one, requested by the user, can spawn additional
# "side-car" pipelines, and these can spawn their own children, and so on. Only a single pipeline is being processed
# at the moment - when a new pipeline is spawned, its parent gives up its time for its kid, and is awoken when the
# kid finishes. `Glue` keeps a stack of pipelines as their appear and disappear. There is always a "current pipeline",
# which has a "current" module, the one being currently executed.
#
# Shared functions are managed by *pipelines* - each pipeline takes care of shared functions exported by its modules.
# `Glue` instance, shared by these pipelines, then allows modules to access all shared functions from all other
# existing pipelines: when a module wished to call a shared function, first the current pipeline (the one running
# the module) is inspected, then its parent, after that parent's parent and so on. This is ensured by `Module`
# API "secretly" calling `Glue` methods, which take care of checking all the layers.
#


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
    :param list(str) sentry_fingerprint: if set, it is used as a Sentry fingerprint of the exception. See
        :py:meth:`sentry_fingerprint` for more details.
    :param dict(str, str) sentry_tags: if set, it is merged with other tags when submitting the exception.
        See :py:meth:`sentry_tags` for more details.

    :ivar str message: Exception message, describing what happened.
    :ivar tuple caused_by: If set, contains tuple as returned by :py:func:`sys.exc_info`, describing
        the exception that caused this one to be born. ``None`` otherwise.
    """

    no_sentry_exceptions = []  # type: List[str]

    def __init__(self, message, caused_by=None, sentry_fingerprint=None, sentry_tags=None, **kwargs):
        # type: (str, Optional[ExceptionInfoType], Optional[List[str]], Optional[Dict[str, str]], **Any) -> None

        super(GlueError, self).__init__(message, **kwargs)  # type: ignore  # too many arguments but it's fine

        self.message = message

        self._sentry_fingerprint = sentry_fingerprint
        self._sentry_tags = sentry_tags

        # if not told explicitly, try to detect the cause
        if caused_by is None:
            caused_by = sys.exc_info()

        # if there's no cause, use None to signal that fact to the rest of the world
        if caused_by == (None, None, None):
            caused_by = None

        self.caused_by = caused_by

    @property
    def submit_to_sentry(self):
        # type: () -> bool

        # pylint: disable=no-self-use

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
        # type: (List[str]) -> List[str]

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

        If the exception was raised with ``sentry_fingerprint`` parameter set, it is returned
        instead of ``current``, after prefixing the list of tags with a name of the exception's
        class.

        :param list(str) current: current fingerprint. Usually ``['{{ default }}']`` telling
            Sentry to use its default method, but it could already be more specific.
        :rtype: list(str)
        :returns: new fingerprint, e.g. ``['FailedToConnectToAPI', '10.20.30.40']``
        """

        if self._sentry_fingerprint:
            return [
                self.__class__.__name__
            ] + self._sentry_fingerprint

        return current

    def sentry_tags(self, current):
        # type: (Dict[str, str]) -> Dict[str, str]

        # pylint: disable=no-self-use
        """
        Add, modify or remove tags attached to a Sentry event, reported when the exception
        was raised.

        Most common usage would be an addition of tags, e.g. ``remote-host`` to allow search
        for events related to the same remote address.

        If the exception was raised with ``sentry_tags`` parameter set, its value is injected
        to ``current`` before returning it.

        :param dict(str, str) current: current set of tags and their values.
        :rtype: dict(str, str)
        :returns: new set of tags. It is possible to add tags directly into ``current`` and
            then return it.
        """

        if self._sentry_tags:
            current.update(self._sentry_tags)

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
        # type: (List[str], gluetool.utils.ProcessOutput, **Any) -> None

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
        # type: (Optional[Module], ExceptionInfoType) -> None

        self.module = module
        self.exc_info = exc_info

        self.sentry_event_id = None  # type: Optional[str]
        self.sentry_event_url = None  # type: Optional[str]

        if exc_info:
            self.exception = exc_info[1]
            self.soft = isinstance(self.exception, SoftGlueError)

        else:
            self.exception = None
            self.soft = False


def retry(*args):
    # type: (*Any) -> Any

    """ Retry decorator
    This decorator catches given exceptions and returns
    libRetryError exception instead.

    usage: @retry(exception1, exception2, ..)
    """
    def wrap(func):
        # type: (Any) -> Any

        def func_wrapper(obj, *fargs, **fkwargs):
            # type: (Any, *Any, **Any) -> Any

            try:
                func(obj, *fargs, **fkwargs)
            except args as e:
                if isinstance(e, GlueError):
                    raise GlueRetryError(e.value)  # type: ignore
                else:
                    raise GlueRetryError(e)
        return func_wrapper
    return wrap


class PipelineStep(object):
    # pylint: disable=too-few-public-methods
    """
    Step of ``gluetool``'s  pipeline - which is basically just a list of steps.
    """

    def to_module(self, glue):
        # type: (Glue) -> Any

        raise NotImplementedError()


class PipelineStepModule(PipelineStep):
    # pylint: disable=too-few-public-methods
    """
    Step of ``gluetool``'s  pipeline backed by a module.

    :param str module: name to give to the module instance. This name is used e.g. in logging or when
        searching for module's config file.
    :param str actual_module: The actual module class the step uses. Usually it is same as ``module``
        but may differ, ``module`` is then a mere "alias". ``actual_module`` is used to locate
        a module class, whose instance is then given name ``module``.
    :param list(str) argv: list of options to be given to the module, in a form similar
        to :py:data:`sys.argv`.
    """

    def __init__(self, module, actual_module=None, argv=None):
        # type: (str, Optional[str], Optional[List[str]]) -> None

        self.module = module
        self.actual_module = actual_module or module
        self.argv = argv or []

    def __repr__(self):
        # type: () -> str

        return "PipelineStepModule('{}', actual_module='{}', argv={})".format(
            self.module,
            self.actual_module,
            self.argv
        )

    def to_module(self, glue):
        # type: (Glue) -> Module

        return glue.init_module(self.module, actual_module_name=self.actual_module)

    @property
    def module_designation(self):
        # type: () -> str

        return self.module if self.module == self.actual_module else '{}:{}'.format(self.module, self.actual_module)

    def serialize_to_json(self):
        # type: () -> Dict[str, Any]

        return {
            field: getattr(self, field) for field in ('module', 'actual_module', 'argv')
        }

    @classmethod
    def unserialize_from_json(cls, serialized):
        # type: (Dict[str, Any]) -> PipelineStepModule

        return PipelineStepModule(
            serialized['module'],
            actual_module=serialized['actual_module'],
            argv=serialized['argv']
        )


class PipelineStepCallback(PipelineStep):
    # pylint: disable=too-few-public-methods
    """
    Step of ``gluetool``'s  pipeline backed by callable.

    :param str name: name to give to the module instance. This name is used e.g. in logging or when
        searching for module's config file.
    :param callable callback: a callable to execute.
    """

    def __init__(self, name, callback, *args, **kwargs):
        # type: (str, Callable[..., None], *Any, **Any) -> None

        self.name = name
        self.callback = callback

        self.args = self.argv = args  # `argv` to match module-based pipelines
        self.kwargs = kwargs

    def __repr__(self):
        # type: () -> str

        return "PipelineStepCallback('{}', {})".format(self.name, self.callback)

    def to_module(self, glue):
        # type: (Glue) -> CallbackModule

        return CallbackModule(self.name, glue, self.callback)

    def serialize_to_json(self):
        # type: () -> Dict[str, Any]

        return {
            field: getattr(self, field) for field in ('name', 'callback')
        }

    @classmethod
    def unserialize_from_json(cls, serialized):
        # type: (Dict[str, Any]) -> NoReturn
        # pylint: disable=unused-argument

        raise GlueError('Cannot unserialize callback pipeline step')


#: Type of pipeline steps.
# pylint: disable=invalid-name
PipelineStepsType = Sequence[PipelineStep]

#: Return type of a pipeline.
# pylint: disable=invalid-name
PipelineReturnType = Tuple[Optional[Failure], Optional[Failure]]


class PipelineAdapter(ContextAdapter):
    """
    Custom logger adapter, adding pipeline name as a context.

    :param logging.Logger logger: parent logger this adapter modifies.
    """

    def __init__(self, logger, pipeline_name):
        # type: (ContextAdapter, str) -> None

        super(PipelineAdapter, self).__init__(logger, {'ctx_pipeline_name': (5, pipeline_name)})


class Pipeline(LoggerMixin, object):
    """
    Pipeline of ``gluetool`` modules. Defined by its steps, takes care of registering their shared functions,
    running modules and destroying the pipeline.

    To simplify the workflow, 2 primitives are defined:

    * :py:meth:`_safe_call` - calls a given callback, returns its return value. Any exception raised by the callback
      is wrapped by :py:class:`Failure` instance and returned instead of what callback would return.
    * :py:meth:`_for_each_module` - loop over given list of modules, calling given callback for each of the modules.
      :py:meth:`_safe_call` is used for the call, making sure we always have a return value and no exceptions.

    Coupled with the following rules, things clear up a bit:

    * Callbacks are allowed to return either ``None`` or ``Failure`` instance.
      * This rule matches ``_safe_call`` behavior. There's no need to worry about the return values, return value
        of a callback can be immediately passed through ``_safe_call``.
      * There are no other possible return values - return value is **always** either *nothing* or *failure*.
    * There are no "naked" exceptions, all are catched by ``_safe_call`` and converted to a common return value.
    * Users of ``_safe_call`` and ``_for_each_module`` also return either ``None`` or ``Failure`` instance, therefore
      it is very easy to end method by a ``return self._for_each_method(...)`` call - return types of callback,
      ``_safe_call``, ``_for_each_module`` and our method match, no need to translate them between these method.

    :param Glue glue: :py:class:`Glue` instance, taking care of this pipeline.
    :param list(PipelineStep) steps: modules to run and their options.
    :ivar list(Module) modules: list of instantiated modules forming the pipeline.
    :ivar Module current_module: if set, it is the module which is currently being executed.
    """

    def __init__(self, glue, steps, logger=None):
        # type: (Glue, PipelineStepsType, Optional[ContextAdapter]) -> None

        logger = logger or glue.logger

        super(Pipeline, self).__init__(logger)

        self.glue = glue
        self.steps = steps

        # Materialized pipeline
        self.modules = []  # type: List[Module]

        # Current module (if applicable)
        self.current_module = None  # type: Optional[Module]

        #: Shared function registry.
        #: funcname: (module, fn)
        self.shared_functions = {}  # type: Dict[str, Tuple[Configurable, SharedType]]

        # Action wrapping runtime of the pipeline. Initialized when pipeline begins running, all following
        # actions (e.g. executing modules) are children of this action.
        self.action = None  # type: Optional[Action]

    def _add_shared(self, funcname, module, func):
        # type: (str, Configurable, SharedType) -> None
        """
        Add a shared function. Overwrites previously registered shared function of the same name.

        Private part of API, for easier testing.

        :param str funcname: name of the shared function.
        :param Module module: module providing the shared function.
        :param callable func: the shared function.
        """

        self.debug("registering shared function '{}' of module '{}'".format(funcname, module.unique_name))

        self.shared_functions[funcname] = (module, func)

    def add_shared(self, funcname, module):
        # type: (str, Module) -> None
        """
        Add a shared function. Overwrites previously registered shared function of the same name.

        :param str funcname: name of the shared function.
        :param Module module: module providing the shared function.
        """

        if not hasattr(module, funcname):
            raise GlueError("No such shared function '{}' of module '{}'".format(funcname, module.name))

        self._add_shared(funcname, module, getattr(module, funcname))

    def has_shared(self, funcname):
        # type: (str) -> bool
        """
        Check whether a shared function of a given name exists.

        :param str funcname: name of the shared function.
        :rtype: bool
        """

        return funcname in self.shared_functions

    def get_shared(self, funcname):
        # type: (str) -> Optional[SharedType]
        """
        Return a shared function.

        :param str funcname: name of the shared function.
        :returns: a callable (shared function), or ``None`` if no such shared function exists.
        """

        if not self.has_shared(funcname):
            return None

        return self.shared_functions[funcname][1]

    def _safe_call(self, callback, *args, **kwargs):
        # type: (Callable[..., Optional[Failure]], *Any, **Any) -> Optional[Failure]
        """
        "Safe" call a function with given arguments, converting raised exceptions to :py:class:`Failure` instance.

        :param callable callback: callable to call. Must return either ``None`` or :py:class:`Failure` instance,
            although it can freely raise exceptions.
        :returns: value returned by ``callback``, or :py:class:`Failure` instance wrapping exception
            raise by ``callback``.
        """

        try:
            return callback(*args, **kwargs)

        # pylint: disable=broad-except
        except Exception:
            return Failure(module=self.current_module, exc_info=sys.exc_info())

    def _for_each_module(self, modules, callback, *args, **kwargs):
        # type: (Iterable[Module], Callable[..., Optional[Failure]], *Any, **Any) -> Optional[Failure]
        """
        For each module in a list, call a given function with module as its first argument. If the call
        returns anything but ``None``, the value is returned by this function as well, ending the loop.

        :param list(Module) modules: list of modules to iterate over.
        :param callable callback: a callback, accepting at least one parameter, current module of the loop.
            Must return either ``None`` or :py:class:`Failure` instance, although it can freely raise
            exceptions.
        :returns: value returned by ``callback``, or ``None`` when loop finished.
        """

        for module in modules:
            self.current_module = module

            # Given that we're using `_safe_call`, we shouldn't encounter any exception - `_safe_call`
            # would convert any exception into `Failure` instance. Callback also cannot return either
            # `None` or a failure. Therefore, if we got anything `True`-ish, we simply pass it to our
            # caller since it must be a failure.
            #
            # Note: This is enforced by type checks, we have no other power over the callback and its
            # return type.
            ret = self._safe_call(callback, module, *args, **kwargs)

            if ret:
                return ret

        return None

    def _log_failure(self, module, failure, label=None):
        # type: (Module, Failure, Optional[str]) -> None
        """
        Log a failure, and submit it to Sentry.

        :param Module module: module to use for logging - apparently, the failure appeared
            when this module was running.
        :param Failure failure: failure to log.
        :param str label: label for logging purposes. If it's set and exception exists, exception
            message is appended. If it's not set and exception exists, exception message is used.
            If failure has no exception, a generic message is the final choice.
        """

        if label and failure.exception:
            label = '{}: {}'.format(label, failure.exception)

        elif failure.exception:
            label = str(failure.exception)

        else:
            label = 'Exception raised'

        module.error(label, exc_info=failure.exc_info)

        self.glue.sentry_submit_exception(failure, logger=self.logger)

    def _setup(self):
        # type: () -> Optional[Failure]

        # Make a copy of steps - while setting modules up, we won't have access to module index, so we cannot
        # reach to `self.steps` for its arguments, but we can pop the first item of this list - it's always
        # the "current" module, the one currently being set up.
        steps = self.steps[:]

        for step in steps:
            module = step.to_module(self.glue)
            self.modules.append(module)

        def _do_setup(module):
            # type: (Module) -> None

            step = steps.pop(0)  # type: ignore  # sequence of modules does have `pop`...

            module.parse_config()

            if isinstance(step, PipelineStepModule):
                module.parse_args(step.argv)

            module.check_dryrun()

        return self._for_each_module(self.modules, _do_setup)

    def _sanity(self):
        # type: () -> Optional[Failure]

        def _do_sanity(module):
            # type: (Module) -> Optional[Failure]

            failure = self._safe_call(module.sanity)

            if failure:
                self._log_failure(module, failure)
                return failure

            failure = self._safe_call(module.check_required_options)

            if failure:
                self._log_failure(module, failure)
                return failure

            return None

        return self._for_each_module(self.modules, _do_sanity)

    def _execute(self):
        # type: () -> Optional[Failure]

        def _do_execute(module):
            # type: (Module) -> Optional[Failure]

            # Safely call module's `execute` method. We get either `None`, which is good, or a `Failure`
            # instance we can log, submit to Sentry and return to break the loop in `_for_each_module`.
            # The failure would then be propagated to `run()` method and it would represent the cause
            # that killed the pipeline.

            with Action(
                'executing module',
                parent=self.action,
                logger=module.logger,
                tags={
                    'unique-name': module.unique_name
                }
            ):
                failure = self._safe_call(module.execute)

            if failure:
                self._log_failure(module, failure, label='Exception raised')

            # Always register module's shared functions
            module.add_shared()

            return failure

        return self._for_each_module(self.modules, _do_execute)

    def _destroy(self, failure=None):
        # type: (Optional[Failure]) -> Optional[Failure]
        """
        "Destroy" the pipeline - call each module's ``destroy`` method, reversing the order of modules.
        If a ``destroy`` method raises an exception, loop ends and the failure is returned.

        :param Failure failure: if set, it represents a failure that caused pipeline to stop, which was followed
            by a call to currently running ``_destroy``. It is passed to modules' ``destroy`` methods.
        :returns: ``None`` if everything went well, or a :py:class:`Failure` instance if any ``destroy`` method
            raised an exception.
        """

        if not self.modules:
            return None

        self.debug('destroying modules')

        def _destroy(module):
            # type: (Module) -> Optional[Failure]

            # If we simply called module's `destroy` method, possible exception would be logged as any
            # other exception, but we want to add "while destroying" message, and make sure it's sent
            # to the Sentry. Therefore, adding `_safe_call` (inside `_destroy` which itself was called via
            # `_safe_call`), catching and logging the failure. After that, we simply return the "destroy failure"
            # from `_destroy`, which then causes `_for_each_module` to quit loop immediately, propagating this
            # destroy failure even further.

            # We get either `None` or a failure if an exception was raised by `destroy`. If it's a failure,
            # we can log it with a bit more context.
            with Action(
                'destroying module',
                parent=self.action,
                logger=module.logger,
                tags={
                    'unique-name': module.unique_name
                }
            ):
                destroy_failure = self._safe_call(module.destroy, failure=failure)

            if destroy_failure:
                self._log_failure(module, destroy_failure, label='Exception raised while destroying module')

            # Just like in the case of `execute` above, return `destroy_failure` - it is either `None`
            # or genuine `Failure` instance, representing the cause that killed the destroy stage.
            return destroy_failure

        final_failure = self._for_each_module(reversed(self.modules), _destroy)

        self.current_module = None
        self.modules = []

        return final_failure

    def run(self):
        # type: () -> PipelineReturnType
        """
        Run a pipeline - instantiate modules, prepare and execute each of them. When done,
        destroy all modules.

        :returns: tuple of two items, each of them either ``None`` or a :py:class:`Failure` instance. The first item
            represents the output of the pipeline, the second item represents the output of the destroy chain. If
            the item is ``None``, the stage finished without any issues, if it's a ``Failure`` instance, then an
            exception was raised during the stage, and ``Failure`` wraps it.
        """

        with Action('running pipeline', logger=self.logger) as self.action:
            log_dict(self.debug, 'running a pipeline', self.steps)

            # Take a list of modules, and call a helper method for each module of the list. The helper function calls
            # modules' methods, and these methods may raise exceptions. Should that happen, _safe_call` inside
            # `_for_each_module` will wrap them with `Failure` instance, collecting the necessary data.
            #
            # Here we dispatch loops, wait for them to return, and if a failure got back to us, we stop
            # running and try to clean things up.
            #
            # We always return "output of the forward run" and "output of the destroy run" - these "output" values
            # are either `None` or `Failure` instances. We don't check too often, all involved methods can accept
            # these objects and decide what to do with them.

            failure = self._setup()

            if failure:
                return failure, self._destroy(failure=failure)

            failure = self._sanity()

            if failure:
                return failure, self._destroy(failure=failure)

            failure = self._execute()

            return failure, self._destroy(failure=failure)


class NamedPipeline(Pipeline):
    """
    Pipeline with a name. The name is recorded in log messages emitted by the pipeline itself.

    :param Glue glue: :py:class:`Glue` instance, taking care of this pipeline.
    :param str name: name of the pipeline.
    :param list(PipelineStep) steps: modules to run and their options.
    :ivar list(Module) modules: list of instantiated modules forming the pipeline.
    :ivar Module current_module: if set, it is the module which is currently being executed.
    """

    def __init__(self, glue, name, steps):
        # type: (Glue, str, PipelineStepsType) -> None

        super(NamedPipeline, self).__init__(glue, steps, logger=PipelineAdapter(glue.logger, name))

        self.name = name


class ArgumentParser(argparse.ArgumentParser):
    """
    Pretty much the :py:class:`argparse.ArgumentParser`, it overrides just
    the :py:meth:`argparse.ArgumentParser.error` method, to catch errors and to wrap them
    into nice and common :py:class:`GlueError` instances.

    The original prints (for us) useless message, including the program name, and raises ``SystemExit``
    exception. Such action does not provide necessary information when encountered in Sentry, for example.
    """

    def error(self, message):  # type: ignore  # incompatible with supertype because of unicode
        # type: (str) -> None

        """
        Must not return - raising an exception is a good way to "not return".

        :raises gluetool.glue.GlueError: When argument parser encounters an error.
        """

        raise GlueError('Parsing command-line options failed: {}'.format(message))


class Configurable(LoggerMixin, object):
    """
    Base class of two main ``gluetool`` classes - :py:class:`gluetool.glue.Glue` and :py:class:`gluetool.glue.Module`.
    Gives them the ability to use `options`, settable from configuration files and/or command-line arguments.

    :ivar dict _config: internal configuration store. Values of all options
      are stored here, regardless of them being set on command-line or by the
      configuration file.
    """

    options = {}  # type: Union[Dict[Any, Any], List[Any]]
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

    required_options = []  # type: Iterable[str]
    """Iterable of names of required options."""

    options_note = None  # type: str
    """If set, it will be printed after all options as a help's epilog."""

    supported_dryrun_level = DryRunLevels.DEFAULT
    """Highest supported level of dry-run."""

    name = None  # type: str
    """
    Module name. Usually matches the name of the source file, no suffix.
    """

    unique_name = None  # type: Optional[str]
    """
    Unque name of this (module) instance.

    Used by modules, has no meaning elsewhere, but since dry-run checks are done on this level,
    it must be declared here to make pylint happy :/
    """

    def __repr__(self):
        # type: () -> str

        return '<Module {}:{}:{}>'.format(self.unique_name, self.name, id(self))

    @staticmethod
    def _for_each_option(callback, options):
        # type: (Callable[..., None], Any) -> None

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
        # type: (Callable[..., None], Any) -> None

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

    def __init__(self, logger):
        # type: (ContextAdapter) -> None

        super(Configurable, self).__init__(logger)

        # Initialize configuration store
        self._config = {}  # type: Dict[str, Any]

        # Initialize values in the store, and make sanity check of option names
        def _fail_name(name):
            # type: (str) -> None

            raise GlueError("Option name must be either a string or (<letter>, <string>), '{}' found".format(name))

        def _verify_option(name, names, params):
            # type: (str, List[str], Dict[str, Any]) -> None

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
            # type: (Dict[str, Dict[str, Any]], **Any) -> None

            # pylint: disable=unused-argument

            Configurable._for_each_option(_verify_option, options)

        Configurable._for_each_option_group(_verify_options, self.options)

    def _parse_config(self, paths):
        # type: (List[str]) -> None

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
            # type: (str, Tuple[str, ...], Dict[str, Any]) -> None

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
            self.debug("Option '{}' set to '{}' by config file".format(name, value))  # pylint: disable=not-callable

        def _inject_values(options, **kwargs):
            # type: (Any, **Any) -> None

            # pylint: disable=unused-argument

            Configurable._for_each_option(_inject_value, options)

        Configurable._for_each_option_group(_inject_values, self.options)

    @classmethod
    def _create_args_parser(cls, **kwargs):
        # type: (**Any) -> ArgumentParser

        """
        Create an argument parser. Used by Sphinx to document "command-line" options
        of the module - which are, by the way, the module options as well.

        :param dict kwargs: Additional arguments passed to :py:class:`argparse.ArgumentParser`.
        """

        root_parser = ArgumentParser(**kwargs)

        def _add_option(parser, name, names, params):
            # type: (ArgumentParser, str, Tuple[str, ...], Dict[str, Any]) -> None

            if params.get('raw', False) is True:
                final_names = (name,)  # type: Tuple[str, ...]
                del params['raw']

            else:
                if isinstance(names, str):
                    final_names = ('--{}'.format(name),)

                else:
                    final_names = ('-{}'.format(names[0]),) + tuple(['--{}'.format(n) for n in names[1:]])

            parser.add_argument(*final_names, **params)

        def _add_options(group_options, group_name=None):
            # type: (Any, Optional[str]) -> None

            group_parser = None  # type: Optional[Union[argparse.ArgumentParser, argparse._ArgumentGroup]]

            if group_name is None:
                group_parser = root_parser

            else:
                group_parser = root_parser.add_argument_group(group_name)

            assert group_parser is not None

            Configurable._for_each_option(partial(_add_option, group_parser), group_options)

        Configurable._for_each_option_group(_add_options, cls.options)

        return root_parser

    def _parse_args(self, args, **kwargs):
        # type: (Any, **Any) -> None

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
            # type: (str, Tuple[str, ...], Dict[str, Any]) -> None

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
            # type: (Any, **Any) -> None

            # pylint: disable=unused-argument

            Configurable._for_each_option(_inject_value, options)

        Configurable._for_each_option_group(_inject_values, self.options)

    def parse_config(self):
        # type: () -> None

        """
        Public entry point to configuration parsing. Child classes must implement this
        method, e.g. by calling :py:meth:`gluetool.glue.Configurable._parse_config` which
        requires list of paths.
        """

        # E.g. self._parse_config(<list of possible configuration files>)

        raise NotImplementedError('Implement this method to enable the actual parsing')

    def parse_args(self, args):
        # type: (List[str]) -> None

        """
        Public entry point to argument parsing. Child classes must implement this method,
        e.g. by calling :py:meth:`gluetool.glue.Configurable._parse_args` which makes use
        of additional :py:class:`argparse.ArgumentParser` options.
        """

        # E.g. self._parse_args(args, description=...)

        raise NotImplementedError('Implement this method to enable the actual parsing')

    def check_required_options(self):
        # type: () -> None

        if not self.required_options:
            self.debug('skipping checking of required options')
            return

        for name in self.required_options:
            if name not in self._config or not self._config[name]:
                raise GlueError("Missing required '{}' option".format(name))

    # `option()` returns two different types based on the number of positional arguments:
    #
    #   - 1 argument => returns just a single value (Any)
    #   - more than 1 argument => returns a tuple of values
    #
    # `mypy` supports typechecking of such function by using @overload decorators, describing
    # each variant, followed by the actual body of the function. We just need to silence pylint
    # and flake since we're re-defining the method - these checkes does not understand @overload.

    # pylint: disable=function-redefined

    @overload
    def option(self, name):
        # type: (str) -> Any

        pass

    @overload  # noqa
    def option(self, *names):
        # type: (*str) -> List[Any]

        pass

    def option(self, *names):  # type: ignore  # noqa
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
        # type: () -> int

        """
        Return current dry-run level. This must be implemented by class descendants
        because each one finds the necessary information in different places.
        """

        raise NotImplementedError()

    @property
    def dryrun_enabled(self):
        # type: () -> bool

        """
        ``True`` if dry-run level is enabled, on any level.
        """

        return self.dryrun_level != DryRunLevels.DEFAULT

    def _dryrun_allows(self, threshold, msg):
        # type: (int, str) -> bool

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
        # type: (str) -> bool

        """
        Checks whether current dry-run level allows an action which is disallowed on
        :py:attr:`DryRunLevels.DRY` level.

        See :py:meth:`Configurable._dryrun_allows` for detailed description.
        """

        return self._dryrun_allows(DryRunLevels.DRY, msg)

    def isolatedrun_allows(self, msg):
        # type: (str) -> bool

        """
        Checks whether current dry-run level allows an action which is disallowed on
        :py:attr:`DryRunLevels.ISOLATED` level.
        """

        return self._dryrun_allows(DryRunLevels.ISOLATED, msg)

    def check_dryrun(self):
        # type: () -> None

        """
        Checks whether this object supports current dry-run level.
        """

        if not self.dryrun_enabled:
            return

        if self.dryrun_level > self.supported_dryrun_level:
            dryrun_level_name = self.dryrun_level.name  # type: ignore  # `dryrun_level` is not pure int but Enum
            raise GlueError("Module '{}' does not support current dry-run level of '{}'".format(self.unique_name,
                                                                                                dryrun_level_name))

    @property
    def eval_context(self):
        # type: () -> Dict[str, Any]

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


class CallbackModule(mock.MagicMock):  # type: ignore  # MagicMock has type Any, complains about inheriting from it
    """
    Stand-in replacement for common :py:`Module` instances which does not represent any real module. We need it only
    to simplify code pipeline code - it can keep working with ``Module``-like instances, since this class mocks each
    and every method, but calls given ``callback`` in its ``execute`` method.

    :param str name: name of the pseudo-module.
    :param Glue glue: ``Glue`` instance governing the pipeline this module is part of.
    :param callable callback: called in the ``execute`` method. Its arguments will be ``glue``, followed by remaining
        positional and keyword arguments (``args`` and ``kwargs``).
    :param tuple args: passed to ``callback``.
    :param dict kwargs: passed to ``callback``.
    """

    def __init__(self, name, glue, callback, *args, **kwargs):
        # type: (str, Glue, Callable[..., None], *Any, **Any) -> None

        super(CallbackModule, self).__init__()

        self.glue = glue
        self.name = self.unique_name = name

        self._callback = callback
        self._args = args
        self._kwargs = kwargs

    def _get_child_mock(self, **kw):
        # type: (**Any) -> mock.MagicMock

        # The default implementation uses the same class it's member of, i.e. ``CallbackModule``. Too complicated,
        # we're perfectly fine with child mocks being of ``MagicMock``.

        return mock.MagicMock(**kw)

    def execute(self):
        # type: () -> None

        self._callback(self.glue, *self._args, **self._kwargs)

    def sanity(self):
        # type: () -> None

        # pylint: disable-msg=no-self-use
        return None

    def destroy(self, failure=None):
        # type: (Optional[Failure]) -> None

        # pylint: disable-msg=no-self-use,unused-argument
        return None

    def check_required_options(self):
        # type: () -> None

        # pylint: disable-msg=no-self-use
        return None


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

    description = None  # type: str
    """Short module description, displayed in ``gluetool``'s module listing."""

    shared_functions = []  # type: List[str]
    """Iterable of names of shared functions exported by the module."""

    def _paths_with_module(self, roots):
        # type: (List[str]) -> List[str]

        """
        Return paths cretaed by joining roots with module's unique name.

        :param list(str) roots: List of root directories.
        """

        assert self.unique_name is not None

        return [os.path.join(root, self.unique_name) for root in roots]

    def __init__(self, glue, name):
        # type: (Glue, str) -> None

        # we need to save the unique name in case there are more aliases available
        self.unique_name = name

        super(Module, self).__init__(ModuleAdapter(glue.logger, self))

        self.glue = glue

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

        self._overloaded_shared_functions = {}  # type: Dict[str, SharedType]

    @property
    def dryrun_level(self):
        # type: () -> int

        return self.glue.dryrun_level

    def parse_config(self):
        # type: () -> None

        self._parse_config(self._paths_with_module(self.glue.module_config_paths))

    def _generate_shared_functions_help(self):
        # type: () -> str

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
        """)).render(FUNCTIONS=functions_help(functions)).encode('ascii')

    def parse_args(self, args):
        # type: (Any) -> None

        epilog = [
            '' if self.options_note is None else docstring_to_help(self.options_note),
            self._generate_shared_functions_help(),
            eval_context_help(self)
        ]

        self._parse_args(args,
                         usage='{} [options]'.format(Colors.style(self.unique_name, fg='cyan')),
                         description=docstring_to_help(self.__doc__ or ''),
                         epilog='\n'.join(epilog).strip(),
                         formatter_class=LineWrapRawTextHelpFormatter)

    def add_shared(self):
        # type: () -> None
        """
        Add all shared functions declared by the module.
        """

        for funcname in self.shared_functions:
            original_shared = self.glue.get_shared(funcname)

            if original_shared:
                self._overloaded_shared_functions[funcname] = original_shared

            self.glue.add_shared(funcname, self)

    def has_shared(self, funcname):
        # type: (str) -> bool
        """
        Check whether a shared function of a given name exists.

        :param str funcname: name of the shared function.
        :rtype: bool
        """

        # A proxy for Glue's `has_shared`, exists to simplify modules.

        return self.glue.has_shared(funcname)

    def require_shared(self, *names, **kwargs):
        # type: (*str, **str) -> bool
        """
        Make sure given shared functions exist.

        :param tuple(str) names: iterable of shared function names.
        :param bool warn_only: if set, only warning is emitted. Otherwise, when any required shared function didn't
            exist, an exception is raised.
        """

        # A proxy for Glue's `require_shared`, exists to simplify modules.

        return self.glue.require_shared(*names, **kwargs)

    def get_shared(self, funcname):
        # type: (str) -> Optional[SharedType]
        """
        Return a shared function.

        :param str funcname: name of the shared function.
        :returns: a callable (shared function), or ``None`` if no such shared function exists.
        """

        # A proxy for Glue's `get_shared`, exists to simplify modules.

        return self.glue.get_shared(funcname)

    def shared(self, funcname, *args, **kwargs):
        # type: (str, *Any, **Any) -> Any
        """
        Call a shared function, passing it all positional and keyword arguments.
        """

        # A proxy for Glue's `shared`, exists to simplify modules.

        return self.glue.shared(funcname, *args, **kwargs)

    def overloaded_shared(self, funcname, *args, **kwargs):
        # type: (str, *Any, **Any) -> Any
        """
        Call a shared function overloaded by the one provided by this module. This way,
        a module can give chance to other implementations of the same name, e.g. function
        named ``publish_message``, working with message bus A, would call previously
        shared function holding of this name, registered by a module earlier in the pipeline,
        which works with message bus B.
        """

        # *Not* a proxy for Glue's `overloaded_shared` - Glue core doesn't care about one module overloading
        # another module's shared function, Glue handles just the whole pipelines.

        if funcname not in self._overloaded_shared_functions:
            return None

        self.debug("calling overloaded shared function '{}'".format(funcname))

        return self._overloaded_shared_functions[funcname](*args, **kwargs)

    def sanity(self):
        # type: () -> None

        # pylint: disable-msg=no-self-use
        """
        In this method, modules can define additional checks before execution.

        Some examples:

        * Advanced checks on passed options
        * Check for additional requirements (tools, data, etc.)

        By default, this method does nothing. Reimplement as needed.
        """

    def execute(self):
        # type: () -> None

        # pylint: disable-msg=no-self-use
        """
        In this method, modules can perform any work they deemed necessary for
        completing their purpose. E.g. if the module promises to run some tests,
        this is the place where the code belongs to.

        By default, this method does nothing. Reimplement as needed.
        """

    def destroy(self, failure=None):
        # type: (Optional[Failure]) -> None

        # pylint: disable-msg=no-self-use,unused-argument
        """
        Here should go any code that needs to be run on exit, like job cleanup etc.

        :param gluetool.glue.Failure failure: if set, carries information about failure that made
          ``gluetool`` to destroy the whole session. Modules might want to take actions based
          on provided information, e.g. send different notifications.
        """

    def run_module(self, module, args=None):
        # type: (str, Optional[List[str]]) -> None

        self.glue.run_module(module, args or [])


#: Describes one discovered ``gluetool`` module.
#:
#: :ivar Module klass: a module class.
#: :ivar str group: group the module belongs to.
DiscoveredModule = NamedTuple('DiscoveredModule', (
    ('klass', Type[Module]),
    ('group', str)
))

#: Module registry type.
ModuleRegistryType = Dict[str, DiscoveredModule]


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
            },
            'module-entry-point': {
                'help': 'Specify setuptools entry point for modules.',
                'metavar': 'ENTRY-POINT',
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
    def module_entry_points(self):
        # type: () -> List[str]

        """
        List of setuptools entry points to which modules are attached.
        """

        from .utils import normalize_multistring_option
        return normalize_multistring_option(self.option('module-entry-point')) or DEFAULT_MODULE_ENTRY_POINTS

    @property
    def module_paths(self):
        # type: () -> List[str]

        """
        List of paths in which modules reside.
        """

        from .utils import normalize_path_option
        return normalize_path_option(self.option('module-path')) or DEFAULT_MODULE_PATHS

    @property
    def module_data_paths(self):
        # type: () -> List[str]

        """
        List of paths in which module data files reside.
        """

        from .utils import normalize_path_option
        return normalize_path_option(self.option('module-data-path')) or [DEFAULT_DATA_PATH]

    @property
    def module_config_paths(self):
        # type: () -> List[str]

        """
        List of paths in which module config files reside.
        """

        from .utils import normalize_path_option
        return normalize_path_option(self.option('module-config-path')) or DEFAULT_MODULE_CONFIG_PATHS

    # pylint: disable=method-hidden
    def sentry_submit_exception(self, *args, **kwargs):
        # type: (*Any, **Any) -> None

        """
        Submits exceptions to the Sentry server. Does nothing by default, unless this instance
        is initialized with a :py:class:`gluetool.sentry.Sentry` instance which actually does
        the job.

        See :py:meth:`gluetool.sentry.Sentry.submit_exception`.
        """

    # pylint: disable=method-hidden
    def sentry_submit_message(self, *args, **kwargs):
        # type: (*Any, **Any) -> None

        """
        Submits message to the Sentry server. Does nothing by default, unless this instance
        is initialized with a :py:class:`gluetool.sentry.Sentry` instance which actually does
        the job.

        See :py:meth:`gluetool.sentry.Sentry.submit_warning`.
        """

    def add_shared(self, funcname, module):
        # type: (str, Module) -> None

        """
        Add a shared function. Overwrites previously registered shared function of the same name.

        :param str funcname: name of the shared function.
        :param Module module: module providing the shared function.
        """

        # A proxy for current pipeline's `add-shared.`

        self.current_pipeline.add_shared(funcname, module)

    def has_shared(self, funcname):
        # type: (str) -> bool
        """
        Check whether a shared function of a given name exists.

        :param str funcname: name of the shared function.
        :rtype: bool
        """

        # Check all running pieplines, start with the most recent one.

        for pipeline in reversed(self.pipelines):
            if pipeline.has_shared(funcname):
                return True

        return False

    def require_shared(self, *names, **kwargs):
        # type: (*str, **str) -> bool
        """
        Make sure given shared functions exist.

        :param tuple(str) names: iterable of shared function names.
        :param bool warn_only: if set, only warning is emitted. Otherwise, when any required shared function didn't
            exist, an exception is raised.
        """

        warn_only = kwargs.get('warn_only', False)

        def _check(name):
            # type: (str) -> bool

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
        # type: (str) -> Optional[SharedType]
        """
        Return a shared function.

        :param str funcname: name of the shared function.
        :returns: a callable (shared function), or ``None`` if no such shared function exists.
        """

        # Check all running pieplines, start with the most recent one.

        for pipeline in reversed(self.pipelines):
            if pipeline.has_shared(funcname):
                return pipeline.get_shared(funcname)

        return None

    def shared(self, funcname, *args, **kwargs):
        # type: (str, *Any, **Any) -> Any
        """
        Call a shared function, passing it all positional and keyword arguments.
        """

        func = self.get_shared(funcname)

        if not func:
            return None

        return func(*args, **kwargs)

    @property
    def eval_context(self):
        # type: () -> Dict[str, Any]

        """
        Returns "global" evaluation context - some variables that are nice to have in all contexts.
        """

        # pylint: disable=unused-variable
        __content__ = {  # noqa
            'ENV': 'Dictionary representing environment variables.',
            'PIPELINE': 'Current pipeline, represented as a list of ``PipelineStep`` instances.'
        }

        return {
            'ENV': dict(os.environ),
            'PIPELINE': self.current_pipeline.steps
        }

    def _eval_context_module_caller(self):
        # type: () -> Optional[Module]

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

        return cast(Module, stack[3][0].f_locals['self'])

    def _eval_context(self):
        # type: () -> Dict[str, Any]

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

        # 1st "module" is always this instance of ``Glue``.
        # Then we walk through all pipelines, from the oldest to the most recent ones, and call their modules
        # in the order they were specified.
        context.update(self.eval_context)

        for pipeline in self.pipelines:
            for module in pipeline.modules:
                context.update(module.eval_context)

        log_dict(self.verbose, 'eval context', context)

        return context

    @property
    def current_pipeline(self):
        # type: () -> Pipeline

        return self.pipelines[-1]

    @property
    def current_module(self):
        # type: () -> Optional[Module]

        return self.current_pipeline.current_module

    #
    # Module discovery and loading
    #
    def _register_module(self, registry, group_name, klass, filepath):
        # type: (ModuleRegistryType, str, Type[Module], str) -> None
        """
        Register one discovered ``gluetool`` module.

        :param dict(str, DiscoveredModule) registry: module registry to add module to.
        :param str group_name: group the module belongs to.
        :param Module klass: module class.
        :param str filepath: path to a file module comes from.
        """

        names = getattr(klass, 'name', None)  # type: Union[None, List[str], Tuple[str]]

        if not names:
            raise GlueError('No name specified by module class {}:{}'.format(filepath, klass.__name__))

        def _do_register_module(name):
            # type: (str) -> None

            if name in registry:
                raise GlueError("Name '{}' of class {}:{} is a duplicate module name".format(
                    name, filepath, klass.__name__
                ))

            self.debug("registering module '{}' from {}:{}".format(name, filepath, klass.__name__))

            registry[name] = DiscoveredModule(klass, group_name)

        if isinstance(names, (list, tuple)):
            for alias in names:
                _do_register_module(alias)

        else:
            _do_register_module(names)

    def _check_pm_file(self, filepath):
        # type: (str) -> bool

        """
        Make sure a file looks like a ``gluetool`` module:

        - can be processed by Python parser,
        - imports :py:class:`gluetool.glue.Glue` and :py:class:`gluetool.glue.Module`,
        - contains child class of :py:class:`gluetool.glue.Module`.

        :param str filepath: path to a file.
        :returns: ``True`` if file contains ``gluetool`` module, ``False`` otherwise.
        :raises gluetool.glue.GlueError: when it's not possible to finish the check.
        """

        self.debug("check possible module file '{}'".format(filepath))

        try:
            with open(filepath) as f:
                node = ast.parse(f.read())

            # check for gluetool import
            def imports_gluetool(item):
                # type: (Any) -> bool

                """
                Return ``True`` if item is an ``import`` statement, and imports ``gluetool``.
                """

                class_name = item.__class__.__name__

                is_import = class_name == 'Import' and item.names[0].name == 'gluetool'
                is_import_from = class_name == 'ImportFrom' and item.module == 'gluetool'

                return cast(bool, is_import or is_import_from)

            if not any((imports_gluetool(item) for item in node.__dict__['body'])):
                self.debug("  no 'import gluetool' found")
                return False

            # check for gluetool.Module class definition
            def has_module_class(item):
                # type: (Any) -> bool

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
            raise GlueError("Unable to check check module file '{}': {}".format(filepath, e))

    def _do_import_pm(self, filepath, pm_name):
        # type: (str, str) -> Any

        """
        Attempt to import a file as a Python module.

        :param str filepath: a file to import.
        :param str pm_name: name assigned to the imported module.
        :returns: imported Python module.
        :raises gluetool.glue.GlueError: when import failed.
        """

        self.debug("try to import '{}' as a module '{}'".format(filepath, pm_name))

        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)

                pm = imp.load_source(pm_name, filepath)

            self.debug('imported file {} as a Python module {}'.format(filepath, pm_name))

            return pm

        # pylint: disable=broad-except
        except Exception as exc:
            raise GlueError("Unable to import file '{}' as a module: {}".format(filepath, exc))

    def _import_pm(self, filepath, pm_name):
        # type: (str, str) -> Any
        """
        If a file contains ``gluetool`` modules, import the file as a Python module. If the file does not look
        like it contains ``gluetool`` modules, or when it's not possible to import the Python module successfully,
        method simply warns user and ignores the file.

        :param str filepath: file to load.
        :param str pm_name: Python module name for the loaded module.
        :returns: loaded Python module.
        :raises gluetool.glue.GlueError: when import failed.
        """

        # Check content of the file, look for Glue and Module stuff.
        try:
            if not self._check_pm_file(filepath):
                return

        except GlueError as exc:
            self.warn("ignoring file '{}': {}".format(filepath, exc))
            return

        # Try to import the file.
        try:
            pm = self._do_import_pm(filepath, pm_name)

        except GlueError as exc:
            self.warn("ignoring file '{}': {}".format(filepath, exc))
            return

        return pm

    def _discover_gm_in_file(self, registry, filepath, pm_name, group_name):
        # type: (ModuleRegistryType, str, str, str) -> None
        """
        Discover ``gluetool`` modules in a file.

        Attempts to import the file as a Python module, and then checks its content and looks for ``gluetool``
        modules.

        :param dict(str, DiscoveredModule) registry: registry of modules to which new ones would be added.
        :param str filepath: path to a file.
        :param str pm_name: a Python module name to use for the imported module.
        :param str group_name: a ``gluetool`` module group name assigned to ``gluetool`` modules discovered
            in the file.
        """

        pm = self._import_pm(filepath, pm_name)

        if not pm:
            return

        # Look for gluetool modules in imported Python module's members, and register them.
        for _, member in inspect.getmembers(pm, inspect.isclass):
            if not isinstance(member, type) or not issubclass(member, Module) or member == Module:
                continue

            assert issubclass(member, Module)

            self._register_module(registry, group_name, member, filepath)

    def _discover_gm_in_dir(self, dirpath, registry, pm_prefix):
        # type: (str, ModuleRegistryType, str) -> None
        """
        Discover ``gluetool`` modules in a directory tree.

        In essence, it scans directory and its subdirectories for files with ``.py`` suffix, and searches for
        classes derived from :py:class:`gluetool.glue.Module` in these files.

        :param str dirpath: path to a directory.
        :param dict(str, DiscoveredModule) registry: registry of modules to which new ones would be added.
        :param str pm_prefix: a string used to prefix all imported Python module names.
        """

        self.debug('discovering modules in directory {}'.format(dirpath))

        for root, _, files in os.walk(dirpath):
            for filename in sorted(files):
                if not filename.endswith('.py'):
                    continue

                # A group of the module is defined by the directories it lies in under the ``dirpath``.
                if root == dirpath:
                    group_name = ''
                else:
                    group_name = root.replace(dirpath + os.sep, '')

                pm_name = '{}.{}.{}'.format(
                    pm_prefix,
                    group_name.replace(os.sep, '.'),
                    os.path.splitext(filename)[0]
                )

                self._discover_gm_in_file(registry, os.path.join(root, filename), pm_name, group_name)

    def _discover_gm_in_entry_point(self, entry_point, registry):
        # type: (str, ModuleRegistryType) -> None

        self.debug('discovering modules in entry point {}'.format(entry_point))

        for ep_entry in pkg_resources.iter_entry_points(entry_point):
            klass = ep_entry.load()

            self._register_module(registry, getattr(klass, 'group', ''), klass, ep_entry.dist.location)

    def discover_modules(self, entry_points=None, paths=None):
        # type: (Optional[List[str]], Optional[List[str]]) -> ModuleRegistryType
        """
        Discover and load all accessible modules.

        Two sources are examined:

        1. entry points, handled by setuptools, to which Python packages can attach ``gluetool`` modules they provide,
        2. directory trees.

        :param list(str) entry_points: list of entry point names to which ``gluetool`` modules are attached.
            If not set, entry points set byt the configuration (``--module-entry-point`` option) are used.
        :param list(str) paths: list of directories to search for ``gluetool`` modules. If not set, paths set by
            the configuration (``--module-path`` option) are used.
        :rtype: dict(str, DiscoveredModule)
        :returns: mapping between module names and ``DiscoveredModule`` instances, describing each module.
        """

        entry_points = entry_points or self.module_entry_points
        paths = paths or self.module_paths

        log_dict(self.debug, 'discovering modules under following entry points', entry_points)
        log_dict(self.debug, 'discovering modules under following paths', paths)

        modules_registry = {}  # type: ModuleRegistryType

        for entry_point in entry_points:
            self._discover_gm_in_entry_point(entry_point, modules_registry)

        for path in paths:
            self._discover_gm_in_dir(path, modules_registry, 'gluetool.file_modules')

        log_dict(self.debug, 'discovered modules', modules_registry)

        return modules_registry

    def __init__(self, tool=None, sentry=None):
        # type: (Optional[Any], Optional[Any]) -> None

        # Initialize logging methods before doing anything else.
        # Right now, we don't know the desired log level, or if
        # output file is in play, just get simple logger before
        # the actual configuration is known.
        self._sentry = sentry

        if sentry is not None:
            self.sentry_submit_exception = sentry.submit_exception  # type: ignore
            self.sentry_submit_message = sentry.submit_message  # type: ignore

        Logging.setup_logger(sentry=sentry)

        super(Glue, self).__init__(Logging.get_logger())

        self.tool = tool

        self._dryrun_level = DryRunLevels.DEFAULT

        # module types dictionary
        self.modules = {}  # type: ModuleRegistryType

        # Pipeline stack - start with a mock pipeline: we need a place to register our shared functions.
        self.pipelines = [
            Pipeline(self, [])
        ]

        # pylint: disable=protected-access
        self.current_pipeline._add_shared('eval_context', self, self._eval_context)

    # pylint: disable=arguments-differ
    def parse_config(self, paths):  # type: ignore  # signature differs on purpose
        # type: (List[str]) -> None

        self._parse_config(paths)

    def parse_args(self, args):
        # type: (Any) -> None

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

        Supported environment variables:

        * GLUETOOL_TRACING_DISABLE - when set, tracing won't be enabled
        * GLUETOOL_TRACING_SERVICE_NAME (string) - name of the trace produced by tool execution
        * GLUETOOL_TRACING_REPORTING_HOST (string) - a hostname where tracing collector listens
        * GLUETOOL_TRACING_REPORTING_PORT (int) - a port on which tracing collector listens
        """).format(module_dirs, data_dirs, module_config_dirs)

        self._parse_args(args,
                         usage='%(prog)s [options] [module1 [module1 options] module2 [module2 options] ...]',
                         epilog=epilog,
                         formatter_class=LineWrapRawTextHelpFormatter)

        # re-create logger - now we have all necessary configuration
        if self.option('verbose'):
            level = VERBOSE

        elif self.option('debug'):
            level = logging.DEBUG

        elif self.option('quiet'):
            level = logging.WARNING

        else:
            level = logging.INFO

        from .utils import normalize_bool_option
        switch_colors(normalize_bool_option(self.option('colors')))

        debug_file = self.option('debug-file')
        verbose_file = self.option('verbose-file')
        json_file = self.option('json-file')

        if debug_file and not verbose_file:
            verbose_file = '{}.verbose'.format(debug_file)

        Logging.setup_logger(
            level=level,
            debug_file=debug_file,
            verbose_file=verbose_file,
            json_file=json_file,
            sentry=self._sentry,
            show_traceback=normalize_bool_option(self.option('show-traceback'))
        )

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
        # type: () -> int

        return self._dryrun_level

    def init_module(self, module_name, actual_module_name=None):
        # type: (str, Optional[str]) -> Module

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
        klass = self.modules[actual_module_name].klass  # type: Type[Module]

        return klass(self, module_name)

    def run_pipeline(self, pipeline):
        # type: (Pipeline) -> PipelineReturnType

        self.pipelines.append(pipeline)

        try:
            return pipeline.run()

        finally:
            self.pipelines.pop(-1)

    def run_modules(self, steps):
        # type: (PipelineStepsType) -> PipelineReturnType

        return self.run_pipeline(Pipeline(self, steps))

    def run_module(self, module_name, module_argv=None, actual_module_name=None):
        # type: (str, Optional[List[str]], Optional[str]) -> PipelineReturnType

        """
        Syntax sugar for :py:meth:`run_modules`, in the case you want to run just a one-shot module.

        :param str module_name: Name under which will be the module instance known.
        :param list(str) module_argv: Arguments of the module.
        :param str actual_module_name: Name of the module to instantiate. It does not have to match
            ``module_name`` - ``actual_module_name`` refers to the list of known ``gluetool`` modules
            while ``module_name`` is basically an arbitrary name new instance calls itself. If it's
            not set, which is the most common situation, it defaults to ``module_name``.
        """

        step = PipelineStepModule(module_name, actual_module=actual_module_name, argv=module_argv)

        return self.run_modules([step])

    def modules_as_groups(self, modules=None):
        # type: (Optional[ModuleRegistryType]) -> Dict[str, ModuleRegistryType]
        """
        Gathers modules by their groups.

        :rtype: dict(str, dict(str, DiscoveredModule))
        :returns: dictonary where keys represent module groups, and values are mappings between
            module names and the corresponding modules.
        """

        modules = modules or self.modules

        groups = collections.defaultdict(dict)  # type: Dict[str, ModuleRegistryType]

        for name, module_info in modules.iteritems():
            groups[module_info.group][name] = module_info

        return groups

    def modules_descriptions(self, modules=None, groups=None):
        # type: (Optional[ModuleRegistryType], Optional[List[str]]) -> str
        """
        Returns a string with modules and their descriptions.

        :param dict(str, DiscoveredModule) modules: mapping with modules. If not set, current known modules
            are used.
        :param list(str) groups: if set, limit descriptions to modules belinging to the given groups.
        :rtype: str
        """

        modules = modules or self.modules

        as_groups = self.modules_as_groups(modules=modules)

        # List of lines, will be merged with `\n` before printing.
        descriptions = []  # type: List[str]

        if groups:
            descriptions += [
                'Available modules in group(s) {}'.format(', '.join(groups))
            ]

        else:
            descriptions += [
                'Available modules'
            ]

        def _add_no_modules():
            # type: () -> None

            descriptions.extend([
                '',
                '  -- no modules found --'
            ])

        if not as_groups:
            _add_no_modules()

        else:
            descriptions += [
                ''
            ]

            for group_name, group in sorted(as_groups.iteritems()):
                # skip groups that are not in the list
                # note that groups is None if all groups should be shown
                if groups and group_name not in groups:
                    continue

                group = as_groups[group_name]

                if not group:
                    _add_no_modules()
                    continue

                for module_name, module in sorted(group.iteritems()):
                    # Indent module name by 4 spaces, and reserve 32 characters for each module name,
                    # starting all descriptions at the same offset.
                    descriptions.append('    {:32} {}'.format(module_name, module.klass.description))

        return '\n'.join(descriptions)
