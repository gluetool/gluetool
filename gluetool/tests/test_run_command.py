# pylint: disable=blacklisted-name

import errno
import subprocess

import pytest

from mock import MagicMock

import gluetool
from gluetool.log import format_dict
from gluetool.utils import Command, run_command


@pytest.fixture(name='popen')
def fixture_popen(monkeypatch):
    popen = MagicMock()

    process = MagicMock(
        communicate=MagicMock(return_value=(None, None)),
        poll=MagicMock(return_value=0)
    )

    popen = MagicMock(return_value=process)

    monkeypatch.setattr(subprocess, 'Popen', popen)

    return popen


def test_invalid_cmd():
    """
    ``Command`` accepts only a list of strings.
    """

    with pytest.raises(gluetool.GlueError, match=r'^Only list of strings is accepted$'):
        Command('/bin/ls').run()

    with pytest.raises(gluetool.GlueError,
                       match=r"^Only list of strings is accepted, \[<type 'str'>, <type 'int'>\] found$"):
        Command(['/bin/ls', 13]).run()


def _assert_logging(log, record_count, cmd, stdout=None, stderr=None, stdout_index=4, stderr_index=6):
    # pylint: disable=too-many-arguments

    assert len(log.records) == record_count
    # assert all([r.levelno == logging.DEBUG for r in records])

    assert log.records[0].message == 'command:\n{}'.format(format_dict(cmd))

    if stdout is not None:
        assert False

    if stderr is not None:
        assert False


