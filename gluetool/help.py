"""
Command-line ``--help`` helpers (muhaha!).

``gluetool`` uses docstrings to generate help for command-line options, modules, shared functions
and other stuff. To generate good looking and useful help texts a bit of work is required.
Add the Sphinx which we use to generate nice documentation of ``gluetool``'s API and structures,
with its directives, and it's even more work to make readable output. Therefore these helpers,
separated in their own file to keep things clean.
"""

import argparse
import functools
import inspect
import os
import sys
import textwrap

import docutils.core
import docutils.nodes
import docutils.parsers.rst
import docutils.writers
import sphinx.writers.text
import sphinx.locale


# Initialize Sphinx locale settings
sphinx.locale.init([os.path.split(sphinx.locale.__file__)], None)

sphinx.writers.text.MAXWIDTH = 120

DEFAULT_WIDTH = 80

SHARED_FUNCTION_HELP_TEMPLATE = """
  {signature}

{help}
"""

SHARED_FUNCTIONS_HELP_TEMPLATE = """
** Shared functions **

{functions}
"""


def _get_width(width):
    if width is not None:
        return width

    try:
        width = int(os.environ['COLUMNS'])

    except (KeyError, ValueError):
        width = DEFAULT_WIDTH

    return width


class LineWrapRawTextHelpFormatter(argparse.RawDescriptionHelpFormatter):
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


def rst2text(text):
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

    width = _get_width(width)

    # Remove leading whitespace
    trimmed = trim_docstring(docstring)

    # we're using Sphinx RST which doesn't look very nice - convert it to plain text then.
    processed = rst2text(trimmed)

    # For each line - which is actually a paragraph, given the text comes from RST - wrap it
    # to fit inside given line length (a bit shorter, there's a prefix for each line!).
    wrapped_lines = []
    wrap = functools.partial(textwrap.wrap, width=width - len(line_prefix), initial_indent=line_prefix,
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

    processed = rst2text(trimmed)

    # Merge all lines into a single line
    return ' '.join(processed.splitlines())


def function_help(func, name=None):
    """
    Uses function's signature and docstring to generate a plain text help describing
    the function.

    :param callable func: Function to generate help for.
    :param str name: If not set, ``func.__name__`` is used by default.
    :returns: Formatted help text.
    """

    name = name or func.__name__

    # construct function signature
    signature = inspect.getargspec(func)
    if signature.defaults is None:
        defaults = [None for _ in range(len(signature.args) - 1)]

    else:
        args, defaults = signature.args, signature.defaults
        defaults = [None for _ in range(len(args) - 1 - len(defaults))] + list(defaults)

    args = []
    for arg, default in zip(signature.args[1:], defaults):
        if isinstance(default, str):
            default = "'{}'".format(default)

        args.append('{}={}'.format(arg, default))

    signature = '{}({})'.format(name, ', '.join(args))

    template_args = {
        'signature': '{}({})'.format(name, ', '.join(args)),
        'help': docstring_to_help(func.__doc__) if func.__doc__ else 'No help provided :('
    }

    return SHARED_FUNCTION_HELP_TEMPLATE.format(**template_args)
