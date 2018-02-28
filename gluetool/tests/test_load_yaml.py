import re

import pytest

from gluetool import GlueError
from gluetool.utils import load_yaml, format_dict

from . import create_yaml


def test_missing_file(tmpdir):
    filepath = '{}.foo'.format(str(tmpdir.join('not-found.yml')))

    with pytest.raises(GlueError, match=r"File '{}' does not exist".format(re.escape(filepath))):
        load_yaml(filepath)


def test_sanity(log, tmpdir):
    data = {
        'some-key': [
            1, 2, 3, 5, 7
        ],
        'some-other-key': {
            'yet-another-key': [
                9, 11, 13
            ]
        }
    }

    filepath = str(create_yaml(tmpdir, 'sanity', data))

    loaded = load_yaml(filepath)

    assert data == loaded
    assert log.records[-1].message == "loaded YAML data from '{}':\n{}".format(filepath, format_dict(data))


def test_invalid_path():
    with pytest.raises(GlueError, match=r'File path is not valid: None'):
        load_yaml(None)

    with pytest.raises(GlueError, match=r'File path is not valid: \[\]'):
        load_yaml([])


def test_bad_yaml(tmpdir):
    f = tmpdir.join('test.yml')
    f.write('{')

    filepath = str(f)

    with pytest.raises(GlueError,
                       match=r"(?ms)Unable to load YAML file '{}': .*? line 1, column 2".format(re.escape(filepath))):
        load_yaml(filepath)
