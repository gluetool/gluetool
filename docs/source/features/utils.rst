Utils
-----

.. _rendering-templates:

Rendering templates
~~~~~~~~~~~~~~~~~~~

``gluetool`` and its modules make heavy use of `Jinja2 <http://jinja.pocoo.org/docs/>`_ templates. To help with their processing, it provides :py:func:`gluetool.utils.render_template` helper which accepts both raw string templates and instances of :py:class:`jinja2.Template`, and renders it with given context variables. Added value is uniform logging of template and used variables.

Example:

.. code-block:: python
   :emphasize-lines: 5

   import gluetool

   gluetool.log.Logging.create_logger()

   print gluetool.utils.render_template('Say hi to {{ user }}', user='happz')

Output:

.. code-block:: console

   Say hi to happz                                                                                                  

.. raw:: html

   <script src="https://asciinema.org/a/170154.js" id="asciicast-170154" async></script>

.. seealso::

   `Jinja2 templates <http://jinja.pocoo.org/docs/>`_
       for information about this fast & modern templating engine.

   :py:func:`gluetool.utils.render_template`
       for developer documentation.

   :ref:`colors-in-templates`
       for using colors in templates


Normalize URL
~~~~~~~~~~~~~

URLs, comming from different systems, or created by joining their parts, might contain redundant bits, duplicities, multiple ``..`` entries, mix of uppercase and lowercase characters and similar stuff. Such URLs are not verry pretty. To "prettify" your URLs, use :py:func:`gluetool.utils.treat_url`:

For example:

.. code-block:: python

    from gluetool.log import Logging
    from gluetool.utils import treat_url

    print treat_url('HTTP://FoO.bAr.coM././foo/././../foo/index.html')

Output:

.. code-block:: console

   http://foo.bar.com/foo/index.html

.. raw:: html

   <script src="https://asciinema.org/a/172738.js" id="asciicast-172738" async></script>

----


.. todo::

  Features yet to describe:

  * `dict_update`
  * converting various command-line options to unified output
  * boolean switches via normalize_bool_option
  * multiple string values (--foo A,B --foo C => [A,B,C])
  * path - expanduser & abspath applied
  * multiple paths - like multiple string values, but normalized like above
  * "worker thread" class - give it a callable, it will return its return value, taking care of catching exceptions
  * running external apps via run_command
  * Bunch object for grouping arbitrary data into a single object, or warping dictionary as an object (d[key] => d.key)
  * cached_property decorator
  * formatted logging of arbitrary command-line - if you have a command-line to format, we have a function for that
  * fetch data from a given URL
  * load data from YAML or JSON file or string
  * write data structures as a YAML of JSON
  * pattern maps
  * waiting for things to finish
  * creating XML elements
  * checking whether external apps are available and runnable
