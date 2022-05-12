Core
----


.. _core-config-store:

Module and ``gluetool`` configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Configuration of ``gluetool`` and every module is gathered from different sources of different priorities, and merged into a single store, accessible by :py:meth:`option() <gluetool.glue.Configurable.option>` method. Configuration from later sources replaces values set by earlier sources, with lower priority. That way it is possible to combine multiple configuration files for a module, e.g. a generic site-wide configuration, with user-specific configuration overriding the global settings. Options specified on a command-line have the highest priority, overriding all configuration files.

Consider following example module - it has just a single option, ``whom``, whose value is logged in a form of greeting. The option has a default value, ``unknown being``:

.. code-block:: python
   :emphasize-lines: 7,11

   from gluetool import Module

   class M(Module):
       name = 'dummy-module'

       options = {
           'whom': {
              'default': 'unknown being'
           }
       }

       def execute(self):
           self.info('Hi, {}!'.format(self.option('whom')))

.. raw:: html

   <script src="https://asciinema.org/a/171492.js" id="asciicast-171492" async></script>

With a configuration file, ``~/.gluetool.d/config/dummy-module``, you can change the value of ``whom``:

.. code-block:: ini

   [default]
   whom = happz

.. raw:: html

   <script src="https://asciinema.org/a/171486.js" id="asciicast-171486" async></script>

As you can see, configuration file for ``dummy-module`` is loaded and :py:meth:`option() <glue.Configurable.option>` method returns the correct value, ``happz``.

Options specified on a command-line are merged into the store transparently, without any additional action necessary:

.. raw:: html

   <script src="https://asciinema.org/a/171487.js" id="asciicast-171487" async></script>

.. todo::

   * re-record video because of ``name`` => ``whom``
   * ``seealso``:

     * options definitions

.. seealso::

   :ref:`core-config-files`
       to see what configuration files are examined.

.. _core-config-files:

Configuration files
~~~~~~~~~~~~~~~~~~~

For every module - including ``gluetool`` itself as well - ``gluetool`` checks several possible sources of configuration, merging all information found into a single configuration store, which can be queried during runtime using :py:meth:`option() <gluetool.glue.Configurable.option>` method.

Configuration files follow simple INI format, with a single section called ``[default]``, containing all options:

.. code-block:: ini

   [default]
   option-foo = value bar

.. warning::

   Options can have short and long names (e.g. ``-v`` vs. ``--verbose``). Configuration files are using **only** the long option names to propagate their values to ``gluetool``. If you use a short name (e.g. ``v = yes``), such setting won't affect ``gluetool`` behavior!

These files are checked for ``gluetool`` configuration:

 * ``/etc/gluetool.d/gluetool``
 * ``~/.gluetool.d/gluetool``
 * ``./.gluetool.d/gluetool``
 * options specified on a command-line

These files are checked for module configuration:

 * ``/etc/gluetool.d/config/<module name>``
 * ``~/.gluetool.d/config/<module name>``
 * ``./.gluetool.d/config/<module name>``
 * options specified on a command-line

If you're using a tool derived from ``gluetool``, it may add its own set of directories, e.g. using its name insead of ``gluetool``, but lists mentioned above should be honored by such tool anyway, to stay compatible with the base ``gluetool``.

It is possible to change the list of directories, using ``--module-config-path`` option, the default list mentioned above is then replaced by directories provided by this option.

.. todo::

   * ``seealso``:

     * option definitions

.. seealso::

   :ref:`core-config-store`
       for more information on configuration handling.

   :ref:`core-module-aliases`
       for more information on module names and how to rename them


.. _core-module-aliases:

Module aliases
~~~~~~~~~~~~~~

Each module has a name, as set by its ``name`` class attribute, but sometimes it might be good to use the module under another name. Remember, the module configuration is loaded from files named just like the module, and if there's a way to "rename" module when used in different pipelines, user might use different configuration files for the same module.

Consider following example module - it has just a single option, ``whom``, whose value is logged in a form of greeting:

.. code-block:: python
   :emphasize-lines: 4

   from gluetool import Module

   class M(Module):
       name = 'dummy-module'

        options = {
            'whom': {}
        }

        def execute(self):
            self.info('Hi, {}!'.format(self.option('whom')))

With the following configuration, ``~/.gluetool.d/config/dummy-module``, it will greet your users in a more friendly fashion:

.. code-block:: ini

   [default]
   whom = handsome gluetool user

.. raw:: html

   <script src="https://asciinema.org/a/172536.js" id="asciicast-172536" async></script>

For some reason, you might wish to use the module in another pipeline, sharing the configuration between both pipelines, but you want to change the greeted entity. One option is to use a command-line option, which overrides configuration files but that would make one of your pipelines a bit exceptional, having some extra command-line stuff. Other way is to tell ``gluetool`` to use the module but give it a different name. Add the extra configuration file for your "renamed" module, ``~/.gluetool.d/config/customized-dummy-module``:

