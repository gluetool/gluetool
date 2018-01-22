Welcome to gluetool's documentation!
====================================

Gluetool |version| (|release|)

The ``gluetool`` command line tool is an automation tool constructing a sequential pipeline on command line. It is able to implement any sequential process divided into :doc:`modules <howto-modules>` with minimal interaction, glued together on the command line. The ``gluetool`` uses the :doc:`gluetool command-line centric modular framework <framework>` for implementation. The framework does not directly implement any testing specific functionality and is generic. The tool optionally integrates with `Sentry.io <https://sentry.io>`_ error logging platform for reporting issues, very useful when running ``gluetool`` in big.

The cool thing about having the pipeline on command line is that it can be easily copy-pasted to a localhost shell for debugging/development or the pipeline can be easily customized if needed.

Installation
------------

If you want to install gluetool on your machine, you have two options:
For just using gluetool, you can install package from pip:

.. code-block:: bash

    pip install gluetool


If you want to change code of gluetool and use your copy, follow our :doc:`DEVELOPMENT` readme in the project root folder.

Table of contents
-----------------

.. toctree::
   :maxdepth: 1

   framework 
   modules
   howto-tests
   howto-docs
   DEVELOPMENT


``gluetool`` API
-------------

.. toctree::
   :maxdepth: 2

   gluetool.glue
   gluetool.help
   gluetool.log
   gluetool.proxy
   gluetool.tool
   gluetool.utils
   gluetool.version

   gluetool.tests


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