def test_sanity(popen, log):
    """
    Basic usage - run a command, and log its output.
    """

    popen.return_value.communicate.return_value = ('root listing', '')

    command = ['/bin/ls', '/']
    output = Command(command).run()

    assert output.exit_code == 0
    assert output.stdout == 'root listing'
    assert output.stderr == ''
    popen.assert_called_once_with(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    _assert_logging(log, 8, command)
    assert log.records[4].message == 'stdout: (See "verbose" log for the actual message)'
    assert log.records[5].message == 'stdout:\n---v---v---v---v---v---\nroot listing\n---^---^---^---^---^---'
    assert log.records[6].message == 'stderr: (See "verbose" log for the actual message)'
    assert log.records[7].message == 'stderr:\n---v---v---v---v---v---\n\n---^---^---^---^---^---'


@pytest.mark.parametrize('actual_errno, expected_exc, expected_message', [
    (errno.ENOENT, gluetool.GlueError, "Command '/bin/foo' not found"),
    (errno.ENOENT + 1, OSError, 'unexpected OS error')
])
def test_oserror(popen, log, actual_errno, expected_exc, expected_message):
    def throw(*args, **kwargs):
        # pylint: disable=unused-argument

        exc = OSError(expected_message)
        exc.errno = actual_errno

        raise exc

    popen.side_effect = throw

    command = ['/bin/foo']

    with pytest.raises(expected_exc, match=r'^{}$'.format(expected_message)):
        Command(command).run()

    _assert_logging(log, 3, command)


def test_exit_code_error(popen, log):
    """
    Command exited with non-zero exit code.
    """

    popen.return_value.poll.return_value = 1

    command = ['/bin/foo']

    with pytest.raises(gluetool.GlueCommandError, match=r"^Command '\['/bin/foo'\]' failed with exit code 1$") \
            as excinfo:
        Command(command).run()

    _assert_logging(log, 6, command)
    assert log.records[4].message == 'stdout:\n  command produced no output'
    assert log.records[5].message == 'stderr:\n  command produced no output'

    assert excinfo.value.output.exit_code == 1
    assert excinfo.value.output.stdout is None
    assert excinfo.value.output.stderr is None


def test_std_streams_mix(popen, log):
    """
    Stdout and stderr are not mixed together.
    """

    popen.return_value.communicate.return_value = (
        'This goes to stdout\n',
        'This goes to stderr\n'
    )

    command = ['/bin/foo']

    output = Command(command).run()

    assert output.exit_code == 0
    assert output.stdout == 'This goes to stdout\n'
    assert output.stderr == 'This goes to stderr\n'

    _assert_logging(log, 8, command)
    assert log.records[4].message == 'stdout: (See "verbose" log for the actual message)'
    assert log.records[5].message == 'stdout:\n---v---v---v---v---v---\nThis goes to stdout\n\n---^---^---^---^---^---'
    assert log.records[6].message == 'stderr: (See "verbose" log for the actual message)'
    assert log.records[7].message == 'stderr:\n---v---v---v---v---v---\nThis goes to stderr\n\n---^---^---^---^---^---'


@pytest.mark.parametrize('actual_comm, stdout, stderr', [
    (
        (
            None,
            'This goes to stderr\n'
        ),
        (
            gluetool.utils.DEVNULL,
            None
        ),
        (
            subprocess.PIPE,
            'This goes to stderr\n'
        )
    ),
    (
        (
            'This goes to stdout\n',
            None
        ),
        (
            subprocess.PIPE,
            'This goes to stdout\n'
        ),
        (
            gluetool.utils.DEVNULL,
            None
        )
    ),
    (
        (
            'This goes to stdout\nThis goes to stderr\n',
            None
        ),
        (
            subprocess.PIPE,
            'This goes to stdout\nThis goes to stderr\n'
        ),
        (
            subprocess.STDOUT, None
        )
    )
])
def test_forwarding(popen, log, actual_comm, stdout, stderr):
    stdout_arg, stdout_output = stdout
    stderr_arg, stderr_output = stderr

    popen.return_value.communicate.return_value = actual_comm

    command = ['/bin/foo']

    output = Command(command).run(stdout=stdout_arg, stderr=stderr_arg)

    assert output.exit_code == 0
    assert output.stdout == stdout_output
    assert output.stderr == stderr_output

    popen.assert_called_once_with(command, stdout=stdout_arg, stderr=stderr_arg)

    _assert_logging(log, 7, command)

    index = 4

    if stdout_output is None:
        assert log.records[index].message == 'stdout:\n  command produced no output'

        index += 1

    else:
        assert log.records[index].message == 'stdout: (See "verbose" log for the actual message)'
        assert log.records[index + 1].message == 'stdout:\n---v---v---v---v---v---\n{}\n---^---^---^---^---^---'.format(stdout_output)

        index += 2

    if stderr_output is None:
        assert log.records[index].message == 'stderr:\n  command produced no output'

    else:
        assert log.records[index].message == 'stderr: (See "verbose" log for the actual message)'
        assert log.records[index + 1].message == 'stderr:\n---v---v---v---v---v---\n{}\n---^---^---^---^---^---'.format(stderr_output)


def test_invalid_stdout(popen, log):
    def throw(*args, **kwargs):
        # pylint: disable=unused-argument

        raise AttributeError("'tuple' object has no attribute 'fileno'")

    popen.side_effect = throw

    command = ['/bin/foo']

    with pytest.raises(AttributeError, match=r"^'tuple' object has no attribute 'fileno'$"):
        Command(command).run(stdout=(13, 17))

    _assert_logging(log, 3, command)


# This part of run_command probably needs refactoring, to be really testable... it's way
# too complicated :/
#
# def test_inspect(popen, log):
#    cmd = ['/bin/bash', '-c', 'echo "This goes to stdout"; >&2 echo "This goes to stderr"']
#    output = run_command(cmd, inspect=True)
#
#    assert output.exit_code == 0
#    assert output.stdout == 'This goes to stdout\n'
#    assert output.stderr == 'This goes to stderr\n'
#    assert_logging(9, "run command: cmd='['/bin/bash', '-c', 'echo \"This goes to stdout\"; >&2 echo
# \"This goes to stderr\"']', kwargs={'stderr': 'PIPE', 'stdout': 'PIPE'}",
#                   stdout_index=7, stdout='stdout:\n---v---v---v---v---v---\nThis goes to stdout\n\n---^---^-
# --^---^---^---',
#                   stderr_index=8, stderr='stderr:\n---v---v---v---v---v---\nThis goes to stderr\n\n---^---^-
# --^---^---^---')
#
#    assert log.records[1].message == "---v---v---v---v---v--- Output of command: \"/bin/bash\" \"-c\"
# \"echo \"This goes to stdout\"; >&2 echo \"This goes to stderr\"\""
#    assert log.records[2].message == 'output of command is inspected by the caller'
#    assert log.records[3].message == 'following blob-like header and footer are expected to be empty'
#    assert log.records[4].message == 'the captured output will follow them'
#    assert log.records[5].message == '---^---^---^---^---^--- End of command output'
# assert log.records[6].message == 'command exited with code 0'
