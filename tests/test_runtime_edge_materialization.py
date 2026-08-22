from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

import pytest

from nodrix.errors import (
    RuntimeGraphError,
)
from nodrix.runtime_edge_materialization import (
    RuntimeEdgeBinding,
    RuntimeGraphMemorySettings,
    materialize_runtime_edge,
    runtime_types_compatible,
)
from nodrix.runtime_primitives import (
    RuntimeEdgeQueue,
    RuntimeQueueBinding,
)


def _loaded(
    *,
    inputs=None,
    outputs=None,
    input_memory=None,
    output_memory=None,
    isolation="in_process",
    binding_inputs=None,
    binding_outputs=None,
):
    node = SimpleNamespace(
        input_types=dict(
            inputs
            or {}
        ),
        output_types=dict(
            outputs
            or {}
        ),
        input_memory=dict(
            input_memory
            or {}
        ),
        output_memory=dict(
            output_memory
            or {}
        ),
    )

    binding = SimpleNamespace(
        isolation=isolation,
        memory_inputs=dict(
            binding_inputs
            or {}
        ),
        memory_outputs=dict(
            binding_outputs
            or {}
        ),
    )

    return SimpleNamespace(
        node=node,
        binding=binding,
        inputs={},
        outputs=defaultdict(
            list
        ),
    )


def _binding(
    *,
    source="source.output",
    target="sink.input",
    capacity=4,
    policy="block",
    memory_domain="auto",
    allow_copy=True,
):
    return RuntimeEdgeBinding(
        queue=RuntimeQueueBinding(
            source=source,
            target=target,
            capacity=capacity,
            policy=policy,
        ),
        memory_domain=memory_domain,
        allow_copy=allow_copy,
    )


def _graph_memory(
    *,
    default_domain="auto",
    forbid_implicit_copies=False,
):
    return RuntimeGraphMemorySettings(
        default_domain=default_domain,
        forbid_implicit_copies=(
            forbid_implicit_copies
        ),
    )


def test_runtime_edge_materialization_wires_generic_queue():
    source = _loaded(
        outputs={
            "output": "core.object",
        },
    )

    sink = _loaded(
        inputs={
            "input": "core.object",
        },
    )

    result = (
        materialize_runtime_edge(
            {
                "source": source,
                "sink": sink,
            },
            _binding(
                capacity=7,
                policy="latest",
            ),
            _graph_memory(),
        )
    )

    assert isinstance(
        result.edge,
        RuntimeEdgeQueue,
    )

    assert (
        result.edge.binding.capacity
        == 7
    )

    assert (
        result.edge.binding.policy
        == "latest"
    )

    assert (
        source.outputs["output"]
        == [
            result.edge,
        ]
    )

    assert (
        sink.inputs["input"]
        is result.edge
    )

    assert (
        result.edge.memory_plan
        is result.memory_plan
    )


def test_runtime_edge_materialization_rejects_unknown_node():
    with pytest.raises(
        RuntimeGraphError,
        match="unknown node",
    ):
        materialize_runtime_edge(
            {},
            _binding(),
            _graph_memory(),
        )


def test_runtime_edge_materialization_rejects_unknown_output():
    source = _loaded(
        outputs={
            "other": "core.object",
        },
    )

    sink = _loaded(
        inputs={
            "input": "core.object",
        },
    )

    with pytest.raises(
        RuntimeGraphError,
        match="Unknown output port",
    ):
        materialize_runtime_edge(
            {
                "source": source,
                "sink": sink,
            },
            _binding(),
            _graph_memory(),
        )


def test_runtime_edge_materialization_rejects_unknown_input():
    source = _loaded(
        outputs={
            "output": "core.object",
        },
    )

    sink = _loaded(
        inputs={
            "other": "core.object",
        },
    )

    with pytest.raises(
        RuntimeGraphError,
        match="Unknown input port",
    ):
        materialize_runtime_edge(
            {
                "source": source,
                "sink": sink,
            },
            _binding(),
            _graph_memory(),
        )


def test_runtime_edge_materialization_rejects_type_mismatch():
    source = _loaded(
        outputs={
            "output": "demo.image",
        },
    )

    sink = _loaded(
        inputs={
            "input": "demo.points",
        },
    )

    with pytest.raises(
        RuntimeGraphError,
        match="Type mismatch",
    ):
        materialize_runtime_edge(
            {
                "source": source,
                "sink": sink,
            },
            _binding(),
            _graph_memory(),
        )


