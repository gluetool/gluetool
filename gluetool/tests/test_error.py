import string
import types

import pytest
from mock import MagicMock
from hypothesis import example, given, strategies as st

import gluetool
from gluetool import GlueError


@given(message=st.text(string.printable))
def test_message(message):
    with pytest.raises(GlueError) as excinfo:
        raise GlueError(message)

    assert excinfo.value.message == message


# simulate dummy sys.exc_info values, and add the special "no exception" case,
# like the one reported by sys.exc_info()
@given(caused_by=st.tuples(st.integers(), st.integers(), st.integers()))
@example((None, None, None))
def test_caused_by_explicit(caused_by):
    expected = None if caused_by == (None, None, None) else caused_by

    assert GlueError('dummy message', caused_by=caused_by).caused_by == expected


# without any cause, expect None
def test_caused_by_detect_empty():
    with pytest.raises(GlueError) as excinfo:
        raise GlueError('')

    assert excinfo.value.caused_by is None


# with a cause, find out necessary details
def test_caused_by_detect():
    mock_exc = ValueError('dummy error')

    with pytest.raises(GlueError, match=r'dummy message') as excinfo:
        try:
            raise mock_exc

        except ValueError:
            raise GlueError('dummy message')

    exc = excinfo.value

    assert isinstance(exc.caused_by, tuple)
    assert len(exc.caused_by) == 3

    klass, error, tb = exc.caused_by

    assert klass is mock_exc.__class__
    assert error is mock_exc
    assert isinstance(tb, types.TracebackType)


# sentry_fingerprint works with list(str)
@given(current=st.lists(st.text(string.printable)))
def test_sentry_fingerprint(current):
    assert GlueError('').sentry_fingerprint(current) == current


# sentry_tags works with dict(str, str)
@given(current=st.dictionaries(st.text(string.printable), st.text(string.printable)))
def test_sentry_tags(current):
    assert GlueError('').sentry_tags(current) == current


@given(cmd=st.lists(st.text(string.printable)), exit_code=st.integers())
def test_command_error(cmd, exit_code):
    mock_output = MagicMock(exit_code=exit_code)

    exc = gluetool.GlueCommandError(cmd, mock_output)

    assert isinstance(exc, GlueError)
    assert exc.cmd == cmd
    assert exc.output == mock_output
    assert exc.message == "Command '{}' failed with exit code {}".format(cmd, exit_code)


# Simulate module by a simple integer - it's not touched by Failure, therefore it's quite fine.
# exc_info is simulated by tuples of strings - we just want to get them assigned to Failure
# attributes - and to check decisions based on real objects we add few special examples.
@given(module=st.integers(),
       exc_info=st.tuples(st.text(string.printable), st.text(string.printable), st.text(string.printable)))
@example(module=0, exc_info=None)
@example(module=0, exc_info=(None, None, None))
@example(module=0, exc_info=(None, gluetool.SoftGlueError(''), None))
def test_failure(module, exc_info):
    failure = gluetool.Failure(module, exc_info)

    assert failure.module == module
    assert failure.exc_info == exc_info

    assert failure.sentry_event_id is failure.sentry_event_url is None

    if exc_info:
        assert failure.exception == exc_info[1]
        assert failure.soft == isinstance(exc_info[1], gluetool.SoftGlueError)

    else:
        assert failure.exception is None
        assert failure.soft is False
