from setuptools import setup


if __name__ == '__main__':
    setup(name='gluetool',
          setup_requires=['setuptools_scm'],
          use_scm_version=True,
          packages=[
              'gluetool',
              'gluetool.pylint',
              'gluetool.tests'
          ],
          entry_points={
              'console_scripts': [
                  'gluetool = gluetool.tool:main'
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
              ])
          ],
          install_requires=[
              'beautifulsoup4==4.6.3',
              'colorama==0.3.9',
              'docutils==0.14',
              'enum34==1.1.6',
              'Jinja2==2.10',
              'lxml==4.2.4',
              'packaging==17.1',
              'raven==6.9.0',
              'requests==2.19.1',
              'requests-toolbelt==0.8.0',
              # since 0.15.52, it returns ordereddict instead of pure dicts, making format_dict unhappy
              'ruamel.yaml==0.15.51',
              # newer versions bring way too many incompabilities, needs deeper inspection
              'Sphinx==1.5.2',
              'sphinx-rtd-theme==0.4.1',
              'tabulate==0.8.2',
              'urlnorm==1.1.4'
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
              'Programming Language :: Python :: Implementation :: CPython',
              'Topic :: Software Development :: Libraries :: Application Frameworks',
              'Topic :: Utilities'
          ])
