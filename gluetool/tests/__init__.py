# pylint: disable=blacklisted-name

# pylint: disable=relative-import
import json

import ruamel.yaml

import gluetool


__all__ = ['Bunch', 'NonLoadingGlue', 'create_module', 'create_yaml']


class Bunch(object):
    # pylint: disable=too-few-public-methods

    """
    Object-like access to a dictionary - useful for many mock objects.
    """

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class NonLoadingGlue(gluetool.Glue):
    """
    Current Glue implementation loads modules and configs when instantiated,
    which makes it *really* hard to make assumptions of the state of its
    internals - they will always be spoiled by other modules, other external
    resources the tests cannot control. So, to overcome this I use this
    custom Glue class that disables loading of modules and configs on its
    instantiation.
    """

    def _load_modules(self):
        pass

    def parse_config(self, *args, **kwargs):
        # pylint: disable=arguments-differ

        pass

    def parse_args(self, *args, **kwargs):
        # pylint: disable=arguments-differ

        pass


class CaplogWrapper(object):
    """
    Thin wrapper around pytest's caplog plugin.
    """

    def __init__(self, caplog):
        self._caplog = caplog

    @property
    def records(self):
        return self._caplog.records

    def __repr__(self):
        return '\n'.join(["<Record: msg='{}'>".format(record.message) for record in self.records])

    def clear(self):
        """
        Clear list of captured records.
        """

        self._caplog.handler.records = []

    def match(self, matcher=any, **kwargs):
        def _cmp(record):
            return all(getattr(record, field) == value for field, value in kwargs.iteritems())

        return matcher(_cmp(record) for record in self.records)


def create_module(module_class, glue=None, glue_class=NonLoadingGlue, name='dummy-module', add_shared=True):
    glue = glue or glue_class()
    mod = module_class(glue, name)

    if add_shared is True:
        mod.add_shared()

    return glue, mod


def create_file(tmpdir, name, writer):
    f = tmpdir.join(name)
    filepath = str(f)

    with open(filepath, 'w') as stream:
        writer(stream)
        stream.flush()

    return filepath


def create_yaml(tmpdir, name, data):
    return create_file(tmpdir, name, lambda stream: ruamel.yaml.YAML().dump(data, stream))


def create_json(tmpdir, name, data):
    return create_file(tmpdir, name, lambda stream: json.dump(data, stream))
