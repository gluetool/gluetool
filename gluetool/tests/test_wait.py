import re
import pytest

import gluetool
import gluetool.utils

from gluetool.result import Result, Ok, Error
from gluetool.utils import wait

# Type annotations
# pylint: disable=unused-import, wrong-import-order
from typing import Any, List  # noqa


def test_sanity(log):
    # type: (Any) -> None

    return_values = [
        Error('failed first time'),
        Error('failed second time'),
        Ok('finally passed')
    ]  # type: List[Result[str, str]]

    def _check():
        # type: () -> Result[str, str]

        return return_values.pop(0)

    wait('dummy check', _check, timeout=10, tick=2)

    assert len(log.records) == 9

    # todo: check decreasing remaining time
    # pylint: disable=line-too-long
    assert re.match(r"waiting for condition 'dummy check', timeout \d seconds, check every 2 seconds", log.records[0].message) is not None  # Ignore PEP8Bear
    assert log.records[1].message == 'calling callback function'
    assert log.records[2].message == 'check failed with \'failed first time\', assuming failure'
    assert re.match(r'\d seconds left, sleeping for 2 seconds$', log.records[3].message) is not None
    assert log.records[4].message == 'calling callback function'
    assert log.records[5].message == 'check failed with \'failed second time\', assuming failure'
    assert re.match(r'\d seconds left, sleeping for 2 seconds$', log.records[6].message) is not None
    assert log.records[7].message == 'calling callback function'
    assert log.records[8].message == 'check passed, assuming success'


def test_timeout():
    with pytest.raises(gluetool.GlueError, match=r"Condition 'dummy check' failed to pass within given time"):
        wait('dummy check', lambda: Error('never going to pass'), timeout=2, tick=1)


def test_invalid_tick():
    with pytest.raises(gluetool.GlueError, match=r'Tick must be an integer'):
        wait(None, None, tick=None)

    with pytest.raises(gluetool.GlueError, match=r'Tick must be a positive integer'):
        wait(None, None, tick=-1)
