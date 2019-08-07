"""
Command-line ``--help`` helpers (muhaha!).

``gluetool`` uses docstrings to generate help for command-line options, modules, shared functions
and other stuff. To generate good looking and useful help texts a bit of work is required.
Add the Sphinx which we use to generate nice documentation of ``gluetool``'s API and structures,
with its directives, and it's even more work to make readable output. Therefore these helpers,
separated in their own file to keep things clean.
"""

import argparse
import ast
import inspect
import os
import textwrap

import docutils.core
import docutils.nodes
import docutils.parsers.rst
import docutils.writers
import sphinx.writers.text
import sphinx.locale
import sphinx.util.nodes

import six
from six import PY2, ensure_str, iteritems

from .color import Colors
from .log import Logging

# Type annotations
# pylint: disable=unused-import, wrong-import-order
from typing import TYPE_CHECKING, cast, Any, Callable, Dict, List, Optional, Tuple, Union  # noqa

if TYPE_CHECKING:
    import gluetool  # noqa
    import gluetool.glue  # noqa


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


FUNCTIONS_HELP_TEMPLATE = """
{% for signature, body in FUNCTIONS %}
  {{ signature }}

{{ body }}
{% endfor %}
"""


EVAL_CONTEXT_HELP_TEMPLATE = """
{{ '** Evaluation context **' | style(fg='yellow') }}

{% for name, description in iteritems(CONTEXT) %}
  * {{ name | style(fg='blue') }}

{{ description | indent(4, true) }}
{% endfor %}
"""


# Semantic colorizers
# pylint: disable=invalid-name
def C_FUNCNAME(text):
    # type: (str) -> str

    return Colors.style(text, fg='blue', reset=True)


def C_ARGNAME(text):
    # type: (str) -> str

    return Colors.style(text, fg='blue', reset=True)


def C_LITERAL(text):
    # type: (str) -> str

    return Colors.style(text, fg='cyan', reset=True)


# Our custom TextTranslator which does the same as Sphinx' original but colorizes some of the text bits.
#
# We must save a reference to the original class because we must use it when calling parent's __init__,
# since we cannot use "sphinx.writers.text.TextTranslator" - when we try to call
# sphinx.writers.text.TextTranslator.__init__, it's already set to our custom class => recursion...

# pylint: disable=invalid-name
_original_TextTranslator = sphinx.writers.text.TextTranslator


# pylint: disable=abstract-method
class TextTranslator(sphinx.writers.text.TextTranslator):  # type: ignore  # no type info in TextTranslator
    # literals, ``foo``
    def visit_literal(self, node):
        # type: (Any) -> None

        self.add_text(Colors.style('', fg='cyan', reset=False))

    def depart_literal(self, node):
        # type: (Any) -> None

        self.add_text(Colors.style('', reset=True))

    # "fields" are used to represent (shared) function parameters
    def visit_field_name(self, node):
        # type: (Any) -> None

        _original_TextTranslator.visit_field_name(self, node)

        self.add_text(Colors.style('', fg='blue', reset=False))

    def depart_field_name(self, node):
        # type: (Any) -> None

        self.add_text(Colors.style('', reset=True))

        _original_TextTranslator.depart_field_name(self, node)


sphinx.writers.text.TextTranslator = TextTranslator


# Custom help formatter that let's us control line length
class LineWrapRawTextHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None

        if kwargs.get('width', None) is None:
            kwargs['width'] = CROP_WIDTH

        super(LineWrapRawTextHelpFormatter, self).__init__(*args, **kwargs)

    def _split_lines(self, text, width):  # type: ignore  # incompatible with super type because of unicode
        # type: (str, int) -> List[str]

        text = ensure_str(self._whitespace_matcher.sub(' ', ensure_str(text)).strip())

        return textwrap.wrap(text, width)


#
# Code to use Sphinx TextWriter & few our helpers to parse
# our docstring to a plain text.
#

def py_default_role(role, rawtext, text, lineno, inliner, options=None, content=None):
    # type: (Any, str, str, int, Any, Optional[Any], Optional[Any]) -> Tuple[Any, Any]

    # pylint: disable=unused-argument,too-many-arguments
    """
    Default handler we use for ``py:...`` roles, translates text to literal node.
    """

    return [docutils.nodes.literal(rawsource=rawtext, text='{}'.format(text))], []


