import subprocess
import re
import sys

FILE_NAME = sys.argv[1] if len(sys.argv) > 1 else 'citool'

CONDITION_FRAME = '''elif [[ ${prev} == %s ]] ; then
            COMPREPLY=( $(compgen -W "${%s}" -- ${cur}) )
            return 0
        '''

MAIN_FRAME = '''
_citool()
{
    local cur prev
    local modules %s
    local index=COMP_CWORD-1

    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[$index]}"

    while [[ ${prev} == -* ]]
    do
        index=$((index - 1))
        prev="${COMP_WORDS[$index]}"
    done

    modules="%s"
%s

    if [[ ${cur} == -* ]] ; then
        begin %s end
    elif [[ ${cur} == [.~/]* ]] ; then
         _filedir
    else
        COMPREPLY=( $(compgen -W "${modules}" -- ${cur}) )
        return 0
    fi
}
complete -F _citool citool
'''


def main():
    # get list of available modules
    list_command = 'citool -l'
    process = subprocess.Popen(list_command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    list_output, _ = process.communicate()

    list_modules = []
    for line in list_output.split('\n'):
        split_line = line.split()
        if len(split_line) >= 2:
            list_modules.append(split_line[0])

    # first item of list is not a name of module
    list_modules.pop(0)
    # citool is also some kind of module for this moment
    list_modules.append('citool')

    # this strings will be merged into frame
    variable_names = ''
    modules_opts = ''
    conditions = ''

    # be verbose
    print "generating bash completion script in '{}', this might take a while".format(FILE_NAME)

    for module_name in list_modules:
        module_variable = '{}_opts'.format(re.sub('-', '_', module_name))
        variable_names += '{} '.format(module_variable)

        help_command = 'citool {} -h'.format(module_name).replace('citool citool', 'citool')
        process = subprocess.Popen(help_command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        help_output, _ = process.communicate()

        module_params = re.findall(r' (--\S+|-\w)', help_output)
        modules_opts += '    {}="{}"\n'.format(module_variable, ' '.join(module_params))

        conditions += CONDITION_FRAME % (module_name, module_variable)

    list_modules.remove('citool')
    list_modules = ' '.join(list_modules)

    output_text = MAIN_FRAME % (variable_names, list_modules, modules_opts, conditions)
    output_text = re.sub('begin elif', 'if', output_text)
    output_text = re.sub(' end', 'fi', output_text)

    with open(FILE_NAME, 'w') as outfile:
        outfile.write(output_text)


if __name__ == "__main__":
    main()
