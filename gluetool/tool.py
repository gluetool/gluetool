"""
Heart of the "gluetool" script. Referred to by setuptools' entry point.
"""

import functools
import logging
import os
import re
import signal
import sys
import traceback

import tabulate

import gluetool
import gluetool.action
import gluetool.sentry

from gluetool import GlueError, GlueRetryError, Failure
from gluetool.help import extract_eval_context_info, docstring_to_help
from gluetool.glue import PipelineStepModule
from gluetool.log import log_dict
from gluetool.utils import format_command_line, cached_property, normalize_path, render_template, \
    normalize_multistring_option

# Type annotations
# pylint: disable=unused-import,wrong-import-order
from typing import cast, Any, Callable, List, Optional, NoReturn, Union  # noqa
from types import FrameType  # noqa
from gluetool.glue import PipelineReturnType  # noqa


# Order is important, the later one overrides values from the former
DEFAULT_GLUETOOL_CONFIG_PATHS = [
    '/etc/gluetool.d/gluetool',
    normalize_path('~/.gluetool.d/gluetool'),
    normalize_path('./.gluetool.d/gluetool')
]

DEFAULT_HANDLED_SIGNALS = (signal.SIGUSR2,)


def handle_exc(func):
    # type: (Callable[..., Any]) -> Callable[..., Any]

    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        # type: (Gluetool, *Any, **Any) -> Any

        # pylint: disable=broad-except, protected-access

        try:
            return func(self, *args, **kwargs)

        except (SystemExit, KeyboardInterrupt, Exception):
            self._handle_failure(Failure(self.Glue.current_module if self.Glue else None, sys.exc_info()))

    return wrapped


