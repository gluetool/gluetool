# pylint: disable=blacklisted-name

import logging
import pytest

import gluetool

from . import NonLoadingGlue


def test_check_for_commands():
    commands = ('ls', 'gzip')

    # these should exist...
    for cmd in commands:
        gluetool.utils.check_for_commands([cmd])

    # ... and these probably not.
    for cmd in commands:
        cmd = 'does-not-exists-' + cmd

        with pytest.raises(gluetool.GlueError, match=r"^Command '{0}' not found on the system$".format(cmd)):
            gluetool.utils.check_for_commands([cmd])


def test_cached_property():
    from gluetool.utils import cached_property

    counter = {
        'count': 0
    }

    class DummyClass(object):
        # pylint: disable=too-few-public-methods
        @cached_property
        def foo(self):
            # pylint: disable=no-self-use
            counter['count'] += 1
            return counter['count']

        @cached_property
        def bar(self):
            # pylint: disable=no-self-use
            raise Exception('This property raised an exception')

    obj = DummyClass()
    assert counter['count'] == 0
    assert 'foo' not in obj.__dict__
    assert 'bar' not in obj.__dict__

    # first access should increase the counter
    assert 'bar' not in obj.__dict__
    assert obj.foo == 1
    assert counter['count'] == 1
    assert obj.__dict__['foo'] == 1

    # the second access should return cached value
    assert 'bar' not in obj.__dict__
    assert obj.foo == 1
    assert counter['count'] == 1
    assert obj.__dict__['foo'] == 1

    # increase counter, and observe property
    counter['count'] += 1
    assert 'bar' not in obj.__dict__
    assert obj.foo == 1
    assert obj.__dict__['foo'] == 1

    # remove attribute, and try again - this should clear the cache
    del obj.foo
    assert 'bar' not in obj.__dict__
    assert obj.foo == 3
    assert counter['count'] == 3
    assert obj.__dict__['foo'] == 3

    # when exception is raised, there should be no changes in __dict__
    with pytest.raises(Exception, match=r'^This property raised an exception$'):
        # pylint: disable=pointless-statement
        obj.bar

    assert obj.foo == 3
    assert counter['count'] == 3
    assert obj.__dict__['foo'] == 3
    assert 'bar' not in obj.__dict__


#
# Modules
#

def test_check_module_file(log, tmpdir):
    # pylint: disable=protected-access

    mfile = tmpdir.join('dummy.py')
    glue = NonLoadingGlue()

    def try_pass(file_content):
        mfile.write(file_content)

        log.clear()
        assert glue._check_module_file(str(mfile)) is True
        assert log.records[0].message == "check possible module file '{}'".format(mfile)
        assert log.records[0].levelno == logging.DEBUG

    def try_fail(file_content, error):
        mfile.write(file_content)

        log.clear()
        assert glue._check_module_file(str(mfile)) is False
        assert log.records[0].message == "check possible module file '{}'".format(mfile)
        assert log.records[0].levelno == logging.DEBUG
        assert log.records[1].message == error
        assert log.records[1].levelno == logging.DEBUG

    # Test empty Python file
    try_fail('pass', "  no 'import gluetool' found")

    # Check file that imports gluetool but does not have module class
    try_fail('import gluetool', "  no child of gluetool.Module found")
    try_fail('from gluetool import Glue', "  no child of gluetool.Module found")

    # Check we ignore module classes with wrong base class
    try_fail("""
import gluetool

class DummyModule(object):
    pass
""", "  no child of gluetool.Module found")

    # Check file that does have module class, but that does not import gluetool
    try_fail("""
class DummyModule(gluetool.Module):
    pass
""", "  no 'import gluetool' found")

    # Check file that both imports gluetool, and has module class
    try_pass("""
import gluetool

class DummyModule(gluetool.Module):
    pass
""")

    try_pass("""
from gluetool import Module

class DummyModule(Module):
    pass
""")

    # Check if module can have multiple names
    try_pass("""
from gluetool import Module

class DummyModule(Module):
    name = ['dummy', 'dummy-alias']
""")


class DummyModule(gluetool.Module):
    """
    Very dummy module, implementing necessary methods and attributes
    to pass through Glue's internal machinery.
    """

    name = 'Dummy module'


def test_module_instantiate():
    """
    Try to instantiate a module, and check some of its properties.
    """

    glue = NonLoadingGlue()
    mod = DummyModule(glue, 'module')

    assert mod.glue == glue

    # pylint: disable=protected-access,no-member
    assert mod.debug == mod.logger.debug
    assert mod.verbose == mod.logger.verbose
    assert mod.info == mod.logger.info
    assert mod.warn == mod.logger.warning
    assert mod.error == mod.logger.error
    assert mod.exception == mod.logger.exception

    # pylint: disable-msg=protected-access
    assert not mod._config

    assert mod.data_path is None  # There's no data path for our "Dummy module"
