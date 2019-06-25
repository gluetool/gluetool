"""
Actions are pieces of workflow. Actions have a name and start/end time, and actions can be traced.

This module provides simple instrumentation to enable logging of actions, and - when client
libraries are installed - submission of actions to storages compatible with
<https://opentracing.io/docs/overview/>`_.

Actions - which are wrapping Open Tracing's _span_ objects - can form an acyclic graph - actions
can have a single parent, it is then possible to start with a "root" action (e.g. "running the pipeline")
from which are children actions spawned (e.g. "executing module") and these actions can become parents
to actions spawned deeper in modules, end so on and on, forming a nice overview of what the code did, how
long did it took, and what are the dependencies between actions, i.e. what subactions were necessary to
perform a particular action.

Each execution of Gluetool pipeline forms a _trace_, which consists of multiple _spans_. Each action
represents a single span, wrapping its properties and dependencies.

.. code-block:: python

   with Action('some label', parent=parent_action, tags={'foo': 'bar'}) as action:
      # do some work

      with Action('some subtask', parent=action):
          # e.g. fetching a webpage

      with Action('another subtask', parent=action):
          # e.g. validating page's source code

For the example above, you get a trace capturing dependencies between a prent task and its two children, how
long they spent doing their job, how it affected the parent. Instrument interesting pieces of your code,
e.g. interaction with remote services, and get an overview of your workflow on a level of "symbolical" actions.

When a supported tracing client is installed, spans created by actions actions are reported to the remote storage.

Supported clients:

    * https://github.com/jaegertracing/jaeger-client-python

To control behavior of tracing subsystem, you can use following environment variables:

    * ``GLUETOOL_TRACING_DISABLE`` - when set to anything, tracing won't be enabled even when a client
      is available.
    * ``GLUETOOL_TRACING_SERVICE_NAME`` - given string is used to name the trace produced by ``gluetool`` execution.
    * ``GLUETOOL_TRACING_REPORTING_HOST`` - given string represents a hostname where service, capturing
        traces, listens.
    * ``GLUETOOL_TRACING_REPORTING_PORT`` - given integer represents a port number where service, capturing
        traces, listens.
"""

import os
import threading
import time

from .log import Logging
from .result import Result

try:
    import jaeger_client as tracing_client

except ImportError:
    tracing_client = None

# Type annotations
# pylint: disable=unused-import, wrong-import-order
from typing import TYPE_CHECKING, cast, Any, Dict, Generator, Iterator, List, Optional, Union  # noqa

if TYPE_CHECKING:
    from .log import ContextAdapter  # noqa

TracingClientType = Any  # pylint: disable=invalid-name


TRACING_DISABLE_ENVVAR = 'GLUETOOL_TRACING_DISABLE'
TRACING_SERVICE_NAME_ENVVAR = 'GLUETOOL_TRACING_SERVICE_NAME'
TRACING_REPORTING_HOST_ENVVAR = 'GLUETOOL_TRACING_REPORTING_HOST'
TRACING_REPORTING_PORT_ENVVAR = 'GLUETOOL_TRACING_REPORTING_PORT'
TRACING_FLUSH_TIMEOUT_ENVVAR = 'GLUETOOL_TRACING_FLUSH_TIMEOUT'

DEFAULT_TRACING_SERVICE_NAME = 'gluetool'
DEFAULT_TRACING_REPORTING_HOST = '127.0.0.1'
DEFAULT_TRACING_REPORTING_PORT = 5775
DEFAULT_TRACING_FLUSH_TIMEOUT = 30


class Tracer(object):
    """
    Wrap tracking tracer instance.

    :param str service_name: name to apply to all traces produced by this tracer.
    :param ContextAdapter logger: logger to use for logging.
    :param str reporting_host: address to which tracer should submit traces.
    :param int reporting_port: port to which tracer should submit tracers.
    """

    # pylint: disable=too-few-public-methods

    TRACER = None  # type: Optional[TracingClientType]

    # pylint: disable=too-many-arguments
    def __init__(self, service_name=None, logger=None, reporting_host=None, reporting_port=None):
        # type: (Optional[str], Optional[ContextAdapter], Optional[str], Optional[int]) -> None

        if not tracing_client or os.getenv(TRACING_DISABLE_ENVVAR):
            return

        self.logger = logger or Logging.get_logger()

        if not service_name:
            service_name = os.getenv(TRACING_SERVICE_NAME_ENVVAR, default=DEFAULT_TRACING_SERVICE_NAME)

        if not reporting_host:
            reporting_host = os.getenv(TRACING_REPORTING_HOST_ENVVAR, default=DEFAULT_TRACING_REPORTING_HOST)

        if not reporting_port:
            reporting_port = int(os.getenv(TRACING_REPORTING_PORT_ENVVAR, default=DEFAULT_TRACING_REPORTING_PORT))

        config = tracing_client.Config(
            config={
                # Using `const` sampler - the same sampling decission for all spans,
                # and that decision is "record" (because `param == 1`).
                'sampler': {
                    'type': 'const',
                    'param': 1
                },
                'local_agent': {
                    'reporting_host': reporting_host,
                    'reporting_port': reporting_port
                },
                'logging': True
            },
            service_name=service_name,
            validate=True
        )

        Tracer.TRACER = config.initialize_tracer()

    def close(self, flush_timeout=None, logger=None):
        # type: (Optional[int], Optional[ContextAdapter]) -> None
        """
        Close the tracer - after this point, no spans won't be submitted to the remote service.

        :param int flush_timeout: how long to wait for flushing the pending tracing spans. If not set,
            environment variable ``{}`` is inspected. The default value is {} seconds.
        :param ContextAdapter logger: logger to use for logging.
        """.format(TRACING_FLUSH_TIMEOUT_ENVVAR, DEFAULT_TRACING_FLUSH_TIMEOUT)

        if not Tracer.TRACER:
            return

        logger = logger or self.logger

        logger.info('Flushing tracing data')

        # Make pylint happy about circular imports by not using global import.
        # pylint: disable=cyclic-import
        from .utils import wait

        if not flush_timeout:
            flush_timeout = int(os.getenv(TRACING_FLUSH_TIMEOUT_ENVVAR, default=DEFAULT_TRACING_FLUSH_TIMEOUT))

        # yield to IOLoop to flush the spans - https://github.com/jaegertracing/jaeger-client-python/issues/50
        time.sleep(2)

        future = Tracer.TRACER.close()

        def _check_flush():
            # type: () -> Result[bool, str]

            return Result.Ok(True) if future.done() else Result.Error('flush pending')

        wait('tracing flush', _check_flush, timeout=flush_timeout, tick=2, logger=logger)


