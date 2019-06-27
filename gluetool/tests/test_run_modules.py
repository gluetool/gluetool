# pylint: disable=blacklisted-name

import inspect
import pytest

from mock import MagicMock

import gluetool

from . import NonLoadingGlue, create_module


class DummyModule(gluetool.Module):
    """
    Dummy module, implementing necessary methods and attributes
    to pass through Glue's internal machinery.
    """

    name = 'Dummy module'
    shared_functions = ('foo',)

    def foo(self):
        pass


class BrokenModule(DummyModule):
    name = 'Broken module'

    def execute(self):
        raise Exception('bar')


class BrokenBrokenModule(DummyModule):
    name = 'Broken broken module'

    def destroy(self, failure=None):
        raise Exception('bar')


@pytest.fixture(name='glue')
def fixture_glue():
    glue = NonLoadingGlue()

    # register our dummy module classes
    glue.modules['Dummy module'] = gluetool.glue.DiscoveredModule(
        klass=DummyModule,
        group='none'
    )

    glue.modules['Broken module'] = gluetool.glue.DiscoveredModule(
        klass=BrokenModule,
        group='none'
    )

    glue.modules['Broken broken module'] = gluetool.glue.DiscoveredModule(
        klass=BrokenBrokenModule,
        group='none'
    )

    return glue


@pytest.fixture(name='pipeline')
def fixture_pipeline(glue):
    return gluetool.glue.Pipeline(glue, [gluetool.glue.PipelineStepModule('Dummy module')])


@pytest.fixture(name='broken_pipeline')
def fixture_broken_pipeline(glue):
    return gluetool.glue.Pipeline(glue, [gluetool.glue.PipelineStepModule('Broken module')])


@pytest.fixture(name='module')
def fixture_module():
    return create_module(DummyModule, name=DummyModule.name)[1]


@pytest.fixture(name='broken_module')
def fixture_broken_module():
    return create_module(BrokenModule, name=BrokenModule.name)[1]


@pytest.fixture(name='broken_broken_module')
def fixture_broken_broken_module():
    return create_module(BrokenBrokenModule, name=BrokenBrokenModule.name)[1]


def test_safe_call(pipeline):
    mock_return = MagicMock()
    mock_callback = MagicMock(return_value=mock_return)

    ret = pipeline._safe_call(mock_callback, 1, 2, foo='bar')

    assert ret is mock_return
    mock_callback.assert_called_once_with(1, 2, foo='bar')


def test_safe_call_exception(pipeline):
    mock_exc = IndexError()
    mock_callback = MagicMock(side_effect=mock_exc)

    ret = pipeline._safe_call(mock_callback, 1, 2, foo='bar')

    assert isinstance(ret, gluetool.Failure)
    assert ret.module is None
    assert ret.exception is mock_exc
    assert isinstance(ret.exc_info, tuple)


def test_for_each_module(pipeline):
    modules = [
        create_module(DummyModule, name=DummyModule.name)[1],
        create_module(DummyModule, name=DummyModule.name)[1]
    ]

    expected_modules = modules[:]

    def _callback(module, *args, **kwargs):
        expected_module = expected_modules.pop(0)

        assert module is expected_module
        assert pipeline.current_module is expected_module
        assert args == (1, 2)
        assert kwargs == {'foo': 'bar'}

    ret = pipeline._for_each_module(modules, _callback, 1, 2, foo='bar')

    assert ret is None


def test_for_each_module_exception(pipeline, module, broken_module):
    modules = [
        module,
        broken_module
    ]

    ret = pipeline._for_each_module(modules, lambda mod: mod.execute())

    assert isinstance(ret, gluetool.Failure)
    assert ret.exception.message == 'bar'


def test_pipeline_setup(pipeline):
    pipeline._setup()

    assert len(pipeline.modules) == 1
    assert isinstance(pipeline.modules[0], DummyModule)


def test_pipeline_sanity(pipeline, monkeypatch):
    pipeline._setup()

    monkeypatch.setattr(pipeline.modules[0], 'sanity', MagicMock(return_value=None))
    monkeypatch.setattr(pipeline.modules[0], 'check_required_options', MagicMock(return_value=None))

    pipeline._sanity()

    pipeline.modules[0].sanity.assert_called_once_with()
    pipeline.modules[0].check_required_options.assert_called_once_with()


