import pytest

import gluetool


TESTCASES = [
    # args, kwargs, expected attrs, expected repr output, expected module designation

    # simple instance
    [
        ('module',),
        {},
        ('module', 'module', []),
        "PipelineStepModule('module', actual_module='module', argv=[])",
        'module'
    ],
    # different actual module
    [
        ('module',),
        {
            'actual_module': 'different_module'
        },
        ('module', 'different_module', []),
        "PipelineStepModule('module', actual_module='different_module', argv=[])",
        'module:different_module'
    ],
    # throw in argv
    [
        ('module',),
        {
            'argv': ['foo', 'bar']
        },
        ('module', 'module', ['foo', 'bar']),
        "PipelineStepModule('module', actual_module='module', argv=['foo', 'bar'])",
        'module'
    ]
]

@pytest.mark.parametrize('args, kwargs, expected', [
    [args, kwargs, expected_attrs] for args, kwargs, expected_attrs, _, _ in TESTCASES
])
def test_sanity(args, kwargs, expected):
    step = gluetool.glue.PipelineStepModule(*args, **kwargs)

    assert (step.module, step.actual_module, step.argv) == expected


@pytest.mark.parametrize('args, kwargs, expected', [
    [args, kwargs, expected_repr] for args, kwargs, _, expected_repr, _ in TESTCASES
])
def test_repr(args, kwargs, expected):
    step = gluetool.glue.PipelineStepModule(*args, **kwargs)

    assert repr(step) == expected


@pytest.mark.parametrize('args, kwargs, expected', [
    [args, kwargs, expected_designation] for args, kwargs, _, _, expected_designation in TESTCASES
])
def test_module_designation(args, kwargs, expected):
    step = gluetool.glue.PipelineStepModule(*args, **kwargs)

    assert step.module_designation == expected
