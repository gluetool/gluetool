"""
Helpers for terminal color support.
"""

import jinja2.defaults

# Type annotations
# pylint: disable=unused-import,wrong-import-order
from typing import Any, Callable, Dict, Optional, Tuple  # noqa


try:
    import colorama

    COLOR_SUPPORT = True

    _FG_COLORS = ('red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white')
    _BG_COLORS = ('black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white')

    _FG = {
        color: getattr(colorama.Fore, color.upper()) for color in _FG_COLORS
    }  # type: Dict[str, str]

    _BG = {
        color: getattr(colorama.Back, color.upper()) for color in _BG_COLORS
    }  # type: Dict[str, str]

except ImportError:
    COLOR_SUPPORT = False


def _style_plain(text, **kwargs):
    # type: (str, **str) -> str

    # pylint: disable=unused-argument
    return text


# pylint: disable=invalid-name
def _style_colors(text, fg=None, bg=None, reset=True):
    # type: (str, Optional[str], Optional[str], Optional[bool]) -> str

    fg_code = getattr(colorama.Fore, fg.upper()) if fg in _FG_COLORS else ''
    bg_code = getattr(colorama.Back, bg.upper()) if bg in _BG_COLORS else ''
    reset_code = colorama.Style.RESET_ALL if reset else ''

    return '{}{}{}{}'.format(fg_code, bg_code, text, reset_code)


# Make `style` a static method, to allow its change on the "global" level while letting
# its users to notice it changed by not using it directly but via `Colors.style`.
class Colors(object):
    # pylint: disable=too-few-public-methods

    style = None  # type: Callable[..., str]


def switch(enabled):
    # type: (bool) -> None

    """
    Enable or disable output colors.

    :param bool enabled: whether terminal output should be colorized.
    """

    if enabled and not COLOR_SUPPORT:
        # pylint: disable=cyclic-import
        from .log import Logging

        logger = Logging.get_logger()
        assert logger is not None

        logger.warn("Unable to turn on colorized terminal messages, please install 'colorama' package")
        return

    Colors.style = staticmethod(_style_colors if enabled else _style_plain)  # type: ignore  # types are compatible

    jinja2.defaults.DEFAULT_FILTERS['style'] = Colors.style


# Disable colors until told otherwise
switch(False)
