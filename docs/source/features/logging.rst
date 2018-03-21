Logging
-------

.. _log-early-debug:

Early debug messages
~~~~~~~~~~~~~~~~~~~~

Default logging level is set to ``INFO``. While debugging actions happening early in pipeline workflow, like module discovery and loading, it may be useful to enable more verbose logging. Unfortunatelly, this feature is controlled by a ``debug`` option, and this option will be taken into account too late to shed light on your problem. For that case, it is possible to tell ``gluetool`` to enable debug logging right from its beginning, by setting an environment variable ``GLUETOOL_DEBUG`` to any value:

.. code-block:: console

   export GLUETOOL_DEBUG=does-not-matter
   gluetool -l


.. raw:: html

   <script src="https://asciinema.org/a/173288.js" id="asciicast-173288" async></script>

As you can see, ``gluetool`` dumps much more verbose logging messages - about processing of options, config files and other stuff - on terminal with the variable set.

.. note::

   You can set the variable in any way supported by your shell, session or environment in general. The only important thing is that such variable must exist when ``gluetool`` starts.


.. _log-dict:

Logging of structured data
~~~~~~~~~~~~~~~~~~~~~~~~~~

To format structured data, like lists, tuples and dictionaries, for output, use :py:func:`gluetool.log.format_dict`

Example:

.. code-block:: python
   :emphasize-lines: 3

   import gluetool

   print gluetool.log.format_dict([1, 2, (3, 4)])


Output:

.. code-block:: console

   [
       1,
       2,
       [
           3,
           4,
       ]
   ]


.. raw:: html

   <script src="https://asciinema.org/a/170177.js" id="asciicast-170177" async></script>

To actually log structured data, the :py:func:`gluetool.log.log_dict` helper is a nice shortcut.


Example:

.. code-block:: python
   :emphasize-lines: 5

   import gluetool

   logger = gluetool.log.Logging.create_logger()

   gluetool.log.log_dict(logger.info, 'logging structured data', [1, 2, (3, 4)])


Output:

.. code-block:: console

   [14:43:03] [+] logging structured data:
   [
       1,
       2,
       [
           3,
           4
       ]
   ]


.. raw:: html

   <script src="https://asciinema.org/a/170178.js" id="asciicast-170178" async></script>

The first parameter of ``log_dict`` expects a callback which is given the formatted data to actually log them. It is therefore easy to use ``log_dict`` on every level of your code, e.g. in methods of your module, just give it proper callback, like ``self.info``.

.. todo::

   * ``seealso``:

     * logging helpers
     * connecting loggers

.. seealso::

   :ref:`log-blob`
       to find out how to log text blobs.

   :py:func:`gluetool.log.format_dict`, :py:func:`gluetool.log.log_dict`
       for developer documentation.

.. _log-blob:

Logging of unstructured blobs of text
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To format a "blob" of text, without any apparent structure other than new-lines and similar markings, use :py:func:`gluetool.log.format_blob`:

.. raw:: html

   <script src="https://asciinema.org/a/170180.js" id="asciicast-170180" async></script>

It will preserve text formatting over multiple lines, and it will add borders to allow easy separation of the blob from neighbouring text.

To actually log a blob of text, :py:func:`gluetool.log.log_blob` is a shortcut:

.. raw:: html

   <script src="https://asciinema.org/a/170182.js" id="asciicast-170182" async></script>

The first parameter of ``log_blob`` expects a callback which is given the formatted data to actually log them. It is therefore easy to use ``log_blob`` on every level of your code, e.g. in methods of your module, just give it proper callback, like ``self.info``.

.. todo::

   * ``seealso``:

     * logging helpers
     * connecting loggers

.. seealso::

   :ref:`log-dict`
       to find out how to log structured data.

   :py:func:`gluetool.log.format_blob`, :py:func:`gluetool.log.log_blob`
       for developer documentation.


.. _log-xml:

Logging of XML elements
~~~~~~~~~~~~~~~~~~~~~~~

To format an XML element, use :py:func:`gluetool.log.format_xml`:

.. raw:: html

   <script src="https://asciinema.org/a/172583.js" id="asciicast-172583" async></script>

It will indent nested elements, presenting the tree in a more readable form.

To actually log an XML element, :py:func:`gluetool.log.log_xml` is a shortcut:

.. raw:: html

   <script src="https://asciinema.org/a/172586.js" id="asciicast-172586" async></script>

The first parameter of ``log_xml`` expects a callback which is given the formatted data to actually log them. It is therefore easy to use ``log_xml`` on every level of your code, e.g. in methods of your module, just give it proper callback, like ``self.info``.

.. todo::

   * ``seealso``:

     * logging helpers
     * connecting loggers

.. seealso::

   :ref:`log-dict`
       to find out how to log structured data.

   :py:func:`gluetool.log.format_blob`, :py:func:`gluetool.log.log_blob`
       for developer documentation.


.. _log-object-helpers:

Object logging helpers
~~~~~~~~~~~~~~~~~~~~~~

.. note::

   When we talk about logger, we mean it as a description - an object that has logging methods we can use. It's not necessarilly the instance of :py:class:`logging.Logger` - in fact, given how logging part of ``gluetool`` works, it is most likely it's an instance of :py:class:`gluetool.logging.ContextAdapter`. But that is not important, the API - logging methods like ``info`` or ``error`` are available in such "logger" object, no matter what its class is.

Python's logging system provides a log function for each major log level, usually named by its corresponding level in lowercase, e.g. ``debug`` or ``info``. These are reachable as methods of a logger (or logging context adapter) instance. If you have a class which is given a logger, to ease access to these methods, it is possible to "connect" the logger and your class, making logger's ``debug`` & co. direct members of your objects, allowing you to call ``self.debug``, for example.

Example:

.. code-block:: python
   :emphasize-lines: 7,9

   from gluetool.log import Logging, ContextAdapter

   logger = ContextAdapter(Logging.create_logger())

   class Foo(object):
       def __init__(self, logger):
           logger.connect(self)

   Foo(logger).info('a message')

Output:

.. code-block:: console

   [10:01:15] [+] a message

.. .. raw:: html

..   <script src="https://asciinema.org/a/171104.js" id="asciicast-171104" async></script>

All standard logging method ``debug``, ``info``, ``warn``, ``error`` and ``exception`` are made available after connecting a logger.

.. todo::

   * ``seealso``:

     * context adapter

.. seealso::

   :py:meth:`logging.Logger.debug`
       for logging methods.


----


.. todo::

  Features yet to describe:

  * clear separation of logging records, making it visible where each of them starts and what is a log message and what a logged blob of command output
  * default log level controlled by env var
  * warn(sentry=True)
  * verbose, readable, formatted traceback logging
  * using context adapters to add "structure" to loged messages
  * colorized messages based on their level
  * optional "log everything" dump in a file
  * correct and readable logging of exception chains
