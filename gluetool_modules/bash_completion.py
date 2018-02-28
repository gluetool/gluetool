import collections

import jinja2

import gluetool
import gluetool.utils

from gluetool.glue import Configurable


BASH_COMPLETION_TEMPLATE = """
_{{ GLUE.tool._command_name }}()
{
    local cur prev
    local modules {% for module_name in MODULE_OPTIONS.iterkeys() | sort %} {{ module_name | replace('-', '_') }}_opts {% endfor %}
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
    {% for module_name, module_options in MODULE_OPTIONS.iteritems() | sort %}
    {{ module_name | replace('-', '_') }}_opts="{{ module_options | sort | join(' ') }}"
    {%- endfor %}

    if [[ ${cur} == -* ]] ; then
        {% for module_name in MODULE_OPTIONS.iterkeys() | sort %}
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
complete -F _{{ GLUE.tool._command_name }} {{ GLUE.tool._command_name }}
"""


class BashCompletion(gluetool.Module):
    name = 'bash-completion'
    description = 'Generate Bash completion configuration.'

    def sanity(self):
        if not self.glue.tool:
            # Don't know how to tell it better - it needs access to self.glue.tool
            # to find out what tool's running this show, to find out its command-name
            # for the completion configuration.
            raise gluetool.GlueError('Module must be used via a gluetool-like tool (e.g. `gluetool bash-completion`')

    def execute(self):
        # pylint: disable=protected-access

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
        for module_name in self.glue.modules.iterkeys():
            Configurable._for_each_option_group(_add_options_from_group,
                                                self.glue.modules[module_name]['class'].options)

        # use the same loop code for the tool as well, just set module_name correctly
        module_name = self.glue.tool._command_name
        Configurable._for_each_option_group(_add_options_from_group, self.glue.options)

        # add -h and --help to every module - these are added by argparse code to the generated
        # help, here we have to do it on our own
        module_options = {
            name: options + ['-h', '--help'] for name, options in module_options.iteritems()
        }

        print jinja2.Template(BASH_COMPLETION_TEMPLATE).render(GLUE=self.glue, MODULE_OPTIONS=module_options)
