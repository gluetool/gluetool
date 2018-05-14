import functools
import requests as original_requests

import pytest

from gluetool.utils import requests


def test_sanity():
    method_names = ('head', 'get', 'post', 'put', 'patch', 'delete')

    original_methods = {
        method_name: getattr(original_requests, method_name) for method_name in method_names
    }

    with requests() as R:
        assert R == original_requests

        for method_name in method_names:
            original_method = original_methods[method_name]
            actual_method = getattr(R, method_name)

            assert isinstance(actual_method, functools.partial)
            assert actual_method.args[0] == original_method
