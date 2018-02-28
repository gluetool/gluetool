"""
Helpers for terminal color support.
"""

import jinja2.defaults


try:
    import colorama

    COLOR_SUPPORT = True

    _FG_COLORS = ('red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white')
    _BG_COLORS = ('black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white')

    _FG = {
        color: getattr(colorama.Fore, color.upper()) for color in _FG_COLORS
    }

    _BG = {
        color: getattr(colorama.Back, color.upper()) for color in _BG_COLORS
    }

except ImportError:
    COLOR_SUPPORT = False


def _style_plain(text, **kwargs):
    # pylint: disable=unused-argument
    return text


# pylint: disable=invalid-name
def _style_colors(text, fg=None, bg=None, reset=True):
    fg = getattr(colorama.Fore, fg.upper()) if fg in _FG_COLORS else ''
    bg = getattr(colorama.Back, bg.upper()) if bg in _BG_COLORS else ''
    reset = colorama.Style.RESET_ALL if reset else ''

    return '{}{}{}{}'.format(fg, bg, text, reset)


# Make `style` a static method, to allow its change on the "global" level while letting
# its users to notice it changed by not using it directly but via `Colors.style`.
class Colors(object):
    # pylint: disable=too-few-public-methods

    style = None


def switch(enabled):
    """
    Enable or disable output colors.

    :param bool enabled: whether terminal output should be colorized.
    """

    if enabled and not COLOR_SUPPORT:
        # pylint: disable=cyclic-import
        from .log import Logging

        Logging.get_logger().warn("Unable to turn on colorized terminal messages, please install 'colorama' package")
        return

    Colors.style = staticmethod(_style_colors if enabled else _style_plain)

    jinja2.defaults.DEFAULT_FILTERS['style'] = Colors.style


# Disable colors until told otherwise
switch(False)
