import pytest
from mock import MagicMock

import gluetool
from gluetool.result import Result, Ok, Error


@pytest.mark.parametrize('result, value, is_ok', [
    (Ok(1), 1, True),
    (Result.Ok(1), 1, True),
    (Ok(True), True, True),
    (Ok(False), False, True),
    (Error(1), 1, False),
    (Result.Error(1), 1, False),
    (Error(True), True, False)
])
def test_factory(result, value, is_ok):
    assert result._value == value
    assert result.is_ok is is_ok
    assert result.is_error is not is_ok


def test_eq():
    assert Ok(1) == Ok(1)
    assert Error(1) == Error(1)
    assert Ok(1) != Error(1)
    assert Ok(1) != Ok(2)
    assert not (Ok(1) != Ok(1))
    assert Ok(1) != 'foo'
    assert Ok('0') != Ok(0)


def test_hash():
    assert len({Ok(1), Error('2'), Ok(1), Error('2')}) == 2
    assert len({Ok(1), Ok(2)}) == 2
    assert len({Ok('a'), Error('a')}) == 2


def test_ok_value():
    o = Ok('foo')
    n = Error('foo')
    assert o.ok == 'foo'
    assert n.ok is None


def test_err_value():
    o = Ok('foo')
    n = Error('foo')
    assert o.error is None
    assert n.error == 'foo'


def test_no_constructor():
    with pytest.raises(RuntimeError):
        Result(_is_ok=True, _value='foo')


def test_unwrap():
    o = Ok('foo')
    n = Error('foo')

    assert o.unwrap() == 'foo'

    with pytest.raises(gluetool.GlueError):
        n.unwrap()


def test_unwrap_error():
    o = Ok('foo')
    n = Error('foo')

    with pytest.raises(gluetool.GlueError):
        o.unwrap_error()

    assert n.unwrap_error() == 'foo'


def test_expect():
    o = Ok('foo')
    n = Error('foo')

    assert o.expect('failure') == 'foo'

    with pytest.raises(gluetool.GlueError):
        n.expect('failure')


def test_expect_error():
    o = Ok('foo')
    n = Error('foo')

    with pytest.raises(gluetool.GlueError):
        o.expect_error('failure')

    assert n.expect_error('failure') == 'foo'


def test_unwrap_or():
    o = Ok('foo')
    n = Error('foo')

    assert o.unwrap_or('default value') == 'foo'
    assert n.unwrap_or('default value') == 'default value'


def test_map():
    o = Ok('foo')

    mock_on_error = MagicMock()

    n = o \
        .map(lambda s: Ok(s + 'bar')) \
        .map(lambda s: Ok(s + 'baz')) \
        .map_error(mock_on_error)

    assert n.is_ok
    assert n.unwrap() == 'foobarbaz'
    mock_on_error.assert_not_called()


def test_map_error():
    o = Error('foo')

    mock_on_ok = MagicMock()

    n = o \
        .map_error(lambda s: Error(s + 'bar')) \
        .map(mock_on_ok)

    assert n.is_error
    assert n.unwrap_error() == 'foobar'
    mock_on_ok.assert_not_called()
