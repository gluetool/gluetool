import os
import operator

from packaging.version import Version

import gluetool


class ModuleInfo(object):
    # pylint: disable=too-few-public-methods
    def __init__(self, data):
        self.name = data['name']
        self.description = data.get('description', '')
        self.dependencies = data.get('dependencies', {})
        deps = self.dependencies

        self.repo = self.normalize_repos(deps.get('repo', []))
        self.yum = deps.get('yum', [])
        self.pip = deps.get('pip', [])
        self.tasks = deps.get('ansible_tasks', [])

    @staticmethod
    def normalize_repos(repos):
        for repo in repos:
            if 'name' not in repo:
                repo['name'] = 'repo' + str(id(repo))
        return repos


class ModuleInfoGroup(object):
    def __init__(self, logger):
        self.items = {}
        self.logger = logger
        self.ops_map = {
            '>': operator.gt,
            '<': operator.lt,
            '>=': operator.ge,
            '<=': operator.le,
            '==': operator.eq
        }

    def add_moduleinfo(self, moduleinfo):
        if moduleinfo.name in self.items:
            self.logger.warn("Module '{}' is already loaded".format(moduleinfo.name))
            return False

        self.items[moduleinfo.name] = moduleinfo
        return True

    def get_dependencies(self, only_modules):
        data = {
            'repo': [],
            'yum': [],
            'pip': [],
            'ansible_tasks': []
        }
        for moduleinfo in self.items.itervalues():
            if only_modules and moduleinfo.name not in only_modules:
                self.logger.debug("Skip module '{}'".format(moduleinfo.name))
                continue

            self.logger.info('Collect dependencies for \'{}\''.format(moduleinfo.name))
            if moduleinfo.yum:
                data['yum'].extend(moduleinfo.yum)
            if moduleinfo.pip:
                data['pip'].extend(moduleinfo.pip)
            if moduleinfo.repo:
                data['repo'].extend(moduleinfo.repo)
            if moduleinfo.tasks:
                data['ansible_tasks'].extend(moduleinfo.tasks)

        self.logger.debug('pip dependencies:\n{}'.format(data['pip']))
        data['pip'] = self.pip_version_unify(data['pip'])

        return data

    def pip_version_unify(self, pip_deps):
        result = []
        versions = {}
        for item in pip_deps:
            pkg, oper, version = ModuleInfoGroup.parse_pkgver(item)
            if pkg in versions:
                version_limit = versions[pkg]
            else:
                version_limit = gluetool.utils.Bunch(pkg=pkg, equal=None, lower=None, upper=None)
                versions[pkg] = version_limit
            if oper and version:
                self.logger.debug(item)
                self.limit_version(version_limit, oper, version)
        self.logger.debug(versions)
        for _, item in versions.iteritems():
            result.append(self.get_allowed_version_bounds(item))
        return result

    def get_allowed_version_bounds(self, item):
        if not item.equal and not item.lower and not item.upper:
            return item.pkg
        if item.equal:
            if item.upper:
                oper, version = item.upper
                relate = self.ops_map[oper]
                if not relate(Version(item.equal), Version(version)):
                    raise gluetool.GlueError("Cannot find common version for package '{}'".format(item.pkg))
            if item.lower:
                oper, version = item.lower
                relate = self.ops_map[oper]
                if not relate(Version(item.equal), Version(version)):
                    raise gluetool.GlueError("Cannot find common version for package '{}'".format(item.pkg))
            return '{}=={}'.format(item.pkg, item.equal)
        elif item.upper and item.lower:
            lower_operator, lower_version = item.lower
            upper_operator, upper_version = item.upper
            relate = self.ops_map[lower_operator]
            if not relate(Version(upper_version), Version(lower_version)):
                raise gluetool.GlueError("Cannot find common version for package '{}'".format(item.pkg))
            relate = self.ops_map[upper_operator]
            if not relate(Version(lower_version), Version(upper_version)):
                raise gluetool.GlueError("Cannot find common version for package '{}'".format(item.pkg))
            return '{}{}{},{}{}'.format(item.pkg, lower_operator, lower_version, upper_operator, upper_version)
        elif item.upper:
            upper_operator, upper_version = item.upper
            return '{}{}{}'.format(item.pkg, upper_operator, upper_version)
        elif item.lower:
            lower_operator, lower_version = item.lower
            return '{}{}{}'.format(item.pkg, lower_operator, lower_version)

    @staticmethod
    def limit_version(item, oper, version):
        if oper in ['>', '>=']:
            if item.lower:
                _, saved_version = item.lower
                if Version(saved_version) < Version(version):
                    item.lower = [oper, version]
                elif Version(saved_version) == Version(version) and oper == '>':
                    item.lower = [oper, version]
            else:
                item.lower = [oper, version]
        elif oper in ['<', '<=']:
            if item.upper:
                _, saved_version = item.upper
                if Version(saved_version) > Version(version):
                    item.upper = [oper, version]
                elif Version(saved_version) == Version(version) and oper == '<':
                    item.upper = [oper, version]
            else:
                item.upper = [oper, version]
        elif oper in ['==']:
            if item.equal and item.equal != version:
                raise gluetool.GlueError(
                    "Different versions '{}' and '{}' of package '{}' required".format(item.equal, version, item.pkg)
                )
            item.equal = version
        else:
            raise gluetool.GlueError("Unsupported operator '{}'".format(oper))

    @staticmethod
    def parse_pkgver(string):
        ops = ['==', '<=', '>=', '<', '>']
        for item in ops:
            if item in string:
                split = string.split(item)
                return split[0], item, split[1]
        return string, None, None


