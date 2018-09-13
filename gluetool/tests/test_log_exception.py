import re
import sys

import jinja2
import pytest

import gluetool
import gluetool.log


EXPECTED = jinja2.Template(r"""---v---v---v---v---v--- Exception: ---v---v---v---v---v---

At {{ FILE }}:81, in foo:

gluetool.glue.GlueError: Foo failed


  File "{{ FILE }}", line 87, in test_sanity
    foo\(\)

    Local variables:
        exc = Foo failed
        excinfo = \(<class 'gluetool\.glue\.GlueError'>, GlueError\('Foo failed',\), <traceback object at 0x[0-9a-f]+>\)

  File "{{ FILE}}", line 81, in foo
    raise gluetool.GlueError\('Foo failed'\)

    Local variables:

---\^---\^---\^---\^---\^---\^----------\^---\^---\^---\^---\^---\^---

---v---v---v---v---v--- Caused by: ---v---v---v---v---v---

At {{ FILE }}:69, in baz:

exceptions.ValueError: Z is really lame value


  File "{{ FILE }}", line 78, in foo
    return bar\(17\)

    Local variables:

  File "{{ FILE }}", line 73, in bar
    return baz\(13, p\)

    Local variables:
        p = 17

  File "{{ FILE }}", line 69, in baz
    raise ValueError\('Z is really lame value'\)

    Local variables:
        x = 13
        y = 17
        z = 13

---\^---\^---\^---\^---\^---\^----------\^---\^---\^---\^---\^---\^---
""").render(FILE=__file__)


# Raise exception from a frame deeper in the stack, catch it and raise another
# to establish exception chain. Spice the functions with local variables, to give
# us something to check in the output.

def baz(x, y):
    z = x

    raise ValueError('Z is really lame value')


def bar(p):
    return baz(13, p)


def foo():
    try:
        return bar(17)

    except ValueError:
        raise gluetool.GlueError('Foo failed')


def test_sanity():
    # not using pytest.raises, don't want pytest to spoil our exception with its smart stuff
    try:
        foo()

    except gluetool.GlueError as exc:
        excinfo = sys.exc_info()

    # not assigning output of formatter to a local variable, we don't want it to appear in the top-level
    # frame's list of locals, leading to a self-reference in expected output.

    # match lines one by one, using expected as a regex pattern
    for l1, l2 in zip(EXPECTED.split('\n'), gluetool.log.LoggingFormatter._format_exception_chain(excinfo).split('\n')):
        assert re.match('^' + l1 + '$', l2)
