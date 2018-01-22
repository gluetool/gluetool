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

-  system packages - it is either impossible or impractical to use their
   Python counterpart, or they are required to build a Python package
   required by ``gluetool``. In some cases, on recent Fedora (26+) for
   example, it's been shown for some packages their ``compat-*`` variant
   might be needed. See the optional ``Bootstrap system environment``
   step bellow.

Installation
------------

0. (optional) Bootstrap system environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Following steps are necessary to install requirements when installing
``gluetool`` on different distributions:

**RHEL 7.4**

.. code-block:: bash

    yum install -y krb5-devel libcurl-devel libxml2-devel openssl-devel python-devel
    curl "https://bootstrap.pypa.io/get-pip.py" -o "get-pip.py" && python get-pip.py && rm -f get-pip.py
    pip install -U setuptools
    pip install ansible virtualenv

**Fedora 26**

.. code-block:: bash

    dnf install -y ansible krb5-devel libselinux-python python2-virtualenv /usr/lib/rpm/redhat/redhat-hardened-cc1
    dnf install -y --allowerasing compat-openssl10-devel
    pip install -U setuptools

1. Create a virtual environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    virtualenv -p /usr/bin/python2.7 <virtualenv-dir>
    . <virtualenv-dir>/bin/activate

2. Clone ``gluetool`` repository - your working copy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    git clone github:<your username>/<your fork name>
    cd gluetool

3. Install ``gluetool``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    python setup.py develop

4. (optional) Activate Bash completion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    python bash_completion.py
    mv gluetool $VIRTUAL_ENV/bin/gluetool-bash-completition
    echo "source $VIRTUAL_ENV/bin/gluetool-bash-completition" >> $VIRTUAL_ENV/bin/activate

5. Re-activate virtualenv
~~~~~~~~~~~~~~~~~~~~~~~~~

Since step #1 your ``gluetool`` virtualenv is active, but ``gluetool``'s
installation made some changes to the ``activate`` script, therefore
it's necessary to re-activate the virtualenv before actually doing stuff
with ``gluetool``:

.. code-block:: bash

    deactivate
    . <virtualenv-dir>/bin/activate

6. Add configuration
~~~~~~~~~~~~~~~~~~~~~~

``gluetool`` looks for its configuration in ``~/.gluetool.d``. Add configuration
for the modules according to your preference.

Now every time you activate your new virtualenv, you should be able to
run ``gluetool``:

.. code-block:: bash

    gluetool -h
    usage: gluetool [opts] module1 [opts] [args] module2 ...

    optional arguments:
    ...

Test suites
-----------

The test suite is governed by ``tox`` and ``py.test``. Before running
the test suite, you have to install ``tox``:

.. code-block:: bash

    pip install tox

Tox can be easily executed by:

.. code-block:: bash

    tox

Tox also accepts additional options which are then passed to
``py.test``:

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