.. code-block:: ini

   [default]
   whom = beautiful

.. raw:: html

   <script src="https://asciinema.org/a/172537.js" id="asciicast-172537" async></script>

Module named ``customized-dummy-module:dummy-module`` does not exist but this form tells ``gluetool`` it should create an instance of ``dummy-module`` module, and name it ``customized-dummy-module``. This is **the** name used to find and load module's configuration.

You may combine aliases and original modules as much as you wish - ``gluetool`` will keep track of names and the actual modules, and it will load the correct configuration:

.. raw:: html

   <script src="https://asciinema.org/a/172540.js" id="asciicast-172540" async></script>

.. todo::

   * re-record video because of ``name`` => ``whom``


Evaluation context
~~~~~~~~~~~~~~~~~~

``gluetool`` and its modules rely heavily on separating code from configuration, offloading things to easily editable files instead of hard-coding them into module sources. Values in configuration files can often be seen as templates, which need a bit of "polishing" to fill in missing bits that depend on the actual state of a pipeline and resources it operates on. To let modules easily participate and use information encapsulated in other modules in the pipeline, ``gluetool`` uses concept called *evaluation context* - a module can provide a set of variables it thinks might be interesting to other modules. These variables are collected over all modules in the pipeline, and made available as a "context", mapping of variable names and their values, which is a form generaly understood by pretty much any functionality that evaluates things, like templating engines.

To provide evaluation context, module has to define a property named :py:meth:`eval_context <gluetool.glue.Configurable.eval_context>`. This property should return a mapping of variable names and their values.

For example:

.. code-block:: python
   :emphasize-lines: 8,10,14,17

   from gluetool import Module
   from gluetool.utils import render_template

   class M(Module):
       name = 'dummy-module'

       @property
       def eval_context(self):
           return {
               'FOO': id(self)
           }

       def execute(self):
           context = self.shared('eval_context')
           self.info('Known variables: {}'.format(', '.join(context.keys())))

           message = render_template('Absolutely useless ID of this module is {{ FOO }}', **context)

           self.info(message)

It provides an interesting information to other modules - named ``FOO`` - for use in templates and other forms of runtime evaluation. To get access to the global context, collected from all modules, shared function ``eval_context`` is called.

Expected output:

.. code-block:: console

   [12:48:41] [+] [dummy-module] Known variables: FOO, ENV
   [12:48:41] [+] [dummy-module] Absolutely useless ID of this module is 139695598692432

.. note::

   Modules are asked to provide their context in the same order they are listed in the pipeline, and their contexts are merged, after each query, into a single mapping. It is therefore easy to overwrite variables provided by modules that were queried earlier by simply providing the same variable with a different value.

.. note::

   It is a good practice to prefix names of provided variables, to make them module specific and avoid confusion when it comes to names that might be considered too generic. E.g. variable ``ID`` is probably way too universal - is it a user ID, or a task ID? Instead, ``USER_ID`` or ``ARTIFACT_OWNER_ID`` is much better.

.. todo::

   * ``seealso``:

     * rendering templates


Long and short option names
~~~~~~~~~~~~~~~~~~~~~~~~~~~

When specifying options on a command-line, each option can be set using its name: ``--foo`` for option named ``foo``. Historicaly, it is also common to use "short" variants of option names, using just a single character. For example, ``--help`` and ``-h`` control the same thing. By default, each option defined by a module is a "long" one, suitable for use in a ``--foo`` form. If developer wishes to enable short form as well, he can simply express this wish by using both variants when defining the option, grouping them in a tuple.

Consider following example module - it has just a single option, ``whom``, whose value is logged in a form of greeting. It is possible to use ``--whom`` or ``-w`` to control the value.

.. code-block:: python
   :emphasize-lines: 7

   from gluetool import Module

   class M(Module):
       name = 'dummy-module'

       options = {
           ('w', 'whom'): {}
       }

       def execute(self):
           self.info('Hi, {}!'.format(self.option('whom')))

.. raw:: html

   <script src="https://asciinema.org/a/173253.js" id="asciicast-173253" async></script>

.. note::

   Configuration files deal with "long" option names only. I.e. ``whom = handsome`` will be correctly propagated into module's configuration store while ``w = handsome`` won't.


----

.. todo::

  Features yet to describe:

  * system-level, user-level and local dir configs
  * configurable list of module paths (with default based on sys.prefix)
  * dry-run support
  * controled by core
  * module can check what level is set, and take corresponding action. core takes care of logging
  * exception hierarchy
  * hard vs soft errors
  * chaining supported
  * custom sentry fingerprint and tags
  * Failure class to pass by internally
  * processes config file, command line options
  * argparser to configure option
  * option groups
  * required options
  * note to print as a part of help
  * shared functions
  * overloaded shared
  * require_shared
  * module logging helpers
  * sanity => execute => destroy - pipeline flow
  * failure access
  * module discovery mechanism
