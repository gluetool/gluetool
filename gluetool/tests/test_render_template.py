# pylint: disable=blacklisted-name

import pytest

import gluetool
from gluetool.utils import render_template

import jinja2


TMPL_STR = """
This is a dummy string template: {foo}
"""

TMPL_JINJA2 = jinja2.Template("""
This is a dummy Jinja2 template: {{ bar }}
""")


def test_render_string():
    assert render_template(TMPL_STR, foo='baz') == 'This is a dummy string template: baz'


def test_render_jinja2():
    assert render_template(TMPL_JINJA2, bar='baz') == 'This is a dummy Jinja2 template: baz'


def test_unexpected_template_type():
    with pytest.raises(gluetool.GlueError, message="Unhandled template type <type 'unicode'>"):
        render_template(u'fake template')


def test_missing_variable_string():
    with pytest.raises(gluetool.GlueError):
        render_template(TMPL_STR)


def test_missing_variable_jinja2():
    assert render_template(TMPL_JINJA2) == 'This is a dummy Jinja2 template:'
