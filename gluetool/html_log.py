#!/usr/bin/env python

import argparse
import io
import json
import os
import re
import sys

import jinja2
from jinja2.utils import Markup

from gluetool.log import format_dict

# Type annotations
# pylint: disable=unused-import,wrong-import-order
from typing import cast, Any, Dict, Iterable, Optional, Union  # noqa


NOT_WHITESPACE = re.compile(r'[^\s]')


TEMPLATE = """
<html>
  <head>
    {# Inject assets - library styles and Javascript. File paths are relative to a path set via --assets option #}
    <style>{{ "semantic.min.css" | file_content }}</style>
    <style>{{ "prism.css" | file_content }}</style>
    <script>{{ "semantic.min.js" | file_content }}</script>
    <script>{{ "prism.js" | file_content }}</script>

    <style>
      body {
        font-size: medium;
      }

      .hidden {
        display: none
      }
    </style>

    <script>
      function toggle(entry) {
        document.getElementById(entry).classList.toggle('hidden');
      }
    </script>
  </head>

  <body>
    <table class="ui celled table">
    <tbody>
    {# First column: date/time; second column: log level (probably can disappear...); third column: messages, data... #}

    {% for entry in LOG %}
      {# Skip DEBUG entries, if we're not asked to include them #}
      {% if not ARGS.include_debug and entry['levelname'] == 'DEBUG' %}
        {% continue %}
      {% endif %}

      {# Save our loop control info - we're going to need it for different IDs later #}
      {% set entry_loop = loop %}

      {# Colorize row based on the log level #}
      <tr
        {% if entry['levelname'] == 'INFO' %}
          class="positive"
        {% elif entry['levelname'] == 'WARNING' %}
          class="warning"
        {% elif entry['levelname'] == 'ERROR' %}
          class="error"
        {% endif %}
      >
        <td>{{ entry['created'] }}</td>
        <td>{{ entry['levelname'] }}</td>
        <td>
          {# if `raw_intro` is set, the entry contains data we'd like to present in a structured way - blob, structure, XML #}
          {% if entry.raw_intro %}
            {{ entry.raw_intro | message }}:
          {% else %}
            {{ entry.message | message }}
          {% endif %}

          <div class="ui right floated buttons">
            {# If there's `caused_by`, we have to add a button to open "Exceptions" view #}
            {% if entry['caused_by'] %}
              <button class="ui button negative" onclick="toggle('entry-{{ loop.index0 }}-exceptions');">Exceptions</button>
            {% endif %}
          </div>
        </td>
      </tr>

      {# Display special data #}
      {% if entry.raw_intro %}
        <tr>
          <td colspan="2" />
          <td>
            {% if entry.raw_struct is not none %}
{{ entry.raw_struct | json }}
            {% endif %}
          </td>
        </tr>
      {% endif %}

      {# Exception info #}
      {% if entry.caused_by %}
      <tr id="entry-{{ loop.index0 }}-exceptions" class="hidden">
        <td /><td />
        <td>
          {% for exc_info in entry.caused_by %}
            {% set exception = exc_info.exception %}
            {% set traceback = exc_info.traceback %}
            {% set last_frame = traceback[-1] %}

            {% if loop.index0 == 0 %}
              <h3 class="ui header">Top-level exception:</h3>
            {% else %}
              <div class="ui divider"></div>

              <h3 class="ui header">Caused by:</h3>
            {% endif %}

            <div class="language-markup">
              At <code>{{ last_frame.filename | escape }}:{{ last_frame.lineno }}</code>, in <code>{{ last_frame.fnname | escape }}()</code>, <code>{{ exception.class | escape }}</code> was raised:
              <div class="ui error large message">{{ exception.message | escape }}</div>
            </div>

            {#Traceback #}
            <table class="ui celled table">
              <thead class="full-width">
                <tr>
                  <th colspan="2">Traceback</th>
                </tr>
              </thead>

              {% for frame in traceback %}
                <tr>
                  <td>
                    <!-- <i class="file alternate outline icon"></i> --><code>{{ frame.filename | escape }}:{{ frame.lineno }}</code>
                  </td>
                  <td>
                    <div class="ui right floated buttons">
                      <button class="ui icon blue button" onclick="navigator.clipboard.writeText('{{ frame.filename }}');">
                        <!-- <i class="copy outline icon"></i> -->
                        Copy
                      </button>
                      <button class="ui button brown" onclick="toggle('entry-{{ entry_loop.index0 }}-frame-locals-{{ loop.index0 }}');">
                        <!-- <i class="list icon"></i> -->
                        Locals
                      </button>
                      {% if frame.filename and frame.lineno and frame.filename != '<template>' %}
                        <button class="ui button brown" onclick="toggle('entry-{{ entry_loop.index0 }}-frame-snippet-{{ loop.index0 }}');">
                          <!-- <i class="code icon"></i> -->
                          Code
                        </button>
                      {% endif %}
                    </div>
                  </td>
                </tr>

                {# source snippet #}
                {% if frame.filename and frame.filename != '<template>' %}
                  <tr id="entry-{{ entry_loop.index0 }}-frame-snippet-{{ loop.index0 }}" class="hidden">
                    <td colspan="2">
                      {{ frame.filename | python_snippet(frame.lineno) }}
                    </td>
                  </tr>
                {% endif %}

                {# frame locals #}
                <tr id="entry-{{ entry_loop.index0 }}-frame-locals-{{ loop.index0 }}" class="hidden">
                  <td colspan="2">
                      <table class="ui table">
                        <thead>
                          <tr>
                            <th class="two wide">Name</th>
                            <th class="two wide">Type</th>
                            <th class="ten wide">Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {% for name, var in frame.locals.items() %}
                            <tr>
                              <td><code>{{ name }}</code></td>
                              <td><code>{{ var.type | escape }}</code></td>
                              <td>
{{ var.value | json }}
                              </td>
                            </tr>
                          {% endfor %}  {# for name, var in frame.locals.items() #}
                        </tbody>
                      </table>
                  </td>
                </tr>

              {% endfor %}  {# for frame in traceback #}
            </table>
          {% endfor %}  {# for entry in LOG #}
        </td>
      </tr>
      {% endif %}
      </tr>
    {% endfor %}
    </tbody>
    </table>
  <body>
</html>
"""