class DepList(gluetool.Module):
    """
    Module collect dependencies from moduleinfo files.
    Type of dependencies:

        repo: list of yum repositories to import on host before yum dependencies are installed
        yum: resolved with yum/dnf manager
        pip: resolved with pip manager, also version collisions are checked, if specified, \
             if more modules specify same package, but only one specify version, this version will be taken
        ansible_tasks: list of ansible tasks as you know it from playbooks

    Example of moduleinfo file, file can contain more definitions

    .. code-block:: yaml

       ---

       name: postgresql
       description: Connect to PostgreSQL database
       dependencies:
         yum:
           - postgresql
         pip:
           - psycopg2==2.7.1
         repo:
           - name: dummyrepo
             baseurl: http://dummy.url/release/repo
             gpgcheck: 0
         ansible_tasks:
           - name: ensure file is present
             file: path=/etc/magic state=file
    """
    name = 'dep-list'
    description = 'Collect module dependencies for citool modules'
    options = {
        'module-dirs': {
            'help': 'Where to find modules'
        },
        'only-modules': {
            'help': 'If specified, modules for which dependencies will beresolved'
        },
        'output': {
            'help': 'Basename of the output file: ``FILE``-requirements.yml and ``FILE``-tasks.yml will be created.',
            'metavar': 'FILE'
        }
    }
    shared_functions = ['prepare_dependencies']

    @staticmethod
    def collect_moduleinfo_files(path):
        collection = []
        for root, _, files in os.walk(path):
            for filename in files:
                if filename.endswith('.moduleinfo'):
                    collection.append(os.path.join(root, filename))
        return collection

    def load_moduleinfo_files(self, files):
        loaded = ModuleInfoGroup(self.logger)
        for filename in files:
            yaml = gluetool.utils.load_yaml(filename)
            try:
                item = ModuleInfo(yaml)
                if loaded.add_moduleinfo(item):
                    self.info("Module info '{}' loaded".format(item.name))
                    self.debug("Module: '{}'\nDescription: '{}'\nDependencies:\n'{}'".format(
                        item.name, item.description, gluetool.log.format_dict(item.dependencies)
                    ))
            except KeyError:
                self.warn("Module info '{}' cannot be properly loaded".format(filename))
        return loaded

    def prepare_dependencies(self, module_dirs, only_modules):
        dirs = module_dirs

        files = []
        for path in dirs:
            self.info("Searching for modules within path '{}'".format(path))
            files += self.collect_moduleinfo_files(path)
            self.debug(files)
        loaded = self.load_moduleinfo_files(files)
        dependencies = loaded.get_dependencies(only_modules)
        self.debug('Resulting dependencies:\n{}'.format(gluetool.log.format_dict(dependencies)))

        return dependencies

    def execute(self):
        dirs = self.option('module-dirs')
        if dirs:
            dirs = [s.strip() for s in dirs.split(',')]
        modules = self.option('only-modules')
        if modules:
            if modules == '*':
                modules = None
            else:
                modules = [s.strip() for s in modules.split(',')]
        outfile = self.option('output')
        if dirs and outfile:
            dependencies = self.prepare_dependencies(dirs, modules)

            requirements_file, tasks_file = '{}-requirements.yml'.format(outfile), '{}-tasks.yml'.format(outfile)

            gluetool.utils.dump_yaml({
                'compose_requirements': {
                    'repositories': dependencies['repo'],
                    'pip': dependencies['pip'],
                    'yum': dependencies['yum']
                }
            }, requirements_file)

            self.info("Requirements written into '{}'".format(requirements_file))

            gluetool.utils.dump_yaml(dependencies['ansible_tasks'], tasks_file)

            self.info("Requirements written into '{}'".format(tasks_file))

        else:
            self.info('To execute provide --module-dirs and --output, skipping dependencies generation in execute')
