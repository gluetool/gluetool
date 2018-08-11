"""
Handy custom PyLint checkers.
"""

import collections
import imp

import astroid
import pylint.utils

from .option_default import register_checkers as register_option_default
from .shared_defined import register_checkers as register_shared_defined
from .unknown_option import register_checkers as register_unknown_option


#: Represents information checker has on an option.
#:
#: :param list nodes: List of AST nodes. Currently, we're passing just a single one, the whole ``options`` dictionary,
#:     but the idea is to implement search for deeper nodes, more precisely locating each option.
#: :param closest_node: node closest in the tree to the definition of the option.
#: :param dict params: option parameters, as described by the module author (``argparse`` keywords).
OptionInfo = collections.namedtuple('OptionInfo', ('nodes', 'closest_node', 'params'))


class OptionsGatherer(object):
    # pylint: disable=too-few-public-methods

    """
    Finds option definitions in the module.
    """

    def __init__(self):
        self.options = {}

    @classmethod
    def walk(cls, node):
        gatherer = cls()

        walker = pylint.utils.PyLintASTWalker(None)
        walker.add_checker(gatherer)
        walker.walk(node)

        return gatherer

    def visit_assign(self, node):
        # pylint: disable=no-self-use

        # skip anything that's not 'options = ...' on the class level
        if not isinstance(node.targets[0], astroid.AssignName):
            return

        if node.targets[0].name != 'options':
            return

        if not isinstance(node.parent, astroid.ClassDef):
            return

        # We're processing options two times:
        #
        # 1) to find out options' parameters, which may require references to default values, global names,
        # other modules and so on, we need to use Python's `exec` - Python will resolve everything, including
        # imports;
        #
        # 2) the option above does not preserve information about nodes corresponding to options, `exec` does
        # not care about them. We need to process AST to find these nodes, but we don't need to dive into options'
        # parameters since we already have them.
        #
        # Well, it's not that easy: way #2 is **not** implemented yet, because it has to deal with many different
        # ways ``options`` "dict" can be specified (dict, list, tuple, calls to dict_update, etc.) Leaving that
        # for the future since it'd would be nice to find specific node for each option, to allow more precise
        # disabling the checks, and also logging would be more precise.

        # pylint: disable=exec-used

        # Create a dummy module object, a placeholder.
        module = imp.new_module('dummy-module')

        # Fill it with the module data by executing the module AST node withing the context
        # of our placeholder's namespace.
        exec node.root().as_string() in module.__dict__

        # Now "evaluate" options structure inside this module, assign it to chosen name...
        exec '__pylint_options = {}'.format(node.value.as_string()) in module.__dict__

        # ... and now pull the evaluated, Python data structure, out of the module namespace.
        executed_options = module.__dict__['__pylint_options']

        # Here will be the second method
        # ...

        def _add_options(options):
            for name, params in options.iteritems():
                if isinstance(name, str):
                    self.options[name] = OptionInfo([node], node, params)

                elif isinstance(name, (list, tuple)):
                    self.options[name[1]] = OptionInfo([node], node, params)

        if isinstance(executed_options, (list, tuple)):
            for _, group_options in executed_options:
                _add_options(group_options)

            return

        if isinstance(executed_options, dict):
            _add_options(executed_options)
            return

        raise Exception('Unknown options type {}'.format(type(executed_options)))


def register(linter):
    register_option_default(linter)
    register_shared_defined(linter)
    register_unknown_option(linter)
