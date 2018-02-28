"""
Handy custom PyLint checkers.
"""

from .shared_defined import register_checkers as register_shared_defined
from .unknown_option import register_checkers as register_unknown_option


def register(linter):
    register_shared_defined(linter)
    register_unknown_option(linter)
