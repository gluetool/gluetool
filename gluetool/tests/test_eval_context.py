# pylint: disable=blacklisted-name

import logging
import pytest

import gluetool

from . import create_module


class DummyModule(gluetool.Module):
    """
    Dummy module, implementing necessary methods and attributes
    to pass through Glue's internal machinery.
    """

    name = 'Dummy module'


@pytest.fixture(name='module')
def fixture_module():
    return create_module(DummyModule)[1]


def test_sanity(module):
    module.shared('eval_context')


def test_module(module):
    eval_context = module.shared('eval_context')

    assert 'MODULE' in eval_context
    assert eval_context['MODULE'] is module


def test_module_via_glue(module, log):
    eval_context = module.glue.shared('eval_context')

    assert 'MODULE' in eval_context
    assert eval_context['MODULE'] is None

    assert log.records[-3].message == 'Cannot infer calling module of eval_context'
    assert log.records[-3].levelno == logging.WARNING
