"""
Integration with `Sentry, error tracking software <https://sentry.io/welcome/>`_.

In theory, when an exception is raised and not handled, you can use this module
to submit it to your Sentry instance, and track errors produced by your application.

The actual integration is controlled by several environment variables. Each
can be unset, empty or set:

    * ``SENTRY_DSN`` - Client key, or DSN as called by Sentry docs.

      When unset or empty, the integration is disabled and no events are sent to the Sentry server.

    * ``SENTRY_BASE_URL`` - Optional: base URL of your project on the Sentry web server. The module
      can then use this value and construct URLs for reported events, which, when followed, will lead
      to the corresponding issue.

      When unset or empty, such URLs will not be available.

    * ``SENTRY_TAG_MAP`` - Optional: comma-separated mapping between environment variables and additional
      tags, which are attached to every reported event. E.g. ``username=USER,hostname=HOSTNAME`` will add
      2 tags, ``username`` and ``hostname``, setting their values according to the environment. Unset variables
      are silently ignored.

      When unset or empty, no additional tags are added to events.

The actual names of these variables can be changed when creating an instance of
:py:class:`gluetool.sentry.Sentry`.
"""

import os

import raven
from six import iteritems

import gluetool
import gluetool.log
import gluetool.utils

# Type annotations
# pylint: disable=unused-import, wrong-import-order
from typing import TYPE_CHECKING, Any, Dict, Optional, Union  # noqa

if TYPE_CHECKING:
    import logging  # noqa


