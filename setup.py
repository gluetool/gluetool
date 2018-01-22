from setuptools import setup

DESCRIPTION = 'Glue!'


if __name__ == '__main__':
    setup(name='gluetool',
          setup_requires=['setuptools_scm'],
          use_scm_version=True,
          packages=[
              'gluetool',
              'gluetool.tests'
          ],
          entry_points={
              'console_scripts': {
                  'gluetool = gluetool.tool:main'
              }
          },
          data_files=[
              ('gluetool_modules', [
                  'gluetool_modules/dep_list.py',
                  'gluetool_modules/dep_list.moduleinfo',
                  'gluetool_modules/yaml_pipeline.py',
                  'gluetool_modules/yaml_pipeline.moduleinfo'
              ])
          ],
          install_requires=[
              'beautifulsoup4==4.5.3',
              'colorama==0.3.7',
              'docutils==0.13.1',
              'enum34==1.1.6',
              'lxml==3.7.3',
              'Jinja2==2.9.6',
              'packaging==16.8',
              'raven==6.0.0',
              'ruamel.yaml==0.15.34',
              'Sphinx==1.5.2',
              'sphinx-rtd-theme==0.1.9',
              'tabulate==0.7.7',
              'urlnorm==1.1.4'
          ],
          description=DESCRIPTION,
          long_description=DESCRIPTION,
          author='Miroslav Vadkerti',
          author_email='mvadkert@redhat.com',
          license='ISC license',
          platforms='UNIX',
          url='TODO',
          classifiers=[
              'Development Status :: 3 - Alpha',
              'Environment :: Console',
              'Intended Audience :: Developers',
              'Intended Audience :: System Administrators',
              'License :: OSI Approved :: ISC License (ISCL)',
              'Operating System :: POSIX',
              'Programming Language :: Python',
              'Programming Language :: Python :: 2.6',
              'Programming Language :: Python :: 2.7',
              'Topic :: Software Development',
              'Topic :: Software Development :: Libraries :: Python Modules',
              'Topic :: Software Development :: Quality Assurance',
              'Topic :: Software Development :: Testing',
              'Topic :: System',
              'Topic :: System :: Archiving :: Packaging',
              'Topic :: System :: Installation/Setup',
              'Topic :: System :: Shells',
              'Topic :: System :: Software Distribution',
              'Topic :: Terminals',
          ])
