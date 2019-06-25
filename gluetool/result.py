# Type annotations
# pylint: disable=unused-import,wrong-import-order
from typing import cast, Any, Generic, Optional, TypeVar, Union  # noqa


#
# Result and its handling.
#
#
# A ``Result`` can be either ``Ok(value)`` - valid result, contains a meaningful
# value - or ``Error(error)`` which represents an error, carrying error's description.
#

# T represents the type of valid value...
T = TypeVar("T")
# ... and E represents type of the error description.
E = TypeVar("E")


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

        return (self.__class__ == other.__class__ and
                self.is_ok == cast(Result, other).is_ok and
                self._value == other._value)

    def __ne__(self, other):
        # type: (Any) -> bool

        return not self == other

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

    def unwrap(self):
        # type: () -> T
        """
        Return the result value if it is valid. Otherwise, an exception is rised.
        """

        return self.expect('Expected valid result value, found error')

    def unwrap_or(self, default):
        # type: (T) -> T
        """
        Return the result value if it is valid. Otherwise, ``default`` is returned.
        """

        if self.is_ok:
            return cast(T, self._value)

        return default


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
