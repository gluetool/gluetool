import pytest

import gluetool.glue
import gluetool.help


def do_test_extract_eval_context_info(source_class, expected):
    assert gluetool.help.extract_eval_context_info(source_class()) == expected


def test_extract_eval_context_info():
    expected_context_info = {
        'some variable': 'and its description'
    }

    class DummyModule(object):
        name = 'dummy-module'

        @property
        def eval_context(self):
            # Cannot assign __content__ == expected_context_info since extract_eval_context_info detects
            # __content__ = {, not just any generic assignment.

            __content__ = {
                'some variable': 'and its description'
            }

            return {}

    do_test_extract_eval_context_info(DummyModule, expected_context_info)


def test_extract_eval_context_info_missing():
    class DummyModule(object):
        name = 'dummy-module'

        @property
        def eval_context(self):
            return {}

    do_test_extract_eval_context_info(DummyModule, {})


def test_extract_eval_context_info_unchanged():
    class DummyModule(gluetool.glue.Configurable):
        name = 'dummy-module'

        @property
        def eval_context(self):
            return {}

    do_test_extract_eval_context_info(DummyModule, {})
