Welcome to gluetool's documentation!
====================================

Gluetool |version| (|release|)

The ``gluetool`` command-line tool is an automation tool constructing a sequential pipeline on the command-line. It is able to implement any sequential process when it's divided into :doc:`modules <modules>` with minimal interaction between them, gluing them together on the command-line to form a pipeline. It is implemented as an open :doc:`gluetool framework <framework>`.

The cool thing about having the pipeline on the command-line is that it can be easily copy-pasted to your local shell for debugging/development, and such pipeline can be easily customized by changing options of the modules when needed.

The tool optionally integrates with `Sentry.io <https://sentry.io>`_ error logging platform for reporting issues, very useful when running ``gluetool`` pipelines at larger scales.


Installation
------------

If you want to install ``gluetool`` on your machine, you have two options:

For just using ``gluetool``, you can install package from pip:

.. code-block:: bash

    pip install gluetool

If you want to change the code of ``gluetool`` and use your copy, follow our :doc:`DEVELOPMENT` readme in the project root folder.


Table of contents
-----------------

.. toctree::
   :maxdepth: 1

   framework 
   howto-modules
   howto-tests
   howto-docs
   DEVELOPMENT


``gluetool`` API
----------------

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
