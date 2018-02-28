"""
Checker for using unknown module options.

Does not handle multiple gluetool modules within the same Python module well, all their
options are stored under the same key (file name), which leads to false negatives. This
will be fixed later.
"""

import imp

import astroid

import pylint
from pylint.checkers import BaseChecker, utils
from pylint.interfaces import IAstroidChecker


BASE_ID = 76


def register_checkers(linter):
    linter.register_checker(OptionNameMatchChecker(linter))


# Stores option names found in inspected files.
OPTION_NAMES = {}


class OptionsGatherer(object):
    # pylint: disable=too-few-public-methods

    """
    Finds option definitions in the module.
    """

    def visit_assign(self, node):
        # pylint: disable=no-self-use

        # skip anything that's not 'options = ...' on the class level
        if not isinstance(node.targets[0], astroid.AssignName):
            return

        if node.targets[0].name != 'options':
            return

        if not isinstance(node.parent, astroid.ClassDef):
            return

        # Options needs to be evaluated within the context of the module defining them - there
        # may be imports, default values, global names, etc. therefore simple eval is not good enough.

        # pylint: disable=exec-used

        # Create a dummy module object, a placeholder.
        module = imp.new_module('dummy-module')

        # Fill it with the module data by executing the module AST node withing the context
        # of our placeholder's namespace.
        exec node.root().as_string() in module.__dict__

        # Now "evaluate" options structure inside this module, assign it to chosen name...
        exec '__pylint_options = {}'.format(node.value.as_string()) in module.__dict__

        # ... and now pull the evaluated, Python data structure, out of the module namespace.
        options = module.__dict__['__pylint_options']

        option_names = OPTION_NAMES[node.root().file] = []

        def _add_options(options):
            for option_name in options.iterkeys():
                if isinstance(option_name, str):
                    option_names.append(option_name)

                elif isinstance(option_name, (list, tuple)):
                    option_names.append(option_name[1])

        if isinstance(options, (list, tuple)):
            for _, group_options in options:
                _add_options(group_options)

            return

        if isinstance(options, dict):
            _add_options(options)
            return

        raise Exception('Unknown options type {}'.format(type(options)))


class OptionNameMatchChecker(BaseChecker):
    """
    Checks for unknown option names used when calling module's ``option`` method.

    Bad:

    .. code-block:: python

       options = {
           'fo': ...
       }

       print self.option('foo')

    OK:

    .. code-block:: python

       options = {
           'foo': ...
       }

    The message ID is ``gluetool-unknown-option``.
    """

    __implements__ = (IAstroidChecker,)

    name = 'gluetool-unknown-option-checker'
    priority = -1

    MESSAGE_ID = 'gluetool-unknown-option'
    msgs = {
        'E%d11' % BASE_ID: (
            'option \'%s\' is not defined',
            MESSAGE_ID,
            'accessing option which is not found within module\'s options'
        )
    }

    def visit_module(self, node):
        # pylint: disable=no-self-use

        # One of the first nodes the checker hits is the Module. Before inspecting any calls
        # to self.option, we must inspect it and find option definitions because there might
        # calls to gluetool module's option() method - in helper classes of functions, for example
        # - that call their "parent"'s (our gluetool module) option() method. Such calls use option
        # names that are unknown at the time this checker inspects them because their definitions
        # come later, when the gluetool module is defined.

        walker = pylint.utils.PyLintASTWalker(None)
        walker.add_checker(OptionsGatherer())
        walker.walk(node)

    @utils.check_messages(MESSAGE_ID)
    def visit_call(self, node):
        # pylint: disable=too-many-return-statements

        # Ignore everything but 'self.option'
        if not isinstance(node.func, astroid.Attribute):
            return

        if node.func.attrname != 'option':
            return

        if not node.args:
            # No arguments for option call? This should be caught by other checkers since option() clearly says
            # it takes one parameter. We can ignore such call.
            return

        option_node = node.args[0]

        # Check only calls with an argument being a string constant - we don't deal with variables,
        # like foo = 'bar'; self.option(foo)
        if not isinstance(option_node, astroid.Const):
            return

        option = option_node.value

        if not isinstance(option, str):
            return

        if not self.linter.is_message_enabled(self.MESSAGE_ID, line=node.fromlineno):
            return

        option_names = OPTION_NAMES[node.root().file]

        if option in option_names:
            return

        self.add_message(self.MESSAGE_ID, args=node.args[0].value, node=node)
