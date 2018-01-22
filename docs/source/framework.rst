The ``gluetool`` framework
=======================

The ``gluetool`` framework is a command line centric modular Python framework. It makes possible to quickly write modules which can be executed on the command line in a sequential pipeline using the ``gluetool`` command.

Architecture
------------

The ``gluetool`` framework was created with various features in mind. These should provide an easy and straightforward way how to write, configure and execute modules.

Generic core
^^^^^^^^^^^^

The :doc:`core of the framework <gluetool.glue>` is completely decoupled from the modules and their specific functionality. It could be used for implementation of other tools.

Modules
^^^^^^^

See :doc:`How to: gluetool modules <howto-modules>` for more information about ``gluetool`` modules.

.. _configuration:

Configuration
^^^^^^^^^^^^^

The framework provides an easy way how to define configuration for the framework and the modules. The configuration files use the `ConfigParser <https://docs.python.org/2/library/configparser.html>`_ format. The configuration option key in the config file is the long option string as defined in the :py:attr:`options <gluetool.glue.Configurable.options>` dictionary.

The configuration directories are hardcoded to ``/etc/gluetool.d`` and ``~/.gluetool.d`` as defined in the :py:attr:`MODULE_CONFIG_PATHS <gluetool.glue.MODULE_CONFIG_PATHS>` variable. The configuration directory layout is:

  .. code-block:: bash

    ~/.gluetool.d/
    ├── gluetool                        - gluetool configuration
    └── config                     - per module configurations, one file per unique module name
        ├── <module_config_file>
        └── ...

  .. note::
    Note that this directory can be used for storing additional configuration files and directories according to the needs of the modules.

.. _gluetool_configuration:

Configuration of ``gluetool``
"""""""""""""""""""""""""""

The `gluetool` file defines the default options for the ``gluetool`` command itself. It can be used to define defaults for any of the supported options. The options need to be defined in the ``[default]`` section. You can view all the supported options of ``gluetool`` by running the command ``gluetool -h``. For example to enable the debug mode by default, we can use this configuration

  .. code-block:: bash

    $ cat ~/.gluetool.d/gluetool 
    [default]
    debug = True

.. _modules_configuration:

Modules Configuration
"""""""""""""""""""""

The `config` subdirectory can define a default configuration for each module. The configuration filename must be the same as the module's :py:attr:`name <gluetool.glue.Module.name>`. All options must be defined in the ``[default]`` section of the configuration file. You can view the module available options by running ``gluetool <module> -h``, e.g. ``gluetool jenkins -h`` for the :doc:`modules/jenkins` module.

Below is an example of configuration for the :doc:`modules/openstack` module.

  .. code-block:: bash

    $ cat ~/.gluetool.d/config/openstack
    [default]
    auth-url = https://our-instance.openstack.com:13000/v2.0
    username = batman
    password = YOUR_SECRET_PASSWORD
    project-name = gotham_ci
    ssh-key = ~/.ssh/id_rsa
    ssh-user = root
    key-name = id_rsa
    ip-pool-name = 10.8.240.0

.. _shared-functions:

Shared Functions
^^^^^^^^^^^^^^^^

Shared functions are the only way how modules can share data to the subsequent modules on the command-line pipeline. Each module can define a shared function via the :py:attr:`shared_functions <gluetool.glue.Module.shared_functions>` list. The available shared functions then can be easily called from any subsequent module being executed via the :py:meth:`shared <gluetool.glue.Module.shared>` method.

To list all shared functions provided by the available modules, use the gluetool's `-L` option

  .. code-block:: bash

    $ gluetool -L

Shared function names are unique, but different modules can expose the same shared function. This is useful for generalization, where for example different modules can provide a provision shared function returning a list of provisioned machines from different virtualization providers.

Shared functions can have arguments and they behave the same way as ordinary Python functions.

  .. note::

    The documentation of the shared function is generated automatically from the docstring of the method and displayed in the help of the module. As an example, see the help of the :doc:`koji <modules/koji>` module ``gluetool koji -h`` which provides the ``primary_task`` shared function.

Uniform Logging
^^^^^^^^^^^^^^^

The ``gluetool`` framework provides uniform logging. Modules can use their own ``info``, ``warn``, ``debug`` and ``verbose`` methods to log messages on different log levels. The log level can be changed using the ``-d/--debug`` and ``-v/--verbose`` options of the ``gluetool`` command.
