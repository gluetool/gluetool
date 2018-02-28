How to: ``gluetool`` tests
==========================

This text is a (hopefully complete) list of best practices, dos and don'ts and tips when it comes to writing
tests for ``gluetool`` APIs, modules and other code. When writing - or reviewing - ``gluetool`` tests, please
adhere to these rules whenever possible.

.. note::

   These rules are not cast in stone - when we find out some are standing in our way to the most readable
   and usable documentation, let's just discuss the change and change what must be changed.


py.test
-------

``gluetool`` uses ``py.test`` framework for its test and tox to automate the running of the tests. If you're not
familiar with these tools, please see following links to get some idea:

* `py.test <https://docs.pytest.org/en/latest/>`_
* `tox <https://tox.readthedocs.io/en/latest/>`_

Also inspecting existing tests and ``tox.ini`` is a good way to find out how to do something, e.g. add new coverage
for your module.


How to run tests?
-----------------

Static analysis is using coala in docker, so for full test, you need to have docker daemon running.

You can run all tests using ``tox``:

.. code-block:: bash

   tox -e py27

If you want to skip coala analysis so you don't need docker, you can run

.. code-block:: bash

   tox -e 'py-{unit-tests,static-analysis,doctest}'

Tox also accept additional options:

.. code-block:: bash

   python setup.py test -a "--option1 --option2=value"

   tox -e py27 -- --option1 --option2=value


How to see code coverage?
-------------------------

By default, coverage measurement is disabled. To enable it, pass following options to the test runner of your choice:

.. code-block:: bash

   --cov=gluetool --cov-report=html:coverage-report

With these options, coverage will be enabled and when test run finishes, the coverage report (in HTML) will be created
in ``coverage-report`` directory. Simply open ``coverage-report/index.html`` in your browser then.

.. note::

   Coverage data are stored in ``.coverage`` file - if you'd like to use ``coverage`` utility to create additional
   reports or filter the output to better suit your needs, feel free to do so, nothing stands in your way :)


Module tests should be in the same file
---------------------------------------

Tests dealing with a single module should be packed in the same file.


Test function tests one thing/code path
---------------------------------------

Avoid the temptation to put more different tests into a single test function. Test function should test a single
feature or a code path. If you're concerned about repeating setup/teardown code a lot, learn about fixtures bellow.


Use ``assert``
--------------

``py.test`` prefers to use ``assert`` keyword to actually test values, and it promotes its use by providing really
nice and helpful formatting of failures, with pointers to places where the actual values differ from expected ones.

Sometimes it's very useful to create a helper function that checks complex response, data or object state, using
multiple lower-level ``assert`` instances.


Use fixtures
------------

.. epigraph::

   The purpose of test fixtures is to provide a fixed baseline upon which tests can reliably and repeatedly execute.
   pytest fixtures offer dramatic improvements over the classic xUnit style of setup/teardown functions.

   -- py.test `documentation <https://docs.pytest.org/en/latest/fixture.html>`_

They don't lie, it's definitely worth the effort. Pretty much every test of a module's code begins with "get a fresh
instance of a module-under-test". You can call some function to create this instance, or you can use a fixture and
simply accept this instance as a argument of your test function. And so on.


.. code-block:: python

   # every test function gets its own instance of gluetool.glue and the module it's testing
   from . import create_module

   @pytest.fixture(name='module')
   def fixture_module():
       return create_module(gluetool.modules.helpers.ansible.Ansible)

   def test_sanity(module, tmpdir):
       glue, _ = module

       assert glue.has_shared('run_playbook') is True


Session fixtures belong to ``tests/conftest.py``.


Check exception messages with ``match``
---------------------------------------

Use :py:func:`pytest.raises` parameter ``match`` to assert exception messages whenever possible:

.. code-block:: python

   with pytest.raises(Exception, match=r'dummy exception'):
       foo()

Be aware that ``match`` value is actually a regular expression used to match exception's message, therefore
use Python's `raw strings <https://docs.python.org/2/reference/lexical_analysis.html#string-literals>`_, prefixed
with ``r``.


Don't be afraid of monkeypatching
---------------------------------

It helps a lot with failure injection, with observing whether your code calls other functions it's expected to call,
and other useful tricks. And all patches are undone when your test function returns.

.. code-block:: python

   # If OSEror pops up, run_command should raise GlueError and re-use message from the original exception
   def faulty_popen_enoent(*args, **kwargs):
       raise OSError(errno.ENOENT, '')

   monkeypatch.setattr(subprocess, 'Popen', faulty_popen_enoent)

   with pytest.raises(gluetool.GlueError, match=r"^Command '/bin/ls' not found$"):
       run_command(['/bin/ls'])


When your attempts lead to messy tests, cosider refactoring of the tested code
------------------------------------------------------------------------------

This can happen very often - you'd like to test a method which is way too complex, and the result is huge pile of
setup/teardown code, unreadable asserts and even more complicated ways to convince the tested function to take different
path, e.g. when it comes to injecting errors into its flow. In such case, consider refactoring the tested code - it's
possible it could be rewritten to more separate pieces of code (main function & several helpers) which could greatly
improve the list of options you have, and it may even lead to more readable code.


``MagicMock`` is very handy tool
--------------------------------

Don't be afraid to use ``MagicMock`` - its ``return_value`` and ``side_effect`` parameters can help a lot when it comes
to mocking mocking functions returning prepared values or raising exceptions. E.g.

.. code-block:: python

   monkeypatch.setattr(library, 'library_function', MagicMock(side_effect=Exception))

when ``library.library_function`` gets called, it will raise an exception. If you need to raise an exception
with specific arguments, pass a helper function as a side effect:

.. code-block:: python

   def throw(*args, **kwargs):
       # pylint: disable=unused-argument

       raise Exception('simply bad request')

   monkeypath.setattr(library, 'library_function', MagicMock(side_effect=throw))

Instead of mocking a whole function, use ``MagicMock``'s ``return_value``:

.. code-block:: python

   monkeypatch.setattr(foo, 'bar', MagicMock(return_value=some_known_object))

is way more readable than:

.. code-block:: python

   def foo():
      return some_known_object

   monkeypach.setattr(foo, 'bar', foo)

Should you need more action when it comes to returned value (computing it on the fly), patching with custom function
is absolutely acceptable.
