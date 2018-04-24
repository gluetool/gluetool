# pylint: disable=blacklisted-name

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

    def foo(self):
        pass


@pytest.fixture(name='glue')
def fixture_glue():
    return NonLoadingGlue()


@pytest.fixture(name='module')
def fixture_module():
    return create_module(DummyModule)[1]


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
