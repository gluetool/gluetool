``gluetool`` modules
====================

All application specific functionality should be placed into modules. Modules are defined in one Python file and the module class must inherit from the class :py:class:`gluetool.glue.Module`.

Importing of modules
--------------------

The framework searches for modules in the module path(s). By default the module path is ``gluetool/modules`` in the project's root directory. You can override the module path with the ``--module-path`` option on the command line or via the :ref:`gluetool configuration <gluetool_configuration>`. The search algorithm tries to be clever about the import. It firstly parses the syntax tree of all ``*.py`` files it finds in the modules path(s) and imports it only if it finds a class definition which inherits from the :py:class:`gluetool.glue.Module` class.

  .. note::

    The module importing logic requires that you always inherit from the :py:class:`gluetool.glue.Modules` class or your module will not be imported. So for example, if you want to extend an existing module ``Koji`` to ``MyKoji``, you need to use:

    .. code-block:: python

        class MyKoji(Koji, Module):
        ...

Basic attributes
----------------

Name and description
^^^^^^^^^^^^^^^^^^^^

Module must define one or more unique names with the class variable :py:attr:`name <gluetool.glue.Module.name>`. This name identifies the module on the command line. For more information about modules providing multiple names see the section :ref:`multi-modules`.

Module should also define **description** with the class variable :py:attr:`description <gluetool.glue.Module.description>`, which will be displayed in the module listing, i.e. ``gluetool -l``.

Options
^^^^^^^

Modules can define an :py:attr:`options <gluetool.glue.Configurable.options>` dictionary, which defines their command line arguments and also the :ref:`module configuration <modules_configuration>` at once. Modules can use their `option method <gluetool.glue.Module.option>` to access the option value. The method returns ``None`` if option does not exist or it's value is not defined.

  .. note::
    The ``gluetool`` framework currently provides support only for named options/arguments. It is strongly advised to use named options only.

A module option value can be specified in 3 ways and in this precedence (later replaces the previously defined value):

  - value defined by the ``default`` key in the option's dictionary
  - value read from the `module configuration <modules_configuration>`
  - value read from the module's command line argument

The first two possibilities are used to define the option defaults. The command line argument value is used to override these if needed.

Modules can define a list of required options using the :py:attr:`required_options <gluetool.glue.Module.required_options>` class variable. The required options specify which options need to be specified when executing the module.

  .. note::
    It is advised to use :py:attr:`required_options <gluetool.glue.Module.required_options>` list instead of argparse's required option because the latter will only require the option specified on the command line, while the ``required_options`` list also takes into account values read from the `module configuration <modules_configuration>`.

Basic methods
-------------

Modules usually want to implement three main :py:class:`Module <gluetool.glue.Module>` methods - :py:meth:`sanity <gluetool.glue.Module.sanity>`, :py:meth:`execute <gluetool.glue.Module.execute>` and :py:meth:`destroy <gluetool.glue.Module.destroy>`.

The :py:meth:`sanity method <gluetool.glue.Module.sanity>` is called after parsing the command line options and the configuration files before any module is executed. The usual use-case for using the sanity method is to do additional actions before any module is executed.

The :py:meth:`execute method <gluetool.glue.Module.execute>` is the main entrypoint for the module. This method usually implements the module's main functionality.

The :py:meth:`destroy method <gluetool.glue.Module.destroy>` is called after the execution of all the modules specified in the pipeline. The destroy methods are called in the opposite direction as the modules are executed and the methods are called also if the execution of the pipeline did not finish (e.g. a module aborted the execution).

Shared functions
----------------

See the :ref:`framework's documentation <shared-functions>` for introduction into shared functions.

A module can define any number of shared functions by listing their name as a string in the :py:attr:`gluetool.glue.Module.shared_functions <shared_functions>` list. The shared functions are made available to other modules after the module has been executed. This makes it possible for the module to redefine the previously defined shared functions with their own version.

