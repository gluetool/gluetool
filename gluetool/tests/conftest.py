# pylint: disable=blacklisted-name

import pytest

import gluetool.log

from . import CaplogWrapper


@pytest.fixture(name='logger', scope='session', autouse=True)
def fixture_enable_logger():
    """
    Initialize logger - in ``gluetool``, this is done by :py:class:`gluetool.glue.Glue` instance
    but we don't have such luxury in the ``gluetool`` unit tests.
    """

    return gluetool.log.Logging.create_logger()


@pytest.fixture(name='enable_logger_propagate', scope='session', autouse=True)
def fixture_enable_logger_propagate():
    """
    Allow propagation of logging records to logger's parents. Without this step, log capturing would
    not work as it sets up another logger, capturing messages propagated by our "real" loggers.
    """

    gluetool.log.Logging.create_logger().propagate = True


@pytest.fixture(name='log', scope='function')
def fixture_log(caplog):
    """
    Wrap the original ``caplog`` object with our proxy that resets "the environment" by clearing
    records captured so far.
    """

    wrapper = CaplogWrapper(caplog)
    wrapper.clear()
    return wrapper
