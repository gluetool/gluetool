# pylint: disable=blacklisted-name

import inspect
import pytest

from mock import MagicMock

import gluetool

from . import NonLoadingGlue, create_module


class DummyModule(gluetool.Module):
    """
    Dummy module, implementing necessary methods and attributes
    to pass through Glue's internal machinery.
    """

    name = 'Dummy module'
    shared_functions = ('foo',)

    def foo(self):
        pass


class BrokenModule(DummyModule):
    name = 'Broken module'

    def execute(self):
        raise Exception('bar')


@pytest.fixture(name='glue')
def fixture_glue():
    glue = NonLoadingGlue()

    # register our dummy module classes
    glue.modules['Dummy module'] = {
        'class': DummyModule,
        'description': DummyModule.__doc__,
        'group': 'none'
    }

    glue.modules['Broken module'] = {
        'class': BrokenModule,
        'description': BrokenModule.__doc__,
        'group': 'none'
    }

    return glue


@pytest.fixture(name='module')
def fixture_module():
    return create_module(DummyModule)[1]


def test_sanity(glue, module, monkeypatch):
    glue.run_modules([gluetool.glue.PipelineStep('Dummy module')])


def test_add_shared(glue):
    glue.run_modules([gluetool.glue.PipelineStep('Dummy module')])

    # foo should be registered as a shared function
    assert glue.has_shared('foo')

    # And it should be foo of our dummy module class, i.e. foo's im_class member, as reported by
    # inspect, should be the DummyModule class. So, filter value of im_class member into a separate
    # list, and DummyModule should be its first (and only) member.
    assert [
        member[1] for member in inspect.getmembers(glue.get_shared('foo'), inspect.isclass) if member[0] == 'im_class'
    ].index(DummyModule) == 0


def test_add_shared_on_error(glue):
    # The same as test_add_shared but this time module raises an exception. Its shared functions
    # should be added despite that.

    with pytest.raises(Exception, match=r'bar'):
        glue.run_modules([gluetool.glue.PipelineStep('Broken module')])

    assert glue.has_shared('foo')

    assert [
        member[1] for member in inspect.getmembers(glue.get_shared('foo'), inspect.isclass) if member[0] == 'im_class'
    ].index(BrokenModule) == 0
