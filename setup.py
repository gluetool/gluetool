from setuptools import setup


# setuptools-scm would extract version from a git tag, but one has to mention setuptools-scm in
# `setup_requires` field, and pip does not play well with that one, and it's all kinds of messy
# and I see no light :((
VERSION = '1.26'


if __name__ == '__main__':
    setup(name='gluetool',
          version=VERSION,
          packages=[
              'gluetool',
              'gluetool.pylint',
              'gluetool.tests'
          ],
          entry_points={
              'console_scripts': [
                  'gluetool = gluetool.tool:main',
                  'gluetool-html-log = gluetool.html_log:main'
              ]
          },
          package_data={
              'gluetool': [
                  'py.typed'
              ]
          },
          data_files=[
              ('gluetool_modules', [
                  'gluetool_modules/bash_completion.py',
                  'gluetool_modules/bash_completion.moduleinfo',
                  'gluetool_modules/dep_list.py',
                  'gluetool_modules/dep_list.moduleinfo',
                  'gluetool_modules/yaml_pipeline.py',
                  'gluetool_modules/yaml_pipeline.moduleinfo'
              ]),
              ('assets/html-log', [
                  'assets/html-log/prism.css',
                  'assets/html-log/prism.js',
                  'assets/html-log/semantic.min.css',
                  'assets/html-log/semantic.min.js'
              ])
          ],
          install_requires=[
              'beautifulsoup4==4.6.3',
              'colorama==0.3.9',
              'docutils==0.14',
              'enum34==1.1.6; python_version == "2.7"',
              'future==0.16.0',
              'Jinja2==2.10',
              'lxml==4.2.4',
              'mock==3.0.5',
              'mypy-extensions==0.4.1',
              'packaging==17.1',
              'raven==6.9.0',
              'requests==2.25.1',
              'requests-toolbelt==0.8.0',
              'ruamel.yaml==0.16.12',
              'six==1.12.0',
              'Sphinx==1.5.2',
              'sphinx-rtd-theme==0.4.1',
              'tabulate==0.8.2',
              'typing==3.7.4; python_version == "2.7"',
              'typing-extensions>=3.7.4.1',
              'urlnormalizer==1.2.0',
              'pyparsing==2.3.0',
              'MarkupSafe==1.1.0'
          ],
          description='Python framework for constructing command-line pipelines',
          # pylint: disable=line-too-long
          long_description='Gluetool is a command line centric generic framework useable for glueing modules into pipeline',
          author='Miroslav Vadkerti, Milos Prchlik and others',
          author_email='mvadkert@redhat.com, mprchlik@redhat.com',
          license='BSD',
          platforms='UNIX',
          url='https://gluetool.readthedocs.org/',
          classifiers=[
              'Development Status :: 5 - Production/Stable',
              'Environment :: Console',
              'Intended Audience :: Developers',
              'Intended Audience :: System Administrators',
              'License :: OSI Approved :: BSD License',
              'Operating System :: POSIX :: Linux',
              'Programming Language :: Python :: 2.7',
              'Programming Language :: Python :: 3.6',
              'Programming Language :: Python :: Implementation :: CPython',
              'Topic :: Software Development :: Libraries :: Application Frameworks',
              'Topic :: Utilities'
          ])
