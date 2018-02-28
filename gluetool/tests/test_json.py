import json
import re
import string

import pytest
from hypothesis import assume, given, strategies as st
from . import create_file, create_json

import gluetool
import gluetool.log
from gluetool.utils import from_json, load_json


# JSON strategy
_json = st.recursive(st.none() | st.booleans() | st.floats(allow_nan=False) | st.text(string.printable),
                     lambda children: st.lists(children) | st.dictionaries(st.text(string.printable), children))


@given(json_data=_json)
def test_sanity(json_data):
    s = json.dumps(json_data)  # JSON => string
    d = from_json(s)  # string => JSON

    assert json_data == d


@pytest.mark.parametrize('filepath', [None, ''])
def test_illegal_filepath(filepath):
    with pytest.raises(gluetool.GlueError, match=r'File path is not valid: {}'.format(filepath)):
        load_json(filepath)


def test_missing_file(tmpdir):
    filepath = '{}.foo'.format(str(tmpdir.join('not-found.json')))

    with pytest.raises(gluetool.GlueError, match=r"File '{}' does not exist".format(re.escape(filepath))):
        load_json(filepath)


@given(json_data=_json)
def test_load(json_data, log, tmpdir):
    filepath = create_json(tmpdir, 'test-load.json', json_data)

    loaded = load_json(filepath)

    assert json_data == loaded
    assert log.match(message="loaded JSON data from '{}':\n{}".format(filepath, gluetool.utils.format_dict(json_data)))


def test_error(tmpdir):
    filepath = create_file(tmpdir, 'test-error.json', lambda stream: stream.write('{'))

    with pytest.raises(gluetool.GlueError,
                       match=r"(?ms)Unable to load JSON file '{}': Expecting object: line 1 column 1 \(char 0\)".format(re.escape(filepath))):
        print load_json(filepath)
