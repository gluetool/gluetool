"""
Checker for using unknown module options.

Does not handle multiple gluetool modules within the same Python module well, all their
options are stored under the same key (file name), which leads to false negatives. This
will be fixed later.
"""

from pylint.checkers import BaseChecker, utils
from pylint.interfaces import IAstroidChecker


BASE_ID = 76


def register_checkers(linter):
    linter.register_checker(OptionDefaultChecker(linter))


class OptionDefaultChecker(BaseChecker):
    """
    Checks whether option help string, when describing a default value, uses ``%(default)s`` variable, and whether
    such option has a default value set explicitly.

    Bad:

    .. code-block:: python

       options = {
           'foo': {
               'help': 'Sets something (default: 79).'
           },
           'bar': {
               'help': 'Sets something else (default: 79).',
               'default': 79
           },
           'baz': {
               'help': 'Sets something completely different.',
               'default': 79
           }
       }

    OK:

    .. code-block:: python

       options = {
           'foo': {
               'help': 'Sets something (default: %(defaults)s).',
               'default': 79
           },
           'bar': {
               'help': 'Sets something else (default: %(default)s).',
               'default': 79
           },
           'baz': {
               'help': 'Sets something completely different (default %(default)s).',
               'default': 79
           }
       }

    The message ID is ``gluetool-option-default``.
    """

    __implements__ = (IAstroidChecker,)

    name = 'gluetool-option-default-checker'
    priority = -1

    MESSAGE_ID_NO_DEFAULT = 'gluetool-option-has-no-default'
    MESSAGE_ID_NO_DEFAULT_IN_HELP = 'gluetool-option-no-default-in-help'
    MESSAGE_ID_HARD_DEFAULT = 'gluetool-option-hard-default'

    msgs = {
        'E%d31' % BASE_ID: (
            'option \'%s\' documents its default value without specifying it',
            MESSAGE_ID_NO_DEFAULT,
            'option documents its default without specifying it'
        ),
        'E%d32' % BASE_ID: (
            'option \'%s\' has default value but does not document it',
            MESSAGE_ID_NO_DEFAULT_IN_HELP,
            'option has default value but does not document it'
        ),
        'E%d33' % BASE_ID: (
            'option \'%s\' refers to its default value by stating the value instead of using \'%%(default)s\'',
            MESSAGE_ID_HARD_DEFAULT,
            'option refers to its default value by stating the value instead of using \'%(default)s\''
        )
    }

    @utils.check_messages(MESSAGE_ID_NO_DEFAULT, MESSAGE_ID_NO_DEFAULT_IN_HELP, MESSAGE_ID_HARD_DEFAULT)
    def visit_module(self, node):
        # pylint: disable=no-self-use

        # One of the first nodes the checker hits is the Module. Before inspecting any calls
        # to self.option, we must inspect it and find option definitions because there might
        # calls to gluetool module's option() method - in helper classes of functions, for example
        # - that call their "parent"'s (our gluetool module) option() method. Such calls use option
        # names that are unknown at the time this checker inspects them because their definitions
        # come later, when the gluetool module is defined.

        from . import OptionsGatherer
        gatherer = OptionsGatherer.walk(node)

        for name, info in gatherer.options.iteritems():
            nodes, closest_node, params = info

            help_text = params.get('help', None)

            if not help_text:
                continue

            for option_node in nodes:
                if not self.linter.is_message_enabled(self.MESSAGE_ID_NO_DEFAULT, line=option_node.fromlineno):
                    return

                if not self.linter.is_message_enabled(self.MESSAGE_ID_NO_DEFAULT_IN_HELP, line=option_node.fromlineno):
                    return

                if not self.linter.is_message_enabled(self.MESSAGE_ID_HARD_DEFAULT, line=option_node.fromlineno):
                    return

            if 'default: ' in help_text:
                if 'default' not in params:
                    self.add_message(self.MESSAGE_ID_NO_DEFAULT, args=name, node=closest_node)
                    continue

                if 'default: %(default)s' not in help_text:
                    self.add_message(self.MESSAGE_ID_HARD_DEFAULT, args=name, node=closest_node)
                    continue

            elif 'default' in params:
                self.add_message(self.MESSAGE_ID_NO_DEFAULT_IN_HELP, args=name, node=closest_node)
