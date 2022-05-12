Help
----

``gluetool`` tries hard to simplify writing of consistent and useful help for modules, their shared functions, options and, of course, a source code. Its markup syntax of choice is reStructured (reST), which is being used in all docstrings. `Sphinx <http://www.sphinx-doc.org/>`_ is then used to generate documentation from documents and source code.


Module help
~~~~~~~~~~~

Every module supports a command-line option ``-h`` or ``--help`` that prints information on module's usage on terminal. To provide as much information on module's "public API", several sources are taken into account when generating the overall help for the module. Use of reST syntaxt is supported by each of them, that should allow authors to highligh important bits or syntax.

module's docstring
    Developer should describe module's purpose, use cases, configuration files and their syntax. Bear in mind that this is the text an end user would read to find out how to use the module, how to configure it and what they should expect from it. Feel free to use reST to include code blocks, emphasize importat bits and so on.

module's options
    Every option module has should have its own help set, using ``help`` key. These texts are gathered.

module's shared functions
    If the module provides shared functions, their signatures and help texts are gathered.

module's evaluation context
    If the module provides an evaluation context, description for each of its variables is extracted.

All parts are put together, formatted properly, and printed out to terminal in response to ``--help`` option.

Example:

.. code-block:: python
   :emphasize-lines: 4,5,6,7,8,14,16,21,22,23,24,25,31,32,33

   from gluetool import Module

   class M(Module):
       """
       This module greets its user.

       See ``--whom`` option.
       """

       name = 'dummy-module'

       options = {
           'whom': {
               'help': 'Greet our caller, whose NAME we are told by this option.',
               'default': 'unknown being',
               'metavar': 'NAME'
           }
       }

       shared_functions = ('hello',)

       def hello(self, name):
           """
           Say "Hi!" to someone.

           :param str name: Name of entity we're supposed to greet.
           """

           self.info('Hi, {}!'.format(name))

       @property
       def eval_context(self):
           __content__ = {
               'NAME': 'Name of entity this module should greet.'
           }

           return {
               'NAME': self.option('whom')
           }

       def execute(self):
           self.hello(self.option('whom'))


.. todo::

   * run example with a ``gluetool`` supporting eval context help
   * ``seealso``:

     * module options
     * shared functions
     * shared functions help
     * eval context
     * help colors


----


.. todo::

   Features yet to describe:

   * modules, shared functions, etc. help strings generated from their docstrings
   * options help from their definitions in self.options
   * RST formatting supported and evaluated before printing
   * colorized to highlight RST
   * keeps track of terminal width, tries to fit in
