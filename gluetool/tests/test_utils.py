import string

import pytest
from hypothesis import given, strategies as st

import gluetool


# generate lists of dictionaries with mixture of keys values selected from random strings and integers
@given(dicts=st.lists(st.dictionaries(st.integers() | st.text(string.printable),
                                      st.integers() | st.text(string.printable))))
def test_dict_update(dicts):
    merged = {}
    for d in dicts:
        merged.update(d)

    assert merged == gluetool.utils.dict_update({}, *dicts)