def decode_stacked(document, pos=0, decoder=json.JSONDecoder()):
    # type: (str, int, Any) -> Iterable[Dict[str, Any]]
    """
    Generator returning log entries - entries are not part of one large list of log entries,
    they are simply added to the log file one by one, therefore we cannot use :py:mod:`json`
    module to read them, it'd return just the first one.
    """

    while True:
        match = NOT_WHITESPACE.search(document, pos)

        if not match:
            return

        pos = match.start()

        obj, pos = decoder.raw_decode(document, pos)

        yield obj


def _code_filter(ctx, value, syntax, apply_format=False, line_numbers=False, line_start=None, line_highlight=None):
    # type: (Any, unicode, str, bool, bool, Optional[int], Optional[int]) -> Union[str, Markup]
    # pylint: disable=too-many-arguments
    """
    Generic filter to highlight the code. Emits tags and content to employ Prism to do the highlighting.

    :param ctx: render context governed by Jinja.
    :param value: text or actual data structure to highlight as code.
    :param str syntax: what syntax to use for highlighting, e.g. ``python``.
    :param bool apply_format: if set, ``format_dict`` is called to pretty-print the structure in ``value``.
    :param bool line_numbers: if set, lines in the output are prefixed with their numbers.
    :param int line_start: if set, it specifies how far from the beginning of the file (line 1) the code
        starts, and how much we have to fake the line counter before prefixing lines.
    :param int line_highlight: if set, line of this number would be highlighted.
    """

    if apply_format:
        value = format_dict(value)

    pre_attrs = []

    if line_numbers is True:
        pre_attrs.append('class="line-numbers"')

    if line_start is not None:
        pre_attrs.append('data-start="{}"'.format(line_start))

    if line_highlight is not None:
        pre_attrs.append('data-line="{}"'.format(line_highlight))

    intro = Markup('<pre {}><code class="language-{}">'.format(' '.join(pre_attrs), syntax))
    outro = Markup('</code></pre>\n')

    result = intro + Markup(value.replace('<', '&lt;').replace('>', '&gt;')) + outro

    if ctx.autoescape:
        return Markup(result)

    return result


def _snippet_filter(ctx, filepath, lineno, syntax, window=10):
    # type: (Any, str, int, str, int) -> Union[str, Markup]
    """
    Generic filter providing snippet of the code from a source file, including the highlight.

    :param ctx: render context governed by Jinja.
    :param str filepath: source file.
    :param int lineno: important line we want to highligh.
    :param str syntax: what syntax to use for highlighting, e.g. ``python``.
    :param int window: size of the "window" we cut from the file. It is actually a half of the window,
        we peek ``window`` lines up **and** down around ``lineno``.
    """

    with io.open(filepath) as f:
        lines = f.readlines()

    line_index = lineno - 1

    snippet = lines[max(line_index - window, 0):min(line_index + window, len(lines))]

    return _code_filter(ctx, u''.join(snippet), syntax,
                        line_numbers=True,
                        line_start=max(lineno - window, 1),
                        line_highlight=lineno)


