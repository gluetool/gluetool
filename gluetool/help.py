"""
Command-line ``--help`` helpers (muhaha!).

``gluetool`` uses docstrings to generate help for command-line options, modules, shared functions
and other stuff. To generate good looking and useful help texts a bit of work is required.
Add the Sphinx which we use to generate nice documentation of ``gluetool``'s API and structures,
with its directives, and it's even more work to make readable output. Therefore these helpers,
separated in their own file to keep things clean.
"""

import argparse
import inspect
import os
import sys
import textwrap

from functools import partial

import docutils.core
import docutils.nodes
import docutils.parsers.rst
import docutils.writers
import jinja2
import sphinx.writers.text
import sphinx.locale

from .color import Colors


# Initialize Sphinx locale settings
sphinx.locale.init([os.path.split(sphinx.locale.__file__)], None)

# If not told otherwise, the default maximal length of lines is this many columns.
DEFAULT_WIDTH = 120

# Check what's the actual width of our terminal, or use a default if we're not sure.
try:
    WIDTH = int(os.environ['COLUMNS'])

except (KeyError, ValueError):
    WIDTH = DEFAULT_WIDTH

# Crop the maximal width to account for various explicit indents.
CROP_WIDTH = WIDTH - 10

# Tell Sphinx to render text into a slightly narrower space to account for some indenting
sphinx.writers.text.MAXWIDTH = CROP_WIDTH


# Semantic colorizers
# pylint: disable=invalid-name
def C_FUNCNAME(text):
    return Colors.style(text, fg='blue', reset=True)


def C_ARGNAME(text):
    return Colors.style(text, fg='blue', reset=True)


def C_LITERAL(text):
    return Colors.style(text, fg='cyan', reset=True)


# Our custom TextTranslator which does the same as Sphinx' original but colorizes some of the text bits.
#
# We must save a reference to the original class because we must use it when calling parent's __init__,
# since we cannot use "sphinx.writers.text.TextTranslator" - when we try to call
# sphinx.writers.text.TextTranslator.__init__, it's already set to our custom class => recursion...

# pylint: disable=invalid-name
_original_TextTranslator = sphinx.writers.text.TextTranslator


class TextTranslator(sphinx.writers.text.TextTranslator):
    # literals, ``foo``
    def visit_literal(self, node):
        self.add_text(Colors.style('', fg='cyan', reset=False))

    def depart_literal(self, node):
        self.add_text(Colors.style('', reset=True))

    # "fields" are used to represent (shared) function parameters
    def visit_field_name(self, node):
        _original_TextTranslator.visit_field_name(self, node)

        self.add_text(Colors.style('', fg='blue', reset=False))

    def depart_field_name(self, node):
        self.add_text(Colors.style('', reset=True))

        _original_TextTranslator.depart_field_name(self, node)


sphinx.writers.text.TextTranslator = TextTranslator


# Custom help formatter that let's us control line length
class LineWrapRawTextHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, *args, **kwargs):
        if kwargs.get('width', None) is None:
            kwargs['width'] = CROP_WIDTH

        super(LineWrapRawTextHelpFormatter, self).__init__(*args, **kwargs)

    def _split_lines(self, text, width):
        text = self._whitespace_matcher.sub(' ', text).strip()
        return textwrap.wrap(text, width)


#
# Code to use Sphinx TextWriter & few our helpers to parse
# our docstring to a plain text.
#

def py_default_role(role, rawtext, text, lineno, inliner, options=None, content=None):
    # pylint: disable=unused-argument,too-many-arguments
    """
    Default handler we use for ``py:...`` roles, translates text to literal node.
    """

    return [docutils.nodes.literal(rawsource=rawtext, text='{}'.format(text))], []


# register default handler for roles we're interested in
for python_role in ('py:class', 'py:meth', 'py:mod'):
    docutils.parsers.rst.roles.register_canonical_role(python_role, py_default_role)


class DummyTextBuilder:
    # pylint: disable=too-few-public-methods,old-style-class,no-init

    """
    Sphinx ``TextWriter`` (and other writers as well) requires an instance of ``Builder``
    class that brings configuration into the rendering process. The original ``TextBuilder``
    requires Sphinx `application` which brings a lot of other dependencies (e.g. source paths
    and similar stuff) which are impractical in our use case ("render short string to plain
    text"). Therefore this dummy class which just provides minimal configuration - ``TextWriter``
    requires nothing else from ``Builder`` instance.

    See ``sphinx/writers/text.py`` for the original implementation.
    """

    class DummyConfig:
        # pylint: disable=too-few-public-methods,old-style-class,no-init

        text_newlines = '\n'
        text_sectionchars = '*=-~"+`'

    config = DummyConfig
    translator_class = None


def rst_to_text(text):
    """
    Render given text, written with RST, as plain text.

    :param str text: string to render.
    :rtype: str
    :returns: plain text representation of ``text``.
    """

    return docutils.core.publish_string(text, writer=sphinx.writers.text.TextWriter(DummyTextBuilder))


