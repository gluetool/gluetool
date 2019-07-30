# pylint: disable=blacklisted-name

import pytest

import gluetool
from gluetool.utils import render_template

import jinja2


TEMPLATE = """
This is a dummy template: {{ bar }}
"""

JINJA_TEMPLATE = jinja2.Template(TEMPLATE)


@pytest.mark.parametrize('template', [
    TEMPLATE,
    jinja2.Template(TEMPLATE)
])
def test_render(template):
    assert render_template(template, bar='baz') == 'This is a dummy template: baz'


def test_unexpected_template_type():
    with pytest.raises(gluetool.GlueError, message="Unhandled template type <type 'int'>"):
        render_template(17)


def test_missing_variable():
    assert render_template(TEMPLATE) == 'This is a dummy template:'
