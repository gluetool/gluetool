"""
Check whether all shared functions, as declared by a module, are actually defined in its code.
"""

import astroid

from pylint.checkers import BaseChecker, utils
from pylint.interfaces import IAstroidChecker


BASE_ID = 76


def register_checkers(linter):
    linter.register_checker(SharedFunctionDefinedChecker(linter))


class SharedFunctionDefinedChecker(BaseChecker):
    """
    Checks whether all shared functions, announced by the module, actually exist in its code.

    Bad:

        shared_functions = ('foo', 'ba')

        ...

        def foo(self):
            pass

        def bar(self):
            pass

    OK:

        shared_functions = ('foo', 'bar')

        ...

    The message ID is ``gluetool-undefined-shared``.
    """

    __implements__ = (IAstroidChecker,)

    name = 'gluetool-undefined-shared-checker'
    priority = -1

    MESSAGE_ID = 'gluetool-undefined-shared'
    msgs = {
        'E%d21' % BASE_ID: (
            'shared function \'%s\' announced by module \'%s\' but undefined',
            MESSAGE_ID,
            'announcing shared functions which is not defined within module'
        )
    }

    # We're keeping track of classes we enter and leave, to correctly handle classes defined
    # in methods - they probably don't have any shared functions to provide but treating them
    # like any other module-level classes is simple way to actually skip them.
    _klass_stack = []

    @utils.check_messages(MESSAGE_ID)
    def visit_classdef(self, node):
        # Each item on the stack is one ClassDef entered (and not left yet), represented
        # by a tuple of three items: (class name, list names class announced as being shared,
        # class-level members).
        self._klass_stack.append((node.name, [], []))

    @utils.check_messages(MESSAGE_ID)
    def leave_classdef(self, node):
        klass_name, announced_functions, class_members = self._klass_stack.pop(-1)

        for name in announced_functions:
            if name in class_members:
                continue

            self.add_message(self.MESSAGE_ID, args=(name, klass_name), node=node)

    @utils.check_messages(MESSAGE_ID)
    def visit_assign(self, node):
        # If the checker is disabled, we simly skip adding shared functions, therefore the test will
        # run, when leaving classdef, with an empty list of shared functions, finding nothing wrong.
        if not self.linter.is_message_enabled(self.MESSAGE_ID, line=node.fromlineno):
            return

        # shared_functions is a class property
        if not isinstance(node.parent, astroid.ClassDef):
            return

        if len(node.targets) != 1:
            return

        target = node.targets[0]

        if not isinstance(target, astroid.AssignName):
            return

        if target.name == 'shared_functions':
            # eval node value to get an interable of shared function names
            # pylint: disable=eval-used
            shared_functions = eval(node.value.as_string())

            # And add it into the list of shared functions of current class.
            # Extending the empty list - it's a part of tuple, we cannot simply replace it with
            # new list, we must modify the existing one.
            self._klass_stack[-1][1].extend(list(shared_functions))

        else:
            # If it's not a `shared_functions = ...` assignment, it's still a definition of a class property,
            # and that's still interesting for us. Module may implement a single function that is aliased
            # on a class level as several functions which are then provided as shared ones. So, we must add
            # this target into a list of "all functions".
            #
            # class Foo(Module):
            #     shared_functions = ('foo', 'bar')
            #
            #     def do_stuff(self):
            #         pass
            #
            #     foo = do_stuff <- these two are "class-level assignment which is not `shared_functions ...`",
            #     bar = do_stuff <- instead they define functions, even shared ones.

            self._klass_stack[-1][2].append(target.name)

    @utils.check_messages(MESSAGE_ID)
    def visit_functiondef(self, node):
        # If the class stack is empty, we're not inside class definition, therefore this function is not
        # a module class method, therefore it cannot be a shared function. Move on, nothing to see here.
        if not self._klass_stack:
            return

        # We're only interested in class level functions aka methods
        if not isinstance(node.parent, astroid.ClassDef):
            return

        self._klass_stack[-1][2].append(node.name)