# register default handler for roles we're interested in
for python_role in ('py:class', 'py:meth', 'py:mod'):
    docutils.parsers.rst.roles.register_canonical_role(python_role, py_default_role)


def doc_role_handler(role, rawtext, text, lineno, inliner, options=None, context=None):
    # type: (Any, str, str, int, Any, Optional[Any], Optional[Any]) -> Tuple[Any, Any]

    # pylint: disable=unused-argument,too-many-arguments
    """
    Format ``:doc:`` roles, used to reference another bits of documentation.
    """

    _, title, target = sphinx.util.nodes.split_explicit_title(text)

    if target and target[0] == '/':
        target = 'docs/source/{}.rst'.format(target[1:])

    return [docutils.nodes.literal(rawsource=text, text='{} (See {})'.format(title, target))], []


docutils.parsers.rst.roles.register_canonical_role('doc', doc_role_handler)


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
    # type: (str) -> str

    """
    Render given text, written with RST, as plain text.

    :param str text: string to render.
    :rtype: str
    :returns: plain text representation of ``text``.
    """

    return ensure_str(docutils.core.publish_string(text, writer=sphinx.writers.text.TextWriter(DummyTextBuilder)))


def trim_docstring(docstring):
    # type: (str) -> str

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
    indent = six.MAXSIZE
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))
    # Remove indentation (first line is special):
    trimmed = [lines[0].strip()]
    if indent < six.MAXSIZE:
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
    # type: (str, Optional[int], str) -> str

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
    wrapped_lines = []  # type: List[str]

    for line in processed.splitlines():
        if line:
            wrapped_lines += textwrap.wrap(
                line,
                width=width - len(line_prefix),
                initial_indent=line_prefix,
                subsequent_indent=line_prefix
            )

        else:
            # yeah, we could just append empty string but line_prefix could be any string, e.g. 'foo: '
            wrapped_lines.append(line_prefix)

    return '\n'.join(wrapped_lines)


def option_help(txt):
    # type: (str) -> str

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
    # type: (Callable[..., Any], Optional[str]) -> Tuple[str, str]

    """
    Uses function's signature and docstring to generate a plain text help describing
    the function.

    :param callable func: Function to generate help for.
    :param str name: If not set, ``func.__name__`` is used by default.
    :returns: ``(signature, body)`` pair.
    """

    name = name or func.__name__

    # construct function signature
    # with Python 3 use getfullargspec instead of getargspec
    if PY2:
        # pylint: disable=deprecated-method
        signature = inspect.getargspec(func)
    else:
        signature = inspect.getfullargspec(func)  # pylint: disable=no-member

    no_default = object()

    defaults = []  # type: List[Union[str, object]]

    # arguments that don't have default value are assigned our special value to let us tell the difference
    # between "no default" and "None is the default"
    if signature.defaults is None:
        defaults = [no_default for _ in range(len(signature.args) - 1)]

    else:
        defaults = [
            no_default for _ in range(len(signature.args) - 1 - len(signature.defaults))
        ] + list(signature.defaults)

    args = []
    for arg, default in zip(signature.args[1:], defaults):
        if default is no_default:
            args.append(C_ARGNAME(arg))

        else:
            if isinstance(default, six.string_types):
                default = "'{}'".format(default)

            args.append('{}={}'.format(C_ARGNAME(arg), C_LITERAL(cast(str, default))))

    return (
        # signature
        '{}({})'.format(C_FUNCNAME(name), ', '.join(args)),
        # body
        docstring_to_help(func.__doc__) if func.__doc__ else Colors.style('    No help provided :(', fg='red')
    )


def functions_help(functions):
    # type: (List[Tuple[str, Callable[..., Any]]]) -> str

    """
    Generate help for a set of functions.

    :param list(str, callable) functions: Functions to generate help for, passed as name
        and the corresponding callable pairs.
    :rtype: str
    :returns: Formatted help.
    """

    # pylint: disable=cyclic-import
    from .utils import render_template

    return render_template(
        FUNCTIONS_HELP_TEMPLATE,
        FUNCTIONS=[
            function_help(func, name=name)
            for name, func in functions
        ]
    )