def test_pipeline_execute(pipeline, monkeypatch):
    pipeline._setup()
    pipeline._sanity()

    monkeypatch.setattr(pipeline.modules[0], 'execute', MagicMock())

    pipeline._execute()

    pipeline.modules[0].execute.assert_called_once_with()


def test_pipeline_run(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, '_setup', MagicMock(return_value=None))
    monkeypatch.setattr(pipeline, '_sanity', MagicMock(return_value=None))
    monkeypatch.setattr(pipeline, '_execute', MagicMock(return_value=None))
    monkeypatch.setattr(pipeline, '_destroy', MagicMock(return_value=None))

    assert pipeline.run() == (None, None)

    pipeline._setup.assert_called_once_with()
    pipeline._sanity.assert_called_once_with()
    pipeline._execute.assert_called_once_with()
    pipeline._destroy.assert_called_once_with(failure=None)


def test_sanity_glue_pipeline_run(glue, pipeline, monkeypatch):
    mock_run = MagicMock()
    monkeypatch.setattr(pipeline, 'run', mock_run)

    glue.run_pipeline(pipeline)

    mock_run.assert_called_once_with()


def _test_add_shared(glue, pipeline, monkeypatch, module_klass):
    original_destroy = pipeline._destroy

    def mock_destroy(failure=None):
        # foo should be registered as a shared function
        assert pipeline.has_shared('foo')
        assert glue.has_shared('foo')
        assert pipeline.get_shared('foo') == pipeline.modules[0].foo  # why not `is`? doesn't work :/
        assert pipeline.get_shared('foo') is glue.get_shared('foo')

        # And it should be foo of our dummy module class, i.e. foo's im_class member, as reported by
        # inspect, should be the DummyModule class. So, filter value of im_class member into a separate
        # list, and DummyModule should be its first (and only) member.
        assert [
            member[1] for member in inspect.getmembers(glue.get_shared('foo'), inspect.isclass) if member[0] == 'im_class'
        ].index(module_klass) == 0

        return original_destroy(failure=failure)

    monkeypatch.setattr(pipeline, '_destroy', mock_destroy)

    glue.run_pipeline(pipeline)


def test_add_shared(glue, pipeline, monkeypatch):
    _test_add_shared(glue, pipeline, monkeypatch, DummyModule)


def test_add_shared_on_error(glue, broken_pipeline, monkeypatch):
    # The same as test_add_shared but this time module raises an exception. Its shared functions
    # should be added despite that.

    _test_add_shared(glue, broken_pipeline, monkeypatch, BrokenModule)


def test_add_shared_missing(pipeline, module):
    with pytest.raises(gluetool.GlueError, match=r"No such shared function 'does_not_exist' of module 'Dummy module"):
        pipeline.add_shared('does_not_exist', module)


def test_has_shared(glue, pipeline):
    pipeline.shared_functions['foo'] = None
    glue.pipelines.append(pipeline)

    assert glue.init_module('Dummy module').has_shared('foo') is True
    assert pipeline.has_shared('foo') is True
    assert glue.has_shared('foo') is True


def test_has_shared_unknown(glue, pipeline):
    assert glue.init_module('Dummy module').has_shared('foo') is False
    assert pipeline.has_shared('foo') is False
    assert glue.has_shared('foo') is False


def test_shared(glue, pipeline):
    pipeline.shared_functions['foo'] = (None, MagicMock(return_value=17))
    glue.pipelines.append(pipeline)

    assert glue.init_module('Dummy module').shared('foo', 13, 11, 'bar', arg='baz') == 17
    assert glue.shared('foo', 13, 11, 'bar', arg='baz') == 17


def test_shared_unknown(glue):
    assert glue.init_module('Dummy module').shared('foo', 13, 11, 'bar', arg='baz') is None
    assert glue.shared('foo', 13, 11, 'bar', arg='baz') is None


def test_module_add_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'add_shared', MagicMock())
    module.shared_functions = ('foo',)

    module.add_shared()

    module.glue.add_shared.assert_called_once_with('foo', module)


def test_module_has_shared(module, monkeypatch):
    monkeypatch.setattr(module.glue, 'has_shared', MagicMock(return_value=17))

    assert module.has_shared('foo') == 17
    module.glue.has_shared.assert_called_once_with('foo')
