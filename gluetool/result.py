# Type annotations
# pylint: disable=unused-import,wrong-import-order
from typing import cast, Any, Callable, Generic, Optional, TypeVar, Union  # noqa


#
# Result and its handling.
#
#
# A ``Result`` can be either ``Ok(value)`` - valid result, contains a meaningful
# value - or ``Error(error)`` which represents an error, carrying error's description.
#

# T and S represent the type of valid value...
# pylint: disable=invalid-name
T = TypeVar("T")
S = TypeVar("S")
# ... and E and F represent type of the error description.
# pylint: disable=invalid-name
E = TypeVar("E")
F = TypeVar("F")


class Result(Generic[T, E]):
    """
    A simple `Result` type inspired by Rust.

    A ``Result`` can be either ``Ok(value)`` - valid result, contains a meaningful
    value - or ``Error(error)`` which represents an error, carrying error's description.

    :param bool _is_ok: ``True`` when the ``_value`` is OK-ish.
    :param _value: the value carried by the result.
    :param bool _force: guards against accidental direct use.
    """

    def __init__(self, _is_ok, _value, _force=False):
        # type: (bool, Union[T, E], bool) -> None
        """
        .. warning::

           Do not instantiate ``Result`` instances directly, **always** use either
           :py:func:`Ok` or :py:func:`Error` functions. Otherwise, type guarantees
           cannot be given.
        """

        if not _force:
            raise RuntimeError('Do not instantiate Result objects directly.')

        self._is_ok = _is_ok
        self._value = _value

    def __eq__(self, other):
        # type: (Any) -> bool
        # pylint: disable=protected-access

        # pylint: disable=line-too-long
        return bool(
            self.__class__ == other.__class__ and self.is_ok == cast(Result[T, E], other).is_ok and self._value == other._value  # Ignore: PEP8Bear
        )

    def __ne__(self, other):
        # type: (Any) -> bool

        return not bool(self == other)

    def __hash__(self):
        # type: () -> int

        return hash((self.is_ok, self._value))

    def __repr__(self):
        # type: () -> str

        if self.is_ok:
            return 'Ok({})'.format(repr(self._value))

        return 'Error({})'.format(repr(self._value))

    # pylint: disable=invalid-name
    @classmethod
    def Ok(cls, value):
        # type: (T) -> Result[T, E]

        return cls(_is_ok=True, _value=value, _force=True)

    # pylint: disable=invalid-name
    @classmethod
    def Error(cls, error):
        # type: (E) -> Result[T, E]

        return cls(_is_ok=False, _value=error, _force=True)

    @property
    def is_ok(self):
        # type: () -> bool

        return self._is_ok

    @property
    def is_error(self):
        # type: () -> bool
        """
        Returns ``True`` if the result value is invalid.
        """

        return not self._is_ok

    # pylint: disable=invalid-name
    @property
    def ok(self):
        # type: () -> Optional[T]
        """
        Return the result value - valid - if it is valid. Otherwise,
        ``None`` is returned.
        """

        return cast(T, self._value) if self.is_ok else None

    @property
    def error(self):
        # type: () -> Optional[E]
        """
        Return the result value - error - if it is invalid. Otherwise, ``None``
        is returned.
        """

        return cast(E, self._value) if self.is_error else None

    @property
    def value(self):
        # type: () -> Union[T, E]
        """
        Return the result value. It will be either one of valid and error types.
        """

        return self._value

    def expect(self, message):
        # type: (str) -> T
        """
        Return the result value if it is valid. Otherwise, an exception is raised.
        """

        if self.is_ok:
            return cast(T, self._value)

        # Avoiding cyclic imports...
        # pylint: disable=cyclic-import
        from .glue import GlueError

        raise GlueError(message)

    def expect_error(self, message):
        # type: (str) -> E
        """
        Return the result value if it is invalid. Otherwise, an exception is raised.
        """

        if self.is_error:
            return cast(E, self._value)

        # Avoiding cyclic imports...
        # pylint: disable=cyclic-import
        from .glue import GlueError

        raise GlueError(message)

    def unwrap(self):
        # type: () -> T
        """
        Return the result value if it is valid. Otherwise, an exception is rised.
        """

        return self.expect('Expected valid result value, found error')

    def unwrap_error(self):
        # type: () -> E
        """
        Return the error value if the result is invalid. Othwerise, an exception is raised.
        """

        return self.expect_error('Expected invalid result value, found valid one')

    def unwrap_or(self, default):
        # type: (T) -> T
        """
        Return the result value if it is valid. Otherwise, ``default`` is returned.
        """

        if self.is_ok:
            return cast(T, self._value)

        return default

    def map(self, fn):
        # type: (Callable[[T], Result[S, F]]) -> Result[S, F]
        """
        Apply given callback to the valid value.

        If this result carries a valid value, then unpack it and pass it to ``fn`` as its single argument.
        Return value of ``fn`` call is then returned.

        If this result carries an invalid value, ``fn`` is not called, and the invalid value is returned,
        wrapped properly.
        """

        if self.is_error:
            return Error(cast(F, self.unwrap_error()))

        return fn(self.unwrap())

    def map_error(self, fn):
        # type: (Callable[[E], Result[S, F]]) -> Result[S, F]
        """
        Apply given callback to the invalid value.

        If this result carries an invalid value, then unpack it and pass it to ``fn`` as its single argument.
        Return value of ``fn`` call is then returned.

        If this result carries a valid value, ``fn`` is not called, and the valid value is returned,
        wrapped properly.
        """

        if self.is_ok:
            return Ok(cast(S, self.unwrap()))

        return fn(self.unwrap_error())


# pylint: disable=invalid-name
def Ok(value):
    # type: (T) -> Result[T, E]
    """
    Shortcut function to create a new valid Result.
    """

    return Result.Ok(value)


# pylint: disable=invalid-name
def Error(error):
    # type: (E) -> Result[T, E]
    """
    Shortcut function to create a new error Result.
    """

    return Result.Error(error)