def extract_eval_context_info(source, logger=None):
    # type: (gluetool.glue.Configurable, Optional[gluetool.log.ContextAdapter]) -> Dict[str, str]

    """
    Extract information of evaluation context content from the ``source`` - a module
    or any other object with ``eval_context`` property. The information we're looking
    for is represented by an assignment to special variable, ``__content__``, in the
    body of ``eval_context`` getter. ``__content__`` is expected to be assigned
    a dictionary, listing context variables (keys) and their descriptions (values).

    If it's not possible to find such information, or an exception is raised, the function
    returns an empty dictionary.

    :param gluetool.glue.Configurable source: object to extract information from.
    :rtype: dict(str, str)
    """

    logger = logger or Logging.get_logger()

    logger.debug("extract eval cotext info from '{}'".format(source.name))

    # Cannot do "source.eval_context" because we'd get the value of property, which
    # is usualy a dict. We cannot let it evaluate and return the value, therefore
    # we must get it via its parent class.
    eval_context = source.__class__.eval_context

    # this is not a cyclic import, yet pylint thinks so :/
    # pylint: disable=cyclic-import
    from .glue import Configurable

    # If eval context is the same as Configurable's - which is the original class for all modules
    # and even gluetool.glue.Glue - it means its inherited from Configurable, therefore
    # ``source`` does not have its own, and in that case we should return an empty dictionary,
    # saying "module does not provide any eval context, just the one inherited from the base class",
    # and that's empty anyway.
    if eval_context == Configurable.eval_context:
        logger.debug('eval context matches the original one, ignoring')
        return {}

    try:
        # get source code of the actual getter of the ``eval_context`` property
        getter_source = inspect.getsource(eval_context.fget)  # type: ignore  # the actual property does have `fget`

        # it's indented - trim it like a docstring
        getter_source_trimmed = trim_docstring(getter_source)

        # now, parse getter source, and create its AST
        tree = ast.parse(getter_source_trimmed)

        # find ``__content__ = { ...`` assignment inside the function
        # ``tree`` is the whole module, ``tree.body[0]`` is the function definition
        for node in tree.body[0].body:  # type: ignore  # if `body` is missing, we can handle it
            if not isinstance(node, ast.Assign):
                continue

            target = node.targets[0]

            if not isinstance(target, ast.Name) or target.id != '__content__':
                continue

            if not isinstance(node.value, ast.Dict):
                continue

            assign = node
            break

        else:
            # No "__content__ = {..." found? So be it, return empty info.
            logger.debug('eval context exists but does not describe its content')
            return {}

        # wrap this assignment into a dummy Module node, to create an execution unit with just a single
        # statement (__content__ assignment), so we could slip it to compile/eval.
        dummy_module = ast.Module([assign])

        # compile the module to an executable code
        code = compile(dummy_module, '', 'exec')

        # We prepare our "locals" mapping - when we eval our dummy module, its "__content__ = ..." will be executed
        # within a context of some globals/locals mappings. We give eval our custom locals mapping, which will
        # result in __content__ being created in it - and we can just pick it up from this mapping when eval
        # is done.
        module_locals = {}  # type: Dict[str, Any]

        # this should be reasonably safe, don't raise a warning then...
        # pylint: disable=eval-used
        eval(code, {}, module_locals)

        return {
            name: trim_docstring(description) for name, description in iteritems(module_locals['__content__'])
        }

    # pylint: disable=broad-except
    except Exception as exc:
        logger.warning("Cannot read eval context info from '{}': {}".format(source.name, exc))

        return {}


def eval_context_help(source):
    # type: (gluetool.glue.Configurable) -> str

    """
    Generate and format help for an evaluation context of a module. Looks for context content,
    and gives it a nice header, suitable for command-line help, applying formatting along the way.

    :param gluetool.glue.Configurable source: object whose eval context help we should format.
    :returns: Formatted help.
    """

    # pylint: disable=cyclic-import
    from .utils import render_template

    context_info = extract_eval_context_info(source)

    if not context_info:
        return ''

    context_content = {
        name: docstring_to_help(description, line_prefix='') for name, description in iteritems(context_info)
    }

    return render_template(EVAL_CONTEXT_HELP_TEMPLATE, CONTEXT=context_content)
