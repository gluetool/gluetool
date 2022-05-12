Sentry integration
------------------

``gluetool`` integrates easily with `Sentry <https://sentry.io/>`_ platform, simplifying the collection of trouble issues, code crashes, warnings and other important events your deployed code produces. This integration is optional - it must be explicitly enabled - and transparent - it is not necessary to report common events, like exceptions.

When enabled, every unhandled exception is automatically reported to Sentry. Helpers for explicit reporting of handled exceptions and warnings are available, as well as the bare method for reporting arbitrary events.

.. _sentry-control:

Control
~~~~~~~

Sentry integration is controlled by environmental variables. It must be possible to configure itilable even before ``gluetool`` has a chance to process given options. To enable Sentry integration, one has to set at least ``SENTRY_DSN`` variable:

.. code-block:: bash

   export SENTRY_DSN="https://<key>:<secret>@sentry.io/<project>"

This variable tells Sentry-related code where it should report the events. Without this variable set, Sentry integration is disabled. All relevant functions still can be called but do not report any events to Sentry, since they don't know where to send their reports.

.. seealso::

   `About the DSN <https://docs.sentry.io/quickstart/#configure-the-dsn>`_
       for detaield information on Sentry DSN and their use.

   :py:mod:`gluetool.sentry module <gluetool.sentry>`
       for developer documentation.


Sentry tags & environment variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sentry allows attaching "tags" to reported events. To use environment variables as such tags, set ``SENTRY_TAG_MAP`` variable. It lists comma-separated pairs of names, tag and its source variable.

.. code-block:: bash

   export SENTRY_TAG_MAP="username=USER,hostname=HOSTNAME"

Should there be an event to report, integration code will attach 2 labels to it, ``username`` and ``hostname``, using environmen variables ``USER`` and ``HOSTNAME`` respectively as source of values.

.. seealso::

   `Tagging Events <https://docs.sentry.io/learn/context/#tagging-events>`_
       for detailed information on event tags.


Logging of submitted events
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Integration code is able to log every reported event. To enable this feature, simply set ``SENTRY_BASE_URL`` environment variable to URL of the project ``gluetool`` is reporting events to. While ``SENTRY_DSN`` controls the whole integration and has its meaning within Sentry server your ``gluetool`` runs report to, ``SENTRY_BASE_URL`` is used only in a cosmetic way and ``gluetool`` code adds ID of reported event to it. The resulting URL, if followed, should lead to your project and the relevant event.

.. raw:: html

   <script src="https://asciinema.org/a/170167.js" id="asciicast-170167" async></script>

As you can see, the exception, raised by ``gluetool`` when there were no command-line options telling it what to do, has been submitted to Sentry, and immediately logged, with ``ERROR`` loglevel.

.. seealso::

   :ref:`Sentry - Control <sentry-control>`
       for more information about Sentry integration.

Warnings
~~~~~~~~

By default, only unhandled exceptions are submitted to Sentry. it is however possible, among others, to submit warnings, e.g. in case when such warning is good to capture yet it is not necessary to raise an exception and kill the whole ``gluetool`` pipeline. For that case, ``warn`` logging method accepts ``sentry`` keword parameter, which, when set to ``True``, uses Sentry-related code to submit given message to the configured Sentry instance. It is also always logged like any other warning.

Example:

.. code-block:: python
   :emphasize-lines: 5

   from gluetool.log import Logging

   logger = Logging.create_logger()

   logger.warn('foo', sentry=True)


Output:

.. code-block:: console

   [17:16:50] [W] foo

.. todo::

   * video

.. seealso::

   :ref:`Object logging helpers <log-object-helpers>`
       for more information on logging methods.

   :py:func:`gluetool.log.warn_sentry`
       for developer documentation.

.. todo ::

   Features yet to describe:

   * all env variables are attached to events (breadcrumbs)
   * logging records are attached to events (breadcrumbs)
   * URL of every reported event available for examination by code
   * soft-error tag for failure.soft errors
   * raised exceptions can provide custom fingerprints and tags
   * submit_exception and submit_warning for explicit submissions
   * logger.warn(sentry=True)