Here is an example of a simple module that exposes myapi shared function and takes one optional argument specifying the api version.

  .. code-block:: python

    import gluetool

    class MyApiModule(gluetool.Module):
        name = 'myapi'

        shared_functions = ['myapi']

        def myapi(self, api_version=1):
            return 'My Api version: {}'.format(api_version)

        def execute(self):
            self.info('hello world')

If you want to call a shared function from an other module, just use the :py:meth:`shared <gluetool.glue.Module.shared>` method and provide the name of the function as a string, for example in the above example, you would call:

  .. code-block:: python

    self.shared('myapi')

  .. note::
    ``shared()`` actually **calls** the shared function ``myapi`` from the MyApiModule in this case.

If you would like to pass additional arguments to the called shared function, just pass it as an argument to the shared function, e.g.:

  .. code-block:: python

     self.shared('myapi', api_version=2)

By design, more recently registered shared function replaces older ones of the same name, making them inaccessible. When calling shared function ``foo``, the one added by the module further in the pipeline gets called. Should you need to call the older version of ``foo``, the one replaced by the current instance, you can use the :py:meth:`overloaded_shared <gluetool.glue.Module.overloaded_shared>` method. It can be used to simulate a chain of ``super()`` calls in Python classes, giving "parent"-ish modules, listed sooner in the pipeline, a say.

For example, imagine two "publishing" modules - one sends messages to "alpha", the other one to "omega". Both "implement the interface" by providing a shared function with the same name, ``publish``, and both call older version of ``publish`` shared function when they're done with their own work, to give modules listed sooner in the pipeline a chance to "publish" as well. With this cooperation, it does not matter how many publishing modules you have in the pipeline or what's their order as long as each of them calls older version of ``publish``. User of such modules, ``publish-message``, then calls ``publish`` shared function, leaving the rest to them.

   .. code-block:: python

    import gluetool

    class PublishAlpha(gluetool.Module):
        name = 'publish-alpha'
        shared_functions = ['publish']

        def publish(self, message):
            self.info("publishing to alpha '{}'".format(message))
            self.overloaded_shared('publish', message)

   .. code-block:: python

    import gluetool

    class PublishOmega(gluetool.Module):
        name = 'publish-omega'
        shared_functions = ['publish']

        def publish(self, message):
            self.info("publishing to omega '{}'".format(message))
            self.overloaded_shared('publish', message)

   .. code-block:: python

    import gluetool

    class Publish(gluetool.Module):
        name = 'publish-message'
        options = {
            'message': {
                'help': 'Message to publish'
            }
        }
        required_options = ['message']

        def execute(self):
            self.shared('publish', self.option('message'))

Here is an example of the execution of the above modules:

   .. code-block:: shell

    $ gluetool publish-alpha publish-omega publish-message --message test
    [14:05:11] [+] [publish-omega] publishing to omega 'test'
    [14:05:11] [+] [publish-alpha] publishing to alpha 'test'

Examples
--------

A minimal module
^^^^^^^^^^^^^^^^
Adding a new gluetool module is very simple. This is a minimal module that just prints 'hello world':

  .. code-block:: python

    from gluetool import Module

    class MinimalModule(Module):
        name = 'example-minimal'
        description = 'A minimal module'

        def execute(self):
            self.info('hello world')

Drop this module into the module path and try to run the module via:

  .. code-block:: shell

    $ gluetool minimal


Advanced development techniques
-------------------------------

.. _multi-modules:

Modules with multiple names
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Modules can actually define multiple names under which they can be called on the command line. This is very useful, if you have the same plugin providing access to various instances of the same system, or a system that can be used using the same API. An example can be a postgresql module, that can be also used to connect to an `Teiid <http://teiid.jboss.org/>`_ instance. The benefit from having the same module appearing with different name is that you can define specific configuration for each module incarnation.

  .. code-block:: python

    from gluetool import Module

    class Posgresql(Module):
        name = ('postgresql', 'teiid')
        ....
