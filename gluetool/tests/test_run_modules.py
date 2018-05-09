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


"""
def test_core_add_shared(glue):
    module = MagicMock()
    func = MagicMock()

    # pylint: disable=protected-access
    glue._add_shared('dummy_func', module, func)

    assert glue.shared_functions['dummy_func'] == (module, func)


def test_add_shared(glue, monkeypatch):
    dummy_func = MagicMock()
    module = MagicMock(dummy_func=dummy_func)

    _add_shared = MagicMock()

    monkeypatch.setattr(glue, '_add_shared', _add_shared)

    glue.add_shared('dummy_func', module)

    _add_shared.assert_called_once_with('dummy_func', module, dummy_func)


def test_add_shared_missing(glue):
    module = MagicMock(spec=gluetool.Module)
    module.name = 'dummy_module'

    with pytest.raises(gluetool.GlueError, match=r"No such shared function 'dummy_func' of module 'dummy_module'"):
        glue.add_shared('dummy_func', module)


def test_del_shared(glue):
    glue.shared_functions['foo'] = None

    glue.del_shared('foo')


def test_del_shared_unknown(glue):
    glue.del_shared('foo')


def test_has_shared(glue):
    glue.shared_functions['foo'] = None

    assert glue.has_shared('foo') is True


def test_has_shared_unknown(glue):
    assert glue.has_shared('foo') is False


def test_shared(glue):
    glue.shared_functions['foo'] = (None, MagicMock(return_value=17))

    assert glue.shared('foo', 13, 11, 'bar', arg='baz') == 17
    glue.shared_functions['foo'][1].assert_called_once_with(13, 11, 'bar', arg='baz')


def test_shared_unknown(glue):
    assert glue.shared('foo', 13, 11, 'bar', arg='baz') is None


def test_module_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'shared', MagicMock(return_value=17))

    assert module.shared('foo', 11, 13, 'bar', arg='baz') == 17
    module.glue.shared.assert_called_once_with('foo', 11, 13, 'bar', arg='baz')


def test_module_add_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'add_shared', MagicMock())
    module.shared_functions = ('foo',)

    module.add_shared()

    module.glue.add_shared.assert_called_once_with('foo', module)


def test_module_del_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'del_shared', MagicMock())

    module.del_shared('foo')

    module.glue.del_shared.assert_called_once_with('foo')


def test_module_has_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'has_shared', MagicMock(return_value=17))

    assert module.has_shared('foo') == 17
    module.glue.has_shared.assert_called_once_with('foo')
"""
