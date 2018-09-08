import os
import string

import pytest
from hypothesis import assume, given, strategies as st

from gluetool.utils import normalize_bool_option, normalize_multistring_option, normalize_path, normalize_path_option, normalize_shell_option


def all_casings(input_string):
    if not input_string:
        yield ""

    else:
        first = input_string[:1]
        for sub_casing in all_casings(input_string[1:]):
            yield first.lower() + sub_casing
            yield first.upper() + sub_casing


# all of these are expected to evaluate to ``True``
POSITIVE_BOOLEAM_OPTIONS = [
    True] \
    + list(all_casings('yes')) \
    + list(all_casings('true')) \
    + ['1'] \
    + ['y', 'Y'] \
    + list(all_casings('on'))


# test not just values, but also check it works when they are wrapped by some whitespace
@pytest.mark.parametrize('value',
                         POSITIVE_BOOLEAM_OPTIONS + ['\t {}\t '.format(value) for value in POSITIVE_BOOLEAM_OPTIONS])
def test_normalize_bool_positive(value):
    assert normalize_bool_option(value) is True


# Anything not listed in POSITIVE_BOOLEAM_OPTIONS should be evaluated to False, including False :)
# Ask hypothesis to run the test with either False or huge pile of weird strings, just make sure
# their stripped version is not in POSITIVE_BOOLEAM_OPTIONS (there's a lot of whitespace in
# string.printable).
@given(value=st.one_of(st.just(False), st.text(alphabet=string.printable)))
def test_normalize_bool_negative(value):
    if not isinstance(value, bool):
        assume(value.strip() not in POSITIVE_BOOLEAM_OPTIONS)

    assert normalize_bool_option(value) is False


def test_normalize_multistring_none():
    assert normalize_multistring_option(None) == []


def test_normalize_multistring_string():
    assert normalize_multistring_option('foo') == ['foo']


# For sake of simplicity, use ASCII lowercase, add comma to get "foo,bar" for free, letting
# us check whether splitting of multiple values in a single item works as well.
@given(value=st.lists(st.text(alphabet=string.ascii_lowercase + ',')))
def test_normalize_multistring(value):
    expected = sum([s.strip().split(',') for s in value], [])

    assert normalize_multistring_option(value) == expected


# Generate path from simple alphabet, throw in slash and tilda to make it look
# like a path.
@given(value=st.text(alphabet=string.ascii_lowercase + '/~'))
def test_normalize_path(value):
    expected = os.path.abspath(os.path.expanduser(value))

    assert normalize_path(value) == expected


# Generate paths, and comma (like test_normalize_multistring) to get multiple paths in a single
# string for free.
@given(value=st.lists(st.text(alphabet=string.ascii_lowercase + '/~,')))
def test_normalize_path_option(value):
    expected = [normalize_path(path) for paths in value for path in paths.split(',')]

    assert normalize_path_option(value) == expected


@pytest.mark.parametrize('option_value, expected', (
    (
        '--foo --bar',
        ['--foo', '--bar']
    ),
    (
        ['--foo --bar', '--baz="abc def"', '--foo abc\\ def'],
        ['--foo', '--bar', '--baz=abc def', '--foo', 'abc def']
    )
))
def test_normalize_shell_option(option_value, expected):
    assert normalize_shell_option(option_value) == expected