@jinja2.contextfilter  # type: ignore
def file_content_filter(ctx, value):
    # type: (Any, str) -> Union[str, Markup]
    # pylint: disable=unused-argument
    """
    Return content of the given file. File path must be relative to an assets directory
    set by ``--assets`` option.

    :param ctx: render context governed by Jinja.
    :param str value: path to a file to include.
    """

    with io.open(os.path.join(ctx['ARGS'].assets, value), 'r') as f:
        return Markup(f.read())


@jinja2.evalcontextfilter  # type: ignore
def message_filter(ctx, value):
    # type: (Any, str) -> Union[str, Markup]
    """
    Return slightly escaped log message to make it keep its formatting in HTML.

    * spaces are replaced with non-breakable spaces (``&nbsp;``);
    * new-line characters are replaced with ``<br/>`` elements.

    :param ctx: render context governed by Jinja.
    :param str value: message to escape.
    """

    result = value.replace('\n', cast(str, Markup('<br/>\n'))).replace(' ', cast(str, Markup('&nbsp;')))

    if ctx.autoescape:
        return Markup(result)

    return result


@jinja2.evalcontextfilter  # type: ignore
def json_filter(ctx, value):
    # type: (Any, str) -> Union[str, Markup]
    """
    Return highlighted JSON code.

    :param ctx: render context governed by Jinja.
    :param str value: JSON snippet to highlight.
    """

    return _code_filter(ctx, value, 'json', apply_format=True)


# Python filter is not being used at this moment
#
# @jinja2.evalcontextfilter
# def python_filter(ctx, value, line_numbers=False, line_start=None):
#     return _code_filter(ctx, value, 'python', line_numbers=line_numbers, line_start=line_start)


@jinja2.evalcontextfilter  # type: ignore
def python_snippet_filter(ctx, filepath, lineno):
    # type: (Any, str, int) -> Union[str, Markup]
    """
    :param ctx: render context governed by Jinja.
    :param str filepath: source file.
    :param int lineno: line to highlight.
    """

    return _snippet_filter(ctx, filepath, lineno, 'python')


def log_entries(stream):
    # type: (Any) -> Any

    """
    Return generator of log entries.

    :param file stream: ``file``-like stream to read JSON input from.
    """

    return decode_stacked(stream.read())


def main():
    # type: () -> None

    # Install our custom filters
    jinja2.defaults.DEFAULT_FILTERS.update({
        'file_content': file_content_filter,
        'json': json_filter,
        'python_snippet': python_snippet_filter,
        'message': message_filter
    })

    parser = argparse.ArgumentParser(description='Generate HTML log from JSON log (gluetool --json-file ...)')
    parser.add_argument(
        '-a', '--assets',
        default=os.path.expandvars('$VIRTUAL_ENV/assets/html-log'),
        help='Path to the directory with HTML log assets (default: %(default)s).'
    )
    parser.add_argument(
        '-i', '--input',
        default='gluetool-debug.json',
        help='Input file (default: %(default)s).'
    )
    parser.add_argument(
        '-o', '--output',
        default='gluetool-debug.html',
        help='Output file (default: %(default)s).'
    )
    parser.add_argument(
        '-D', '--include-debug',
        default=False,
        action='store_true',
        help='Include entries with level DEBUG (default: %(default)s).'
    )

    args = parser.parse_args()

    # Input file - is it a file or stdin?
    if args.input == '-':
        entries = log_entries(sys.stdin)

    else:
        if not os.path.exists(args.input):
            print 'No such file "{}"'.format(args.input)
            sys.exit(1)

        with io.open(args.input, 'r') as f:
            entries = log_entries(f)

    # Output file - file or stdout?
    if args.output == '-':
        output_stream = sys.stdout

    else:
        output_stream = io.open(args.output, 'w')

    jinja_env = jinja2.Environment(extensions=['jinja2.ext.loopcontrols'])
    template = jinja_env.from_string(TEMPLATE)

    output_stream.write(cast(str, template.render(ARGS=args, LOG=entries)))
    output_stream.flush()


if __name__ == '__main__':
    main()
