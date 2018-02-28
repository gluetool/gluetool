Development
===========

Environment
-----------

Before moving on to the actual setup, there are few important notes:

-  **The only supported and (sort of tested) way of installation and
   using ``gluetool`` is a separate virtual environment!** It may be
   possible to install ``gluetool`` directly somewhere into your system
   but we don't recommend that, we don't use it that way, and we don't
   know what kind of hell you might run into. Please, stick with
   ``virtualenv``.

-  The tested distributions (as in "we're using these") are either
   recent Fedora, RHEL or CentOS. You could try to install ``gluetool``
   in a different environment - or even development trees of Fedora, for
   example - please, make notes about differences, and it'd be awesome
   if your first merge request could update this file :)

Requirements
------------

To begin digging into ``gluetool`` sources, there are few requirements:

-  ``virtualenv`` utility

-  ``ansible-playbook``

Installation
------------

1. Create a virtual environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    virtualenv -p /usr/bin/python2.7 <virtualenv-dir>
    . <virtualenv-dir>/bin/activate

2. Clone ``gluetool`` repository - your working copy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    git clone github:<your username>/<your fork name>
    cd gluetool

3. Install ``gluetool``
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    python setup.py develop

4. (optional) Activate Bash completion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   gluetool --module-path gluetool_modules/ bash-completion > gluetool-bash-completition
   mv gluetool-bash-completition $VIRTUAL_ENV/bin/gluetool-bash-completition
   echo "source $VIRTUAL_ENV/bin/gluetool-bash-completition" >> $VIRTUAL_ENV/bin/activate

To activate bash completion immediately, source the generated file. Otherwise, it'd start working next time you'd activate your virtualenv.

.. code-block:: bash

   . ./gluetool-bash-completition

5. Add configuration
~~~~~~~~~~~~~~~~~~~~~~

``gluetool`` looks for its configuration in a local directory (among others), in ``./.gluetool.d`` to be specific. Add
configuration for the modules according to your preference.

Now every time you activate your new virtualenv, you should be able to run ``gluetool``:

.. code-block:: bash

    gluetool -h
    usage: gluetool [opts] module1 [opts] [args] module2 ...

    optional arguments:
    ...

Test suites
-----------

The test suite is governed by ``tox`` and ``py.test``. Before running the test suite, you have to install ``tox``:

.. code-block:: bash

    pip install tox

Tox can be easily executed by:

.. code-block:: bash

    tox

Tox also accepts additional options which are then passed to ``py.test``:

.. code-block:: bash

    tox -- --cov=gluetool --cov-report=html:coverage-report

Tox creates (and caches) virtualenv for its test runs, and uses them for
running the tests. It integrates multiple different types of test (you
can see them by running ``tox -l``).

Documentation
-------------

Auto-generated documentation is located in ``docs/`` directory. To
update your local copy, run these commands:

.. code-block:: bash

    ansible-playbook ./generate-docs.yml

Then you can read generated docs by opening ``docs/build/html/index.html``.
