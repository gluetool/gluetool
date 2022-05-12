Colorized output
----------------

``gluetool`` uses awesome `colorama <https://pypi.python.org/pypi/colorama>`_ library to enhance many of its outputs with colors. This is done in a transparent way, when developer does not need to think about it, and user can control this feature with a single option.


Control
~~~~~~~

Color support is disabled by default, and can be turned on using ``--color`` option:

.. raw:: html

   <script src="https://asciinema.org/a/GhsulmjcL5FjXf5uA3XGE4sLi.js" id="asciicast-GhsulmjcL5FjXf5uA3XGE4sLi" async></script>


If ``colorama`` package is **not** installed, color support cannot be turned on. If user tries to do that, ``gluetool`` will emit a warning:

.. raw:: html

   <script src="https://asciinema.org/a/NhorAwOzY3NiBhlT1QSXxpkqL.js" id="asciicast-NhorAwOzY3NiBhlT1QSXxpkqL" async></script>

.. note::

   As of now, ``colorama`` is ``gluetool``'s hard requirement, therefore it should not be possible - at least out of the box - to run ``gluetool`` wihout having ``colorama`` installed. However, this may change in the future, leaving this support up to user decision.

To control this feature programatically, see :py:func:`gluetool.color.switch`.

.. todo::

   * ``seealso``:

     * how to specify options

Colorized logs
~~~~~~~~~~~~~~

Messages, logged on the terminal, are colorized based on their level:

.. raw:: html

   <script src="https://asciinema.org/a/170112.js" id="asciicast-170112" async></script>

``DEBUG`` log level inherits default text color of your terminal, while, for example, ``ERROR`` is highlighted by being red, and ``INFO`` level is printed with nice, comforting green.

.. todo::

   * ``seealso``:

     * logging

Colorized help
~~~~~~~~~~~~~~

``gluetool`` uses reStructuredText (reST) to document modules, shared functions, opitons and other things, and to make the help texts even more readable, formatting, provided by reST, is enhanced with colors, to help users orient and focus on important information.

.. raw:: html

   <script src="https://asciinema.org/a/170118.js" id="asciicast-170118" async></script>

.. todo::

   * ``seealso``:

     * generic help
     * module help
     * option help


.. _colors-in-templates:

Colors in templates
~~~~~~~~~~~~~~~~~~~

Color support is available for templates as well, via :py:func:`style <gluetool.color._style_colors>` filter.

Example:

.. code-block:: python
   :emphasize-lines: 6

   import gluetool

   gluetool.log.Logging.create_logger()
   gluetool.color.switch(True)

   print gluetool.utils.render_template('{{ "foo" | style(fg="red", bg="green") }}')

.. raw:: html

   <script src="https://asciinema.org/a/170123.js" id="asciicast-170123" async></script>

.. seealso::

   :ref:`rendering-templates`
       for more information about rendering templates with ``gluetool``.