def test_runtime_edge_materialization_rejects_duplicate_input():
    source = _loaded(
        outputs={
            "output": "core.object",
        },
    )

    sink = _loaded(
        inputs={
            "input": "core.object",
        },
    )

    nodes = {
        "source": source,
        "sink": sink,
    }

    materialize_runtime_edge(
        nodes,
        _binding(),
        _graph_memory(),
    )

    with pytest.raises(
        RuntimeGraphError,
        match="already connected",
    ):
        materialize_runtime_edge(
            nodes,
            _binding(),
            _graph_memory(),
        )


def test_process_isolation_forces_shared_memory():
    source = _loaded(
        outputs={
            "output": "core.object",
        },
        isolation="process",
    )

    sink = _loaded(
        inputs={
            "input": "core.object",
        },
    )

    result = (
        materialize_runtime_edge(
            {
                "source": source,
                "sink": sink,
            },
            _binding(),
            _graph_memory(),
        )
    )

    assert (
        result.memory_plan.selected
        == "shared"
    )

    assert (
        result.memory_plan.copies
        == 0
    )


def test_global_default_memory_domain_applies_to_auto_edge():
    source = _loaded(
        outputs={
            "output": "core.object",
        },
    )

    sink = _loaded(
        inputs={
            "input": "core.object",
        },
    )

    result = (
        materialize_runtime_edge(
            {
                "source": source,
                "sink": sink,
            },
            _binding(
                memory_domain="auto",
            ),
            _graph_memory(
                default_domain="shared",
            ),
        )
    )

    assert (
        result.memory_plan.selected
        == "shared"
    )


def test_global_copy_forbid_overrides_edge_allow_copy():
    source = _loaded(
        outputs={
            "output": "core.object",
        },
        output_memory={
            "output": "source-domain",
        },
    )

    sink = _loaded(
        inputs={
            "input": "core.object",
        },
        input_memory={
            "input": "target-domain",
        },
    )

    with pytest.raises(
        RuntimeGraphError,
        match="Unsupported memory path",
    ):
        materialize_runtime_edge(
            {
                "source": source,
                "sink": sink,
            },
            _binding(
                allow_copy=True,
            ),
            _graph_memory(
                forbid_implicit_copies=True,
            ),
        )


def test_runtime_edge_materialization_uses_supplied_queue_factory():
    source = _loaded(
        outputs={
            "output": "core.object",
        },
    )

    sink = _loaded(
        inputs={
            "input": "core.object",
        },
    )

    calls = []

    def factory(
        queue_binding,
        memory_plan,
    ):
        calls.append(
            (
                queue_binding,
                memory_plan,
            )
        )

        return RuntimeEdgeQueue(
            queue_binding,
            memory_plan,
        )

    result = (
        materialize_runtime_edge(
            {
                "source": source,
                "sink": sink,
            },
            _binding(),
            _graph_memory(),
            queue_factory=factory,
        )
    )

    assert calls == [
        (
            result.edge.binding,
            result.memory_plan,
        ),
    ]


@pytest.mark.parametrize(
    (
        "source",
        "target",
        "expected",
    ),
    [
        (
            "demo.image",
            "demo.image",
            True,
        ),
        (
            "core.any",
            "demo.image",
            True,
        ),
        (
            "demo.image",
            "core.any",
            True,
        ),
        (
            "demo.image",
            "demo.points",
            False,
        ),
    ],
)
def test_runtime_type_compatibility(
    source,
    target,
    expected,
):
    assert (
        runtime_types_compatible(
            source,
            target,
        )
        is expected
    )


def test_loaded_node_queue_annotations_are_backend_neutral():
    from typing import get_type_hints

    from nodrix.runtime_components import (
        LoadedNode,
    )

    hints = get_type_hints(
        LoadedNode
    )

    assert (
        "RuntimeEdgeQueue"
        in str(
            hints["inputs"]
        )
    )

    assert (
        "RuntimeEdgeQueue"
        in str(
            hints["outputs"]
        )
    )

    assert (
        "EdgeQueue"
        not in str(
            hints["inputs"]
        ).replace(
            "RuntimeEdgeQueue",
            "",
        )
    )
