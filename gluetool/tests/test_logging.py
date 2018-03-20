import json
import re
import string

import pytest
from hypothesis import assume, given, strategies as st

import gluetool.log

# strategy to generate strctured data
_structured = st.recursive(st.none() | st.booleans() | st.floats(allow_nan=False) | st.text(string.printable),
                           lambda children: st.lists(children) | st.dictionaries(st.text(string.printable), children))


@given(blob=st.text(alphabet=string.printable + string.whitespace))
def test_format_blob(blob):
    pattern = r"""^{}$
{}
^{}$""".format(re.escape(gluetool.log.BLOB_HEADER),
               re.escape(blob),
               re.escape(gluetool.log.BLOB_FOOTER))

    re.match(pattern, gluetool.log.format_blob(blob), re.MULTILINE)


@given(data=_structured)
def test_format_dict(data):
    # This is what format_dict does... I don't have other way to generate similar to output to match format_dict
    # with other code. Therefore this is more like a sanity test, checking that format_dict does some formatting,
    # ignoring how its output actually looks.
    def default(obj):
        return repr(obj)

    expected = json.dumps(data, sort_keys=True, indent=4, separators=(',', ': '), default=default)

    assert re.match(re.escape(expected), gluetool.log.format_dict(data), re.MULTILINE)
