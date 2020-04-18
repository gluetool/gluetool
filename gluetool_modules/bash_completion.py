import collections
import sys

import jinja2

from six import iterkeys, iteritems

import gluetool
import gluetool.utils

from gluetool.glue import Configurable


BASH_COMPLETION_TEMPLATE = """
_{{ COMMAND_NAME }}()
{
    local cur prev
    local modules {% for module_name in iterkeys(MODULE_OPTIONS) | sort %} {{ module_name | replace('-', '_') }}_opts {% endfor %}
    local index=COMP_CWORD-1

    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[$index]}"

    while [[ ${prev} == -* ]]
    do
        index=$((index - 1))
        prev="${COMP_WORDS[$index]}"
    done

    modules="{{ GLUE.modules.keys() | sort | join(' ') }}"
    {% for module_name, module_options in iteritems(MODULE_OPTIONS) | sort %}
    {{ module_name | replace('-', '_') }}_opts="{{ module_options | sort | join(' ') }}"
    {%- endfor %}

    if [[ ${cur} == -* ]] ; then
        {% for module_name in iterkeys(MODULE_OPTIONS) | sort %}
            if [[ ${prev} == {{ module_name }} ]]; then
                COMPREPLY=( $(compgen -W "${{ module_name | replace('-', '_') }}_opts" -- ${cur}) )
                return 0
            fi
        {% endfor %}
    elif [[ ${cur} == [.~/]* ]] ; then
         _filedir
    else
        COMPREPLY=( $(compgen -W "${modules}" -- ${cur}) )
        return 0
    fi
}
complete -F _{{ COMMAND_NAME }} {{ COMMAND_NAME }}

"""


class BashCompletion(gluetool.Module):
    name = 'bash-completion'
    description = 'Generate Bash completion configuration.'

    options = {
        'command-name': {
            'help': 'Generate rules for command COMMAND (default: %(default)s).',
            'default': 'gluetool',
            'type': str
        }
    }

    def sanity(self):
        if not self.glue.tool:
            # Don't know how to tell it better - it needs access to self.glue.tool
            # to find out what tool's running this show, to find out its command-name
            # for the completion configuration.
            raise gluetool.GlueError('Module must be used via a gluetool-like tool (e.g. `gluetool bash-completion`')

    def execute(self):
        # pylint: disable=protected-access

        command_name = self.option('command-name')

        module_options = collections.defaultdict(list)

        # Callbacks for Glue's standard "loop over all options" helper methods.

        # For the option, construct its command-line forms and add them to the list
        # of all options of this module.
        def _add_option(name, names, params):
            # pylint: disable=unused-argument

            dest = module_options[module_name]

            if isinstance(names, tuple):
                dest += ['-{}'.format(names[0])]
                dest += ['--{}'.format(s) for s in names[1:]]

            else:
                dest += ['--{}'.format(names)]

        # For the option group, simply process them using the callback above.
        def _add_options_from_group(options, **kwargs):
            # pylint: disable=unused-argument

            Configurable._for_each_option(_add_option, options)

        # Inspect all option groups defined by the module, and add every option found
        for module_name in iterkeys(self.glue.modules):
            Configurable._for_each_option_group(_add_options_from_group,
                                                self.glue.modules[module_name].klass.options)

        # use the same loop code for the tool as well, just set module_name correctly
        module_name = command_name
        Configurable._for_each_option_group(_add_options_from_group, self.glue.options)

        # add -h and --help to every module - these are added by argparse code to the generated
        # help, here we have to do it on our own
        module_options = {
            name: options + ['-h', '--help'] for name, options in iteritems(module_options)
        }

        sys.stdout.write(jinja2.Template(BASH_COMPLETION_TEMPLATE).render(
            GLUE=self.glue,
            MODULE_OPTIONS=module_options,
            COMMAND_NAME=command_name
        ))