class Action(object):
    """
    A piece of a workflow: it has a name, and starts and ends at some point of time. Represents an individual unit
    of work.

    :param str label: a human-readable string which concisely represents the work done by the ``Action``. The name
        should be the most general string that describes an interesting class of ``Action`` instances.
        I.e. ``fetch-url` is better than ``fetch-url-https://foo.com```.
    :param Action parent: parent ``Action`` - one action can spawn multiple additional "children" actions to
        achieve its goal, either explicitly or by using instrumented library code.
    :param dict tags: additional key/value tags of this action, e.g. ``url=https://foo.com``.
    :param ContextAdapter logger: logger to use for logging purposes.
    """

    # For each thread, we keep a LIFO of unfinished actions. The topmost one is considered to be
    # "current".
    #
    # Works as long as user keeps only a single "active" action in a thread - if one creates two actions,
    # side by side, the last one becomes the "current":
    #
    # A1, A2 = Action(), Action()
    #     ^ current action
    _thread_actions = threading.local()

    @staticmethod
    def _action_stack():
        # type: () -> List[Action]
        """
        Return current - or create an empty new one - list of unfinished actions of the current thread.
        """

        if not hasattr(Action._thread_actions, 'stack'):
            Action._thread_actions.stack = []

        return cast(
            List[Action],
            Action._thread_actions.stack
        )

    @staticmethod
    def _add_action(action):
        # type: (Action) -> None
        """
        Add action on top of the list of unfinished actions of the current thread.
        """

        Action._action_stack().append(action)

    @staticmethod
    def _drop_action(action):
        # type: (Action) -> None
        """
        Drop action from the list of unfinished actions of the current thread.
        """

        try:
            Action._action_stack().remove(action)

        except ValueError:
            # Avoid circullar imports (and make pylint silent)
            # pylint: disable=cyclic-import
            from .glue import GlueError

            raise GlueError('Cannot remove action {}, it is not active'.format(action))

    @staticmethod
    def current_action():
        # type: () -> Action
        """
        Return the top-most - "current" - unfinished action of the current thread.
        """

        stack = Action._action_stack()

        if not stack:
            raise RuntimeError('Action stack is empty')

        return stack[-1]

    @staticmethod
    def set_thread_root(action):
        # type: (Action) -> None
        """
        Initialize list of unfinished action of the current thread with a given transaction.

        When thread starts, its list is obviously empty, therefore :py:meth:`current_action`
        cannot return anything reasonable. But there probably was an action, e.g. the one in
        the main thread, which could serve as "current action" for this thread. This method
        inserts it into the threads list, as the first action.

        This is a combination of resetting the action stack followed by :py:meth:`_add_action`.
        Cannot be replaced by ``_add_action`` though - ``_add_action`` *adds* action to the
        existing stack, but this method promises to reset the stack: imagine re-using thread
        as a worker for multiple workflows, each workflow should start with a clean slate,
        with a different root - when work starts in the thread, it should call ``set_thread_root``
        to initialize its actions stack with an action, given by whoever started the work from
        the main thread.
        """

        # We shouldn't replace the list itself, only its content.
        Action._action_stack()[:] = [action]

    def __init__(self, label, parent=None, tags=None, logger=None):
        # type: (str, Optional[Action], Optional[Dict[Any, Any]], Optional[ContextAdapter]) -> None

        self.label = label
        self.logger = logger or Logging.get_logger()
        self.parent = parent

        self.tags = tags or {}

        if Tracer.TRACER:
            if parent:
                parent_span = parent.span

            else:
                parent_span = None

            self.span = Tracer.TRACER.start_span(label, child_of=parent_span, tags=tags)  # type: Any

        else:
            self.span = None

        Action._add_action(self)

        self.logger.debug("action '{}', child of '{}', with span '{}', starts".format(
            self.label,
            self.parent.label if self.parent else '<unknown parent>',
            self.span if self.span else '<unknown span>'
        ))

    def __repr__(self):
        # type: () -> str

        return 'Action({}, parent={})'.format(
            self.label,
            self.parent.label if self.parent else 'unknown'
        )

    def finish(self):
        # type: () -> None
        """
        Complete the action.
        """

        Action._drop_action(self)

        if self.span:
            self.span.finish()

        self.logger.debug("action '{}', child of '{}', with span '{}', finished".format(
            self.label,
            self.parent.label if self.parent else '<unknown parent>',
            self.span if self.span else '<unknown span>'
        ))

    def __enter__(self):
        # type: () -> Action

        return self

    def __exit__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None

        self.finish()

    def set_tag(self, name, value):
        # type: (str, Any) -> None

        self.tags[name] = value

        if self.span:
            self.span.set_tag(name, value)

    def set_tags(self, tags):
        # type: (Dict[str, Any]) -> None

        for name, value in tags.iteritems():
            self.set_tag(name, value)
