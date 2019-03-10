# pylint: disable=blacklisted-name

import logging
import pytest

import gluetool
import pkg_resources

from mock import MagicMock


class DummyModule(gluetool.Module):
    name = 'dummy-module'


class DummyModuleWithAliases(gluetool.Module):
    name = ('dummy-module', 'dummy-module-alias')


class DummyModuleWithoutName(gluetool.Module):
    pass


@pytest.fixture(name='glue')
def fixture_glue():
    return gluetool.Glue()


def _assert_module_registered(log, glue, registry, klass, name, group):
    assert name in registry
    assert registry[name].klass is klass
    assert registry[name].group == group

    assert log.match(message="registering module '{}' from dummy-filepath:{}".format(name, klass.__name__))


def test_register_module(log, glue):
    registry = {}

    glue._register_module(registry, 'dummy-group', DummyModule, 'dummy-filepath')

    assert len(registry) == 1

    _assert_module_registered(log, glue, registry, DummyModule, 'dummy-module', 'dummy-group')


def test_register_module_aliases(log, glue):
    registry = {}

    glue._register_module(registry, 'dummy-group', DummyModuleWithAliases, 'dummy-filepath')

    assert len(registry) == 2

    _assert_module_registered(log, glue, registry, DummyModuleWithAliases, 'dummy-module', 'dummy-group')
    _assert_module_registered(log, glue, registry, DummyModuleWithAliases, 'dummy-module-alias', 'dummy-group')


def test_register_module_no_names(log, glue):
    registry = {}

    with pytest.raises(gluetool.GlueError, match=r'No name specified by module class dummy-filepath:DummyModule'):
        glue._register_module(registry, 'dummy-group', DummyModuleWithoutName, 'dummy-filepath')


def test_register_module_name_conflict(log, glue):
    registry = {
        'dummy-module': None
    }

    with pytest.raises(gluetool.GlueError, match=r"Name 'dummy-module' of class dummy-filepath:DummyModule is a duplicate module name"):
        glue._register_module(registry, 'dummy-group', DummyModule, 'dummy-filepath')


def test_discover_gm_in_entry(log, monkeypatch, glue):
    registry = {}

    mock_ep = MagicMock(load=MagicMock(return_value=DummyModule), dist=MagicMock(location='dummy-filepath'))
    mock_iter_entry_points = MagicMock(return_value=[mock_ep])

    monkeypatch.setattr(pkg_resources, 'iter_entry_points', mock_iter_entry_points)

    glue._discover_gm_in_entry_point('dummy-entry-point', registry)

    mock_ep.load.assert_called_once()

    assert len(registry) == 1
    _assert_module_registered(log, glue, registry, DummyModule, 'dummy-module', '')


@pytest.mark.parametrize(
    ('expected', 'error_message', 'content'),
    (
        # Empty Python file
        (False, "  no 'import gluetool' found", 'pass'),

        # Check file that imports gluetool but does not have module class
        (False, '  no child of gluetool.Module found', 'import gluetool'),
        (False, '  no child of gluetool.Module found', 'from gluetool import Glue'),

        # Check we ignore module classes with wrong base class
        (False, '  no child of gluetool.Module found', """
import gluetool

class DummyModule(object):
    pass
"""),

        # Check file that does have module class, but that does not import gluetool
        (False, "  no 'import gluetool' found", """
class DummyModule(gluetool.Module):
    pass
"""),

        # Check file that both imports gluetool, and has module class
        (True, '', """
import gluetool

class DummyModule(gluetool.Module):
    pass
"""),

        (True, '', """
from gluetool import Module

class DummyModule(Module):
    pass
"""),

        # Check if module can have multiple names
        (True, '', """
from gluetool import Module

class DummyModule(Module):
    name = ['dummy', 'dummy-alias']
""")
    )
)
def test_check_pm_file(log, tmpdir, glue, expected, error_message, content):
    # pylint: disable=protected-access

    pm_file = tmpdir.join('dummy.py')
    pm_file.write(content)

    log.clear()

    assert glue._check_pm_file(str(pm_file)) is expected

    assert log.match(levelno=logging.DEBUG, message="check possible module file '{}'".format(pm_file))

    if expected is False:
        assert log.match(levelno=logging.DEBUG, message=error_message)


def test_check_pm_file_missing(log, tmpdir, glue):
    with pytest.raises(gluetool.GlueError, match=r"Unable to check check module file 'foo\.txt': \[Errno 2\] No such file or directory: 'foo\.txt'"):
        glue._check_pm_file('foo.txt')