def trim_docstring(docstring):
    """
    Quoting `PEP 257 <https://www.python.org/dev/peps/pep-0257/#handling-docstring-indentation>`:

    *Docstring processing tools will strip a uniform amount of indentation from
    the second and further lines of the docstring, equal to the minimum indentation
    of all non-blank lines after the first line. Any indentation in the first line
    of the docstring (i.e., up to the first newline) is insignificant and removed.
    Relative indentation of later lines in the docstring is retained. Blank lines
    should be removed from the beginning and end of the docstring.*

    Code bellow follows the quote.

    This method does exactly that, therefore we can keep properly aligned docstrings
    while still use them for reasonably formatted help texts.

    :param str docstring: raw docstring.
    :rtype: str
    :returns: docstring with lines stripped of leading whitespace.
    """

    if not docstring:
        return ''
    # Convert tabs to spaces (following the normal Python rules)
    # and split into a list of lines:
    lines = docstring.expandtabs().splitlines()
    # Determine minimum indentation (first line doesn't count):
    indent = sys.maxint
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))
    # Remove indentation (first line is special):
    trimmed = [lines[0].strip()]
    if indent < sys.maxint:
        for line in lines[1:]:
            trimmed.append(line[indent:].rstrip())
    # Strip off trailing and leading blank lines:
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    while trimmed and not trimmed[0]:
        trimmed.pop(0)
    # Return a single string:
    return '\n'.join(trimmed)


def docstring_to_help(docstring, width=None, line_prefix='    '):
    """
    Given docstring, process and render it as a plain text. This conversion function
    is used to generate nice and readable help strings used when printing help on
    command line.

    :param str docstring: raw docstring of Python object (function, method, module, etc.).
    :param int width: Maximal line width allowed.
    :param str line_prefix: prefix each line with this string (e.g. to indent it with few spaces or tabs).
    :returns: formatted docstring.
    """

    width = width or WIDTH

    # Remove leading whitespace
    trimmed = trim_docstring(docstring)

    # we're using Sphinx RST which doesn't look very nice - convert it to plain text then.
    processed = rst_to_text(trimmed)

    # For each line - which is actually a paragraph, given the text comes from RST - wrap it
    # to fit inside given line length (a bit shorter, there's a prefix for each line!).
    wrapped_lines = []
    wrap = partial(textwrap.wrap, width=width - len(line_prefix), initial_indent=line_prefix,
                   subsequent_indent=line_prefix)

    for line in processed.splitlines():
        if line:
            wrapped_lines += wrap(line)
        else:
            # yeah, we could just append empty string but line_prefix could be any string, e.g. 'foo: '
            wrapped_lines.append(line_prefix)

    return '\n'.join(wrapped_lines)


def option_help(txt):
    """
    Given option help text, format it to be more suitable for command-line help.
    Options can provide a single line of text, or mutiple lines (using triple
    quotes and docstring-like indentation).

    :param str txt: Raw option help text.
    :returns: Formatted option help text.
    """

    # Remove leading whitespace - this won't hurt anyone, and helps docstring-like texts
    trimmed = trim_docstring(txt)

    processed = rst_to_text(trimmed)

    # Merge all lines into a single line
    return ' '.join(processed.splitlines())


def function_help(func, name=None):
    """
    Uses function's signature and docstring to generate a plain text help describing
    the function.

    :param callable func: Function to generate help for.
    :param str name: If not set, ``func.__name__`` is used by default.
    :returns: ``(signature, body)`` pair.
    """

    name = name or func.__name__

    # construct function signature
    signature = inspect.getargspec(func)
    no_default = object()

    # arguments that don't have default value are assigned our special value to let us tell the difference
    # between "no default" and "None is the default"
    if signature.defaults is None:
        defaults = [no_default for _ in range(len(signature.args) - 1)]

    else:
        args, defaults = signature.args, signature.defaults
        defaults = [no_default for _ in range(len(args) - 1 - len(defaults))] + list(defaults)

    args = []
    for arg, default in zip(signature.args[1:], defaults):
        if default is no_default:
            args.append(C_ARGNAME(arg))

        else:
            if isinstance(default, str):
                default = "'{}'".format(default)

            args.append('{}={}'.format(C_ARGNAME(arg), C_LITERAL(default)))

    return (
        # signature
        '{}({})'.format(C_FUNCNAME(name), ', '.join(args)),
        # body
        docstring_to_help(func.__doc__) if func.__doc__ else Colors.style('    No help provided :(', fg='red')
    )


def functions_help(functions):
    """
    Generate help for a set of functions.

    :param list(str, callable) functions: Functions to generate help for, passed as name
        and the corresponding callable pairs.
    :rtype: str
    :returns: Formatted help.
    """

    return jinja2.Template(trim_docstring("""
    {% for signature, body in FUNCTIONS %}
      {{ signature }}

    {{ body }}
    {% endfor %}
    """)).render(FUNCTIONS=[function_help(func, name=name) for name, func in functions])
