import bs4
import pytest

from gluetool.utils import new_xml_element


def test_sanity():
    assert new_xml_element('dummy-tag').name == 'dummy-tag'


def test_parentize():
    tag = 'dummy-kid'

    parent = new_xml_element('dummy-parent')

    assert tag not in [c.name for c in parent.children]

    el = new_xml_element(tag, _parent=parent)

    assert tag in [c.name for c in parent.children]
    assert el.parent is parent


def test_attrs():
    el = new_xml_element('dummy-element', foo='bar', baz=True)

    assert el['foo'] == 'bar'
    assert el['baz'] == True