class Gluetool(object):
    def __init__(self):
        # type: () -> None

        self.gluetool_config_paths = DEFAULT_GLUETOOL_CONFIG_PATHS

        self.sentry = None  # type: Optional[gluetool.sentry.Sentry]
        self.tracer = None  # type: Optional[gluetool.action.Tracer]

        # pylint: disable=invalid-name
        self.Glue = None  # type: Optional[gluetool.glue.Glue]

        self.argv = None  # type: Optional[List[str]]
        self.pipeline_desc = None  # type: Optional[List[gluetool.glue.PipelineStepModule]]

    @cached_property
    def _version(self):
        # type: () -> str

        # pylint: disable=no-self-use
        from .version import __version__

        return cast(str, __version__.strip())

    @cached_property
    def _command_name(self):
        # type: () -> str

        # pylint: disable=no-self-use
        return 'gluetool'

    def _deduce_pipeline_desc(self, argv, modules):
        # type: (List[Any], List[str]) -> List[gluetool.glue.PipelineStepModule]

        # pylint: disable=no-self-use

        """
        Split command-line arguments, left by ``gluetool``, into a pipeline description, splitting them
        by modules and their options.

        :param list argv: Remainder of :py:data:`sys.argv` after removing ``gluetool``'s own options.
        :param list(str) modules: List of known module names.
        :returns: Pipeline description in a form of a list of :py:class:`gluetool.glue.PipelineStepModule` instances.
        """

        alias_pattern = re.compile(r'^([a-z\-]*):([a-z\-]*)$', re.I)

        pipeline_desc = []
        step = None

        while argv:
            arg = argv.pop(0)

            # is the "arg" a module name? If so, add new step to the pipeline
            if arg in modules:
                step = PipelineStepModule(arg)
                pipeline_desc.append(step)
                continue

            # is the "arg" a module with an alias? If so, add a new step to the pipeline, and note the alias
            match = alias_pattern.match(arg)
            if match is not None:
                module, actual_module = match.groups()

                step = PipelineStepModule(module, actual_module=actual_module)
                pipeline_desc.append(step)
                continue

            if step is None:
                raise GlueError("Cannot parse module argument: '{}'".format(arg))

            step.argv.append(arg)

        return pipeline_desc

    def log_cmdline(self, argv, pipeline_desc):
        # type: (List[Any], List[gluetool.glue.PipelineStepModule]) -> None

        cmdline = [
            [sys.argv[0]] + argv
        ]

        for step in pipeline_desc:
            cmdline.append([step.module_designation] + step.argv)

        assert self.Glue is not None
        self.Glue.info('command-line:\n{}'.format(format_command_line(cmdline)))

    @cached_property
    def _exit_logger(self):
        # type: () -> Union[logging.Logger, gluetool.log.ContextAdapter]

        # pylint: disable=no-self-use
        """
        Return logger for use when finishing the ``gluetool`` pipeline.
        """

        # We want to use the current logger, if there's any set up.
        logger = gluetool.log.Logging.get_logger()  # type: Union[logging.Logger, gluetool.log.ContextAdapter]

        if logger:
            return logger

        # This may happen only when something went wrong during logger initialization
        # when Glue instance was created. Falling back to a very basic Logger seems
        # to be the best option here.

        logging.basicConfig(level=logging.DEBUG)
        logger = logging.getLogger()

        logger.warn('Cannot use custom logger, falling back to a default one')

        return logger

    def _quit(self, exit_status):
        # type: (int) -> NoReturn

        """
        Log exit status and quit.
        """

        logger = self._exit_logger

        if self.tracer:
            self.tracer.close(logger=logger)

        (logger.debug if exit_status == 0 else logger.error)('Exiting with status {}'.format(exit_status))

        sys.exit(exit_status)

    # pylint: disable=invalid-name
    def _handle_failure_core(self, failure):
        # type: (gluetool.glue.Failure) -> NoReturn

        logger = self._exit_logger

        assert failure.exc_info is not None
        assert failure.exc_info[1] is not None

        # Handle simple 'sys.exit(0)' - no exception happened
        if failure.exc_info[0] == SystemExit:
            assert isinstance(failure.exc_info[1], SystemExit)  # collapse type to SystemExit to make mypy happy

            if failure.exc_info[1].code == 0:
                self._quit(0)

        # soft errors are up to users to fix, no reason to kill pipeline
        exit_status = 0 if failure.soft is True else -1

        if failure.module:
            msg = "Pipeline reported an exception in module '{}': {}".format(
                failure.module.unique_name,
                failure.exc_info[1]
            )

        else:
            msg = "Pipeline reported an exception: {}".format(failure.exc_info[1])

        logger.error(msg, exc_info=failure.exc_info)

        # Submit what hasn't been submitted yet...
        if self.sentry and not failure.sentry_event_id:
            self.sentry.submit_exception(failure, logger=logger)

        self._quit(exit_status)

    # pylint: disable=invalid-name
    def _handle_failure(self, failure):
        # type: (gluetool.glue.Failure) -> NoReturn

        try:
            self._handle_failure_core(failure)

        # pylint: disable=broad-except
        except Exception:
            exc_info = sys.exc_info()

            # Don't trust anyone, the exception might have occured inside logging code, therefore
            # resorting to plain print.

            print >> sys.stderr
            print >> sys.stderr, '!!! While handling an exception, another one appeared !!!'
            print >> sys.stderr
            print >> sys.stderr, 'Will try to submit it to Sentry but giving up on everything else.'

            try:
                # pylint: disable=protected-access
                print >> sys.stderr, gluetool.log.LoggingFormatter._format_exception_chain(sys.exc_info())

                # Anyway, try to submit this exception to Sentry, but be prepared for failure in case the original
                # exception was raised right in Sentry-related code.
                if self.sentry is not None:
                    self.sentry.submit_exception(Failure(None, exc_info))

            # pylint: disable=broad-except
            except Exception:
                # tripple error \o/

                print >> sys.stderr
                print >> sys.stderr, '!!! While logging an exception, another exception appeared !!!'
                print >> sys.stderr, '    Giving up on everything...'
                print >> sys.stderr

                traceback.print_exc()

            # Don't use _quit() here - it might try to use complicated logger, and we don't trust
            # anythign at this point. Just die already.
            sys.exit(-1)

    @handle_exc
    def setup(self):
        # type: () -> None

        self.sentry = gluetool.sentry.Sentry()
        self.tracer = gluetool.action.Tracer()

        # Python installs SIGINT handler that translates signal to
        # a KeyboardInterrupt exception. It's so good we want to use
        # it for SIGTERM as well, just wrap the handler with some logging.
        orig_sigint_handler = signal.getsignal(signal.SIGINT)
        sigmap = {getattr(signal, name): name for name in [name for name in dir(signal) if name.startswith('SIG')]}

        def _signal_handler(signum, frame, handler=None, msg=None):
            # type: (int, FrameType, Optional[Callable[[int, FrameType], None]], Optional[str]) -> Any

            msg = msg or 'Signal {} received'.format(sigmap[signum])

            Glue.warn(msg)

            if handler is not None:
                return handler(signum, frame)

        def _sigusr1_handler(signum, frame):
            # type: (int, FrameType) -> None

            # pylint: disable=unused-argument

            raise GlueError('Pipeline timeout expired.')

        sigint_handler = functools.partial(_signal_handler,
                                           handler=orig_sigint_handler, msg='Interrupted by SIGINT (Ctrl+C?)')
        sigterm_handler = functools.partial(_signal_handler,
                                            handler=orig_sigint_handler, msg='Interrupted by SIGTERM')
        sigusr1_handler = functools.partial(_signal_handler, handler=_sigusr1_handler)

        # pylint: disable=invalid-name
        Glue = self.Glue = gluetool.Glue(tool=self, sentry=self.sentry)

        # Glue is initialized, we can install our logging handlers
        signal.signal(signal.SIGINT, sigint_handler)
        signal.signal(signal.SIGTERM, sigterm_handler)
        signal.signal(signal.SIGUSR1, sigusr1_handler)

        for signum in DEFAULT_HANDLED_SIGNALS:
            signal.signal(signum, _signal_handler)

        # process configuration
        Glue.parse_config(self.gluetool_config_paths)
        Glue.parse_args(sys.argv[1:])

        # store tool's configuration - everything till the start of "pipeline" (the first module)
        self.argv = sys.argv[1:len(sys.argv) - len(Glue.option('pipeline'))]

        if Glue.option('pid'):
            Glue.info('PID: {} PGID: {}'.format(os.getpid(), os.getpgrp()))

        # version
        if Glue.option('version'):
            Glue.info('{} {}'.format(self._command_name, self._version))
            sys.exit(0)

        GlueError.no_sentry_exceptions = normalize_multistring_option(Glue.option('no-sentry-exceptions'))

        Glue.modules = Glue.discover_modules()

    @handle_exc
    def check_options(self):
        # type: () -> None

        Glue = self.Glue
        assert Glue is not None

        self.pipeline_desc = self._deduce_pipeline_desc(Glue.option('pipeline'), Glue.modules.keys())
        log_dict(Glue.debug, 'pipeline description', self.pipeline_desc)

        # list modules
        groups = Glue.option('list-modules')
        if groups == [True]:
            sys.stdout.write('%s\n' % Glue.modules_descriptions())
            sys.exit(0)

        elif groups:
            sys.stdout.write('%s\n' % Glue.modules_descriptions(groups=groups))
            sys.exit(0)

        if Glue.option('list-shared'):
            functions = []  # type: List[List[str]]

            for mod_name in sorted(Glue.modules.iterkeys()):
                functions += [
                    [func_name, mod_name] for func_name in Glue.modules[mod_name].klass.shared_functions
                ]

            if functions:
                functions = sorted(functions, key=lambda row: row[0])
            else:
                functions = [['-- no shared functions available --', '']]

            sys.stdout.write("""Available shared functions

{}
            """.format(tabulate.tabulate(functions, ['Shared function', 'Module name'], tablefmt='simple')))

            sys.exit(0)

        if Glue.option('list-eval-context'):
            variables = []

            def _add_variables(source):
                # type: (gluetool.glue.Configurable) -> None

                info = extract_eval_context_info(source)

                for name, description in info.iteritems():
                    variables.append([
                        name, source.name, docstring_to_help(description, line_prefix='')
                    ])

            for mod_name in sorted(Glue.modules.iterkeys()):
                _add_variables(Glue.init_module(mod_name))

            _add_variables(Glue)

            if variables:
                variables = sorted(variables, key=lambda row: row[0])

            else:
                variables = [['-- no variables available --', '', '']]

            table = tabulate.tabulate(variables, ['Variable', 'Module name', 'Description'], tablefmt='simple')

            print render_template("""
{{ '** Variables available in eval context **' | style(fg='yellow') }}

{{ TABLE }}
            """, TABLE=table)

            sys.exit(0)

    @handle_exc
    def run_pipeline(self):
        # type: () -> PipelineReturnType

        Glue = self.Glue
        assert Glue is not None

        # no modules
        if not self.pipeline_desc:
            raise GlueError('No module specified, use -l to list available')

        # command-line info
        if Glue.option('info'):
            assert self.argv is not None

            self.log_cmdline(self.argv, self.pipeline_desc)

        # actually the execution loop is retries+1
        # there is always one execution
        retries = Glue.option('retries')

        for loop_number in range(retries + 1):
            # Print retry info
            if loop_number:
                Glue.warn('retrying execution (attempt #{} out of {})'.format(loop_number, retries))

            # Run the pipeline
            failure, destroy_failure = Glue.run_modules(self.pipeline_desc)

            if destroy_failure:
                return failure, destroy_failure

            if failure and isinstance(failure.exception, GlueRetryError):
                Glue.error(str(failure.exception))
                continue

            return failure, destroy_failure

        return None, None

    def main(self):
        # type: () -> None

        self.setup()
        self.check_options()

        failure, destroy_failure = self.run_pipeline()

        if destroy_failure:
            self._exit_logger.warn('Exception raised when destroying modules, overriding exit status')

            self._handle_failure(destroy_failure)

        if failure:
            self._handle_failure(failure)

        self._quit(0)


def main():
    # type: () -> None

    app = Gluetool()
    app.main()
