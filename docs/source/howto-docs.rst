How to: ``gluetool`` documentation
==================================

This text is a (hopefully complete) list of best practices, dos and don'ts and tips when it comes to writing
documentation of ``gluetool`` APIs, options and other documents. When writing - or reviewing - ``gluetool`` docs,
please adhere to these rules whenever possible.

  .. note::

    These rules are not cast in stone - when we find out some are standing in our way to the most readable and usable documentation, let's just discuss the change and change what must be changed.


RST
---

``gluetool`` uses `reStructuredText` for its docstrings and documentation. If you're not familiar with this markup
language, please see following links to get some idea:

* `RST primer <http://www.sphinx-doc.org/en/stable/rest.html>`_
* `Other helpful directives <http://www.sphinx-doc.org/en/stable/markup/index.html>`_
* `Referencing Python objects <http://www.sphinx-doc.org/en/stable/domains.html#cross-referencing-python-objects>`_

Also inspecting sources - and the resulting documentation - is a good way to find out how to do something, e.g. how
to use links to external documents.


How to generate HTML documentation locally
------------------------------------------

* Just run ansible playbook generate-docs.yml which can be found in the root directory of the project

  .. code-block:: bash

    /usr/bin/ansible-playbook generate-docs.yml

You documentation awaits you at ``docs/build/html/index.html``.


Write multi-line docstrings
---------------------------

  .. code-block:: python

    """
    Foo bar
    """

Most of the time, functions and classes take parameters, return values, etc. Unless there's a really good reason
against that, e.g. in the case of very simple helpers, multi-line docstring should be the goal, allowing for
detailed description of the documented API.


Every module must have a description
------------------------------------

Short, one or two sentences describing the purpose of the module.


Every shared function must be documented
----------------------------------------

Shared functions are **the** API of ``gluetool`` modules. Their docstrings are used to generate HTML docs
or command-line help, therefore it's crucial to document their usage.


Every module must be documented
-------------------------------

Longer, detailed description of module's goal, provided services, required resources and possible pitfalls.


Check whether the documentation is up-to-date
---------------------------------------------

Make sure the documentation describes the actual state of the affairs. E.g. developer could have changed semantics
of a command-line option, or added another one that changed a behavior slightly, and forgot to update its help
string.

  .. note::

    Outdated documentation is probably even worse than no documentation at all. It leads reader to false assumptions
    which lead to anger. Anger leads to hate. Hate leads to suffering. When revieweing documentation, please take
    special care of making sure it's up-to-date.


Default values of parameters
----------------------------

If the parameter is a keyword parameter, having its default value right in function signature, Sphinx will use this
information and add it to the output.

  .. code-block:: python

    def foo(bar=None):
        """
        ...
        :param str bar: if set, it's printed to ``stdout``.
        """

If the default value only means `unspecified value` and function replaces it internally with the actual default value
that cannot be declared in function signature (e.g. it's mutable object, or it's retreived from another API), then
it should be noted in parameter description:

  .. code-block:: python

    def foo(bar=None):
        """
        ...
        :param dict bar: if set, it's passed to Baz. Empty ``dict`` is used by default.
        """

        bar = bar or {}


Reference what can be referenced
--------------------------------

Hyperlinks are good. Hyperlinks are useful. Hyperlinks save lives. Sphinx makes it easy to reference Python stuff,
you can find more information `here <http://www.sphinx-doc.org/en/stable/domains.html#cross-referencing-python-objects>`_.

It is not necessary to reference types of parameters when documented by ``:param <type> name`` directive - Sphinx will
attempt to create correspondign link automagically.


Return values
-------------

Sphinx provides two directives for return value documentation:

* ``:returns:``
  * describe the return value, you can include its type if it fits naturally into your text
  * if you include type, you must reference it manually, Sphinx won't do it

* ``:rtype:``
  * type - and only a type - of the return value
  * creates a link to the type - it's not necessary to reference it with ``:py:...``

If you can fit return value type into your description of the return value, then use ``:returns:``. Most of the time
you probably can, that makes ``:rtype:`` a bit redundant but sometimes it can be useful.

  .. code-block:: python

    """
    ...
    :returns: :py:class:`gluetool.utils.ProcessOutput` instance whose attributes contain data returned by the process.
    """

Code and data examples
----------------------

If it'd be helpful, use an example, e.g. to show possible config file structure or to provide better idea about complex
return type. For this, ``.. code-block:: <language>`` can be very useful:

  This is what a config file may look like:

  .. code-block:: yaml

    ---
    foo:
      - bar
      - baz

  .. note::

    Be careful of the alignment of text bellow the ``code-block`` directive - it starts at the same column as the ``code-block`` string, with one empty line separating them.


Style
-----

* Use backquotes to mark literals

  * module names: ``guest-setup``, ``jenkins``, ...
  * commands: ``jenkins-jobs``, ``/bin/ls``, ...
  * when mentioning it, ``gluetool`` itself
  * basic Python types: ``dict``, ``list``, ...
  * command-line options: ``--help``, ``--pattern-map``, ...

* Sentences should start with capital letter and end with a full stop. This applies to parameter descriptions as well.

* Directives like ``:param`` can spread to multiple lines - in such case, indent the second and following lines by
  a single ``<TAB>``.