class Sentry(object):
    """
    Provides unified interface to the Sentry client, Raven. Callers don't have to think
    whether the submitting is enabled or not, and we can add common tags and other bits
    we'd like to track for all events.

    :param str dsn_env_var: Name of environment variable setting Sentry DSN. Set to ``None``
        to explicitly disable Sentry integration.
    :param str base_url_env_var: Name of environment variable setting base URL of Sentry
        server. Setting to ``None`` will cause the per-event links will not be available
        to users of this class.
    :param str tags_map_env_var: Name of environment variable setting mapping between environment
        variables and additional tags. Set to ``None`` to disable adding these tags.
    """

    def __init__(self, dsn_env_var='SENTRY_DSN', base_url_env_var='SENTRY_BASE_URL', tags_map_env_var='SENTRY_TAG_MAP'):
        # type: (Optional[str], Optional[str], Optional[str]) -> None

        self._client = None
        self._base_url = None

        if base_url_env_var:
            self._base_url = os.environ.get(base_url_env_var, None)

        self._tag_map = {}  # type: Dict[str, str]

        if tags_map_env_var and os.environ.get(tags_map_env_var):
            try:
                for pair in os.environ[tags_map_env_var].split(','):
                    tag, env_var = pair.split('=')
                    self._tag_map[env_var.strip()] = tag.strip()

            except ValueError:
                raise gluetool.glue.GlueError(
                    'Cannot parse content of {} environment variable'.format(tags_map_env_var)
                )

        if not dsn_env_var:
            return

        dsn = os.environ.get(dsn_env_var, None)

        if not dsn:
            return

        self._client = raven.Client(dsn, install_logging_hook=True)

        # Enrich Sentry context with information that are important for us
        context = {}

        # env variables
        for name, value in iteritems(os.environ):
            context['env.{}'.format(name)] = value

        self._client.extra_context(context)

    @gluetool.utils.cached_property
    def enabled(self):
        # type: () -> bool

        return self._client is not None

    def enable_logging_breadcrumbs(self, logger):
        # type: (Union[logging.Logger, gluetool.log.ContextAdapter]) -> None

        if not self.enabled:
            return

        raven.breadcrumbs.register_special_log_handler(logger, lambda *args: False)

    def event_url(self, event_id, logger=None):
        # type: (str, Optional[gluetool.log.ContextAdapter]) -> Optional[str]

        """
        Return URL showing the event on the Sentry server. If ``event_id``
        is ``None`` or when base URL of the Sentry server was not set, ``None``
        is returned instead.

        :param str event_id: ID of the Sentry event, e.g. the one returned by
            :py:meth:`submit_exception` or :py:meth:`submit_warning`.
        :param gluetool.log.ContextAdapter logger: logger to use for logging.
        """

        if not self._base_url:
            return None

        return gluetool.utils.treat_url('{}/?query={}'.format(self._base_url, event_id), logger=logger)

    @staticmethod
    def log_issue(failure, logger=None):
        # type: (Optional[gluetool.glue.Failure], Optional[gluetool.log.ContextAdapter]) -> None

        """
        Nicely log issue and possibly its URL.

        :param gluetool.glue.Failure failure: ``Failure`` instance describing the exception.
        :param gluetool.log.ContextAdapter logger: logger to use for logging.
        """

        if not logger or not failure:
            return

        logger.error("Submitted as Sentry issue '{}'".format(failure.sentry_event_id))

        if failure.sentry_event_url:
            logger.error('See {} for details.'.format(failure.sentry_event_url))

    def _capture(self, event_type, logger=None, failure=None, **kwargs):
        # type: (str, Optional[gluetool.log.ContextAdapter], Optional[gluetool.glue.Failure], **Any) -> str

        """
        Prepare common arguments, and then submit the data to the Sentry server.
        """

        #
        # After this line, we CANNOT log with `sentry=True`!
        #
        # This function might have been called by logger's method, e.g. logger.warn(..., sentry=True),
        # if we'd log with sentry=True, we'd use the same logger, getting into possibly infinite recursion.
        #

        tags = kwargs.pop('tags', {})
        fingerprint = kwargs.pop('fingerprint', ['{{ default }}'])

        for env_var, tag in iteritems(self._tag_map):
            if env_var not in os.environ:
                continue

            tags[tag] = os.environ[env_var]

        if failure is not None:
            if 'soft-error' not in tags:
                tags['soft-error'] = failure.soft is True

            if 'exc_info' not in kwargs:
                kwargs['exc_info'] = failure.exc_info

            if hasattr(failure.exception, 'sentry_fingerprint'):
                fingerprint = failure.exception.sentry_fingerprint(fingerprint)  # type: ignore  # has no attribute

            if hasattr(failure.exception, 'sentry_tags'):
                tags = failure.exception.sentry_tags(tags)  # type: ignore  # has no attribute

        assert self._client is not None
        event_id = self._client.capture(event_type, tags=tags, fingerprint=fingerprint, **kwargs)  # type: str

        if failure is not None:
            failure.sentry_event_id = event_id
            failure.sentry_event_url = self.event_url(event_id, logger=logger)

        self.log_issue(failure, logger=logger)

        return event_id

    def submit_exception(self, failure, logger=None, **kwargs):
        # type: (gluetool.glue.Failure, Optional[gluetool.log.ContextAdapter], **Any) -> Optional[str]

        """
        Submits an exception to the Sentry server. Exceptions are usually submitted
        automagically, but sometimes you might feel the need to share arbitrary issues
        with the world.

        When submitting is not enabled, this method simply returns without sending anything anywhere.

        :param gluetool.glue.Failure failure: ``Failure`` instance describing the exception.
        :param dict kwargs: Additional arguments that will be passed to Sentry's ``captureException``
            method.
        """

        if not self.enabled:
            return None

        exc = failure.exception
        if exc and not getattr(exc, 'submit_to_sentry', True):
            if logger:
                logger.warning('As requested, exception {} not submitted to Sentry'.format(exc.__class__.__name__))

            return None

        return self._capture('raven.events.Exception', logger=logger, failure=failure, **kwargs)

    def submit_message(self, msg, logger=None, **kwargs):
        # type: (str, Optional[gluetool.log.ContextAdapter], **Any) -> Optional[str]

        """
        Submits a message to the Sentry server. You might feel the need to share arbitrary
        issues - e.g. warnings that are not serious enough to kill the pipeline - with the
        world.

        When submitting is not enabled, this method simply returns without sending anything anywhere.

        :param str msg: Message describing the issue.
        :param dict kwargs: additional arguments that will be passed to Sentry's ``captureMessage``
            method.
        """

        if not self.enabled:
            return None

        return self._capture('raven.events.Message', logger=logger, message=msg, **kwargs)
