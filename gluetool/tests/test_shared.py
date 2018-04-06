# pylint: disable=blacklisted-name

import logging

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

    @gluetool.shared_function
    def foo(self):
        pass


@pytest.fixture(name='glue')
def fixture_glue():
    return NonLoadingGlue()


@pytest.fixture(name='module')
def fixture_module():
    return create_module(DummyModule)[1]


# Shared functions discovery

# children of all these classes should support shared functions discovery
_FIND_SHARED_FUNCTIONS_PARAMS = [
    (
        gluetool.Module,
        (fixture_glue(), 'dummy'),
        None
    ),
    (
        gluetool.Glue,
        tuple(),
        {
            'eval_context': '_eval_context'
        }
    )
]

@pytest.mark.parametrize('parent, init_args, additional_shared_functions', _FIND_SHARED_FUNCTIONS_PARAMS)
def test_shared_functions(parent, init_args, additional_shared_functions, glue):
    class Container(parent):
        shared_functions = ('old_style',)

        def old_style(self):
            pass

        @gluetool.shared_function
        def foo(self):
            pass

        @gluetool.shared_function(name='baz')
        def bar(self):
            pass

    container = Container(*init_args)

    expected_shared_functions = {
        'foo': container.foo,
        'baz': container.bar,
        'old_style': container.old_style
    }

    if additional_shared_functions:
        expected_shared_functions.update({
            name: getattr(container, member) for name, member in additional_shared_functions.iteritems()
        })

    assert container._shared_functions() == expected_shared_functions

    assert container.foo._gluetool_shared_function is True
    assert container.foo._gluetool_shared_name == 'foo'
    assert container.bar._gluetool_shared_function is True
    assert container.bar._gluetool_shared_name == 'baz'


@pytest.mark.parametrize('parent, init_args, additional_shared_functions', _FIND_SHARED_FUNCTIONS_PARAMS)
def test_shared_functions_missing(parent, init_args, additional_shared_functions, glue):
    class Container(parent):
        shared_functions = ('foo',)

        def bar(self):
            pass

    # Glue raises the exception when being instantiated, while Module when _shared_functions is called.
    # Therefore the ``if`` - we cannot use ``container = Container()`` and use ``container.unique_name`` in
    # the ``match``, because with ``parent`` being ``Glue``, we cannot instantiate container without
    # detecting missing shared function.

    if parent is gluetool.Glue:
        with pytest.raises(gluetool.GlueError, match=r"No such shared function 'foo' of module 'gluetool core'"):
            Container(*init_args)._shared_functions()

    else:
        with pytest.raises(gluetool.GlueError, match=r"No such shared function 'foo' of module 'dummy'"):
            Container(*init_args)._shared_functions()


def test_glue_register_shared(glue):
    module = MagicMock()
    func = MagicMock()

    glue.register_shared('dummy_func', module, func)

    # pylint: disable=protected-access
    assert glue._shared_functions_registry['dummy_func'] == (module, func)


def test_register_shared(glue, monkeypatch):
    class Module(gluetool.Module):
        @gluetool.shared_function
        def foo(self):
            pass

    monkeypatch.setattr(glue, 'register_shared', MagicMock())

    module = Module(glue, 'dummy')
    module.register_shared()

    glue.register_shared.assert_called_once_with('foo', module, module.foo)


def test_glue_unregister_shared(glue):
    glue._shared_functions_registry['foo'] = None
    assert 'foo' in glue._shared_functions_registry

    glue.unregister_shared('foo')

    assert 'foo' not in glue._shared_functions_registry


def test_unregister_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'unregister_shared', MagicMock())

    assert 'foo' in module.glue._shared_functions_registry

    module.unregister_shared()

    module.glue.unregister_shared.assert_called_once_with('foo')


def test_glue_unregister_shared_unknown(glue):
    assert 'foo' not in glue._shared_functions_registry

    glue.unregister_shared('foo')


def test_glue_has_shared(glue):
    glue._shared_functions_registry['foo'] = None
    assert 'foo' in glue._shared_functions_registry

    assert glue.has_shared('foo') is True


def test_has_shared(module, monkeypatch):
    mock_return_value = MagicMock()
    monkeypatch.setattr(module.glue, 'has_shared', MagicMock(return_value=mock_return_value))

    assert module.has_shared('foo') == mock_return_value
    module.glue.has_shared.assert_called_once_with('foo')


def test_has_shared_unknown(glue):
    assert 'foo' not in glue._shared_functions_registry
    assert glue.has_shared('foo') is False


def test_glue_shared(glue):
    glue._shared_functions_registry['foo'] = (None, MagicMock(return_value=17))

    assert glue.shared('foo', 13, 11, 'bar', arg='baz') == 17
    glue._shared_functions_registry['foo'][1].assert_called_once_with(13, 11, 'bar', arg='baz')


def test_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'shared', MagicMock(return_value=17))

    assert module.shared('foo', 11, 13, 'bar', arg='baz') == 17
    module.glue.shared.assert_called_once_with('foo', 11, 13, 'bar', arg='baz')


def test_glue_shared_unknown(glue):
    assert glue.shared('foo', 13, 11, 'bar', arg='baz') is None


def test_glue_get_shared(glue):
    glue._shared_functions_registry['foo'] = (None, MagicMock())

    assert glue.get_shared('foo') == glue._shared_functions_registry['foo'][1]


def test_glue_get_shared_unknown(glue):
    assert glue.get_shared('foo') is None


def test_get_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'get_shared', MagicMock())

    module.get_shared('foo')

    module.glue.get_shared.assert_called_once_with('foo')


def test_glue_require_shared(glue):
    glue._shared_functions_registry.update({
        'foo': None,
        'bar': None
    })

    glue.require_shared('foo', 'bar')


def test_glue_require_shared_missing(glue):
    with pytest.raises(gluetool.GlueError, match=r"Shared function 'foo' is required. See `gluetool -L` to find out which module provides it."):
        glue.require_shared('foo', 'bar')


def test_glue_require_shared_missing_warning(glue, log):
    glue.require_shared('foo', 'bar', warn_only=True)

    log.match(message="Shared function 'foo' is required. See `gluetool -L` to find out which module provides it.", levelno=logging.WARN)


def test_require_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'require_shared', MagicMock())

    module.require_shared('foo', 'bar', warn_only=True)

    module.glue.require_shared.assert_called_once_with('foo', 'bar', warn_only=True)
