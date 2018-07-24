# pylint: disable=blacklisted-name

import pytest

from mock import MagicMock

import gluetool

from . import create_module


class DummyModule(gluetool.Module):
    """
    Dummy module, implementing necessary methods and attributes
    to pass through Glue's internal machinery.
    """

    name = 'Dummy module'

    options = {
        'foo': {},
        'bar': {}
    }


@pytest.fixture(name='module')
def fixture_module():
    return create_module(DummyModule)[1]


@pytest.fixture(name='configured_module')
def fixture_configured_module(module):
    module._config.update({
        'foo': 'some foo value',
        'bar': 19
    })

    return module


def test_sanity(module):
    assert module.option('foo') is None


def test_existing_option(configured_module):
    assert configured_module.option('foo') == 'some foo value'


def test_multiple_options(configured_module):
    foo, bar = configured_module.option('foo', 'bar')

    assert foo == 'some foo value'
    assert bar == 19


def test_no_option(module):
    with pytest.raises(gluetool.GlueError, match=r'Specify at least one option'):
        module.option()
