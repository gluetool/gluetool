import argparse
import functools
import os

import jinja2

import gluetool
import gluetool.glue
from gluetool.log import log_dict


class YAMLPipeline(gluetool.Module):
    """
    It is possible to "wrap" a pipeline, and define it in a quite simple YAML file.

    .. code-block:: yaml

       ---

       # Name of the pipeline
       name:
       # Longer description of the pipeline, e.g. including examples.
       description:

       # List of pipeline options. These are similar to what's possible
       # to declare in usual modules.
       options:
          foo:
            help: Some foo option.
            required: True

          bar:
            help: Another option, this time bar.
            default: 79

       # List of modules and their options. Each option is evaluated as a Jinja2 template,
       # with `PIPELINE` name serving as a reference to the pipeline, providing access to
       # pipeline options and other gluetool internals, like shared functions.
       pipeline:
         - module-1:
             - some-option: "and it's value"

         - module-2:
             - option1: "{{ PIPELINE.option('foo') }}"
             - option2: "{{ PIPELINE.shared('some_shared_function_added_by_module_1', 'baz') }}"

         - module-3:
           # optionally, it is possible skip a module using `when` directive. Its value is evaluated
           # as a template, and if it's false-ish (empty string, False, empty list, ...), the module
           # is not called.
           when: "{{ PIPELINE.option('bar') == 'run-module-3!' }}"

    .. note::

       Please, be aware that even when the pipeline description looks similar to Ansible playbook,
       it it **not** a playbook and there's no connection to Ansible other that the similarity.
       In both cases, the goal is the same - define a sequence of modules, and run them with some
       arguments - therefore the solutions look similar.

    .. note::

       Note that is is necessary to use a argument separator ``--`` on the command line, to split
       options of this (and other modules) from those user wish to pass to the pipeline defined
       by the file.

       .. code-block:: bash

          gluetool yaml-pipeline --description foo.yml -- --pipeline-option1=bar ...

       Without a separator, command-line

       .. code-block:: bash

          gluetool yaml-pipeline --description foo.yml --pipeline-option1=bar

       would raise an exception since ``yaml-pipeline`` module has no ``--pipeline-option1`` option.

    """

    name = 'yaml-pipeline'
    desc = 'Runs pipeline, described by a given YAML file.'

    options = {
        'description': {
            'help': 'File with pipeline description.',
            'metavar': 'FILE'
        },
        # Everything after the separator ends here.
        'pipeline_options': {
            'raw': True,
            'help': 'Pipeline options.',
            'nargs': argparse.REMAINDER
        }
    }

    required_options = ('description',)

    @gluetool.utils.cached_property
    def pipeline(self):
        return gluetool.utils.load_yaml(self.option('description'), logger=self.logger)

    def execute(self):
        # we must fix "type" keys in pipeline options: it's supposed to be a callable
        # but we cannot store callable in YAML, therefore let's convert from strings,
        # using builtins.
        #
        # Also, find required options/
        required_options = []

        for name, properties in self.pipeline['options'].iteritems():
            if 'required' in properties:
                if properties['required'] is True:
                    required_options.append(name)

                del properties['required']

            option_type = properties.get('type', None)

            if option_type is None:
                continue

            if option_type not in __builtins__:
                raise gluetool.GlueError("Cannot find option type '{}'".format(option_type))

            properties['type'] = __builtins__[option_type]

        # our custom "pipeline" module
        class Pipeline(gluetool.Module):
            name = self.pipeline['name']
            desc = self.pipeline['description']

            options = self.pipeline['options']

        # cannot assign local name to Pipeline's class property while delcaring it, therefore setting it now
        Pipeline.required_options = required_options

        log_dict(self.debug, 'pipeline options', Pipeline.options)

        pipeline_module = Pipeline(self.glue, self.pipeline['name'])
        pipeline_module.parse_args(self.option('pipeline_options')[1:])  # skip leading '--'
        pipeline_module.check_dryrun()
        pipeline_module.check_required_options()

        # Run each module, one by one - we cannot construct a pipeline, because options
        # of a module might depend on state of previous modules - available via
        # PIPELINE.shared, for example.
        run_module = functools.partial(self.glue.run_module, register=True)

        def evaluate_value(value):
            # If the template is not a string type, just return it as a string. This helps
            # simplifyusers of this method: *every* value is treated by this method, no
            # exceptions. User gets new one, and is not concerned whether the original was
            # a template or boolean or whatever.

            if not isinstance(value, str):
                return str(value)

            return jinja2.Template(value).render(PIPELINE=pipeline_module, ENV=os.environ)

        for module in self.pipeline['pipeline']:
            log_dict(self.debug, 'module', module)

            # just a module name
            if isinstance(module, str):
                run_module(module, [])
                continue

            if not isinstance(module, dict):
                raise gluetool.GlueError('Unexpected module syntax: {}'.format(module))

            # Check 'when' - if it's set and evaluates as false-ish, skip the module
            when = module.pop('when', None)
            if when is not None:
                # If "when" is a string, expect it's an expression - wrap it with {{ }}
                # to form a Jinja template, and evaluate it.
                if isinstance(when, str):
                    when = evaluate_value('{{ ' + when + ' }}')

                self.debug("evalued when: '{}' ({})".format(when, type(when)))

                # Works for both Python false-ish values and strings, coming from template evaluation
                # If it's false-ish by nature, or its string representation is false-ish, skip the module.
                if not when or when.lower() in ('no', 'off', '0', 'false', 'none'):
                    self.debug('skipping module')
                    continue

            # remaining key is the module name
            module_name = module.keys()[0]

            # empty options
            if module[module_name] is None:
                run_module(module_name, [])
                continue

            module_argv = []

            for option, value in module[module_name].iteritems():
                value = evaluate_value(value)

                if value is None:
                    module_argv.append('--{}'.format(option))

                else:
                    module_argv.append('--{}={}'.format(option, value))

            run_module(module_name, module_argv)
