from __future__ import annotations

from collections import (
    defaultdict,
)
from types import (
    SimpleNamespace,
)

from nodrix.runtime_primitives import (
    RuntimeEdgeQueue,
)
from nodrix.system.connection_execution import (
    ResolvedConnectionExecutionPolicy,
    ResolvedConnectionMemoryPolicy,
    ResolvedConnectionQueuePolicy,
)
from nodrix.system.direct_graph_preparation import (
    materialize_direct_edges,
)
from nodrix.system.planning import (
    PlannedConnection,
)
from nodrix.system.runtime_mechanics import (
    ResolvedGraphMemoryMechanics,
    ResolvedRuntimeMechanics,
)


def _loaded(
    *,
    inputs=None,
    outputs=None,
):
    return SimpleNamespace(
        node=SimpleNamespace(
            input_types=dict(
                inputs
                or {}
            ),
            output_types=dict(
                outputs
                or {}
            ),
            input_memory={},
            output_memory={},
        ),
        binding=SimpleNamespace(
            isolation="in_process",
            memory_inputs={},
            memory_outputs={},
        ),
        inputs={},
        outputs=defaultdict(
            list
        ),
    )


def _planned_node(
    *,
    graph,
    name,
    identity,
):
    return SimpleNamespace(
        graph=graph,
        name=name,
        id=identity,
    )


def _connection(
    *,
    graph="main",
    source="source.out",
    target="sink.in",
    capacity=4,
    policy="block",
    domain="auto",
    allow_copy=True,
):
    return PlannedConnection.model_validate(
        {
            "ordinal": 0,
            "graph": graph,
            "from": source,
            "to": target,
            "type_id": "core.object",
            "placement_target": "local",
            "backend": "local",
            "execution": (
                ResolvedConnectionExecutionPolicy(
                    queue=(
                        ResolvedConnectionQueuePolicy(
                            capacity=capacity,
                            policy=policy,
                        )
                    ),
                    memory=(
                        ResolvedConnectionMemoryPolicy(
                            domain=domain,
                            allow_copy=allow_copy,
                        )
                    ),
                )
            ),
        }
    )


def _mechanics(
    *,
    default_domain="auto",
    forbid_implicit_copies=False,
):
    return ResolvedRuntimeMechanics(
        graph_memory=(
            ResolvedGraphMemoryMechanics(
                default_domain=(
                    default_domain
                ),
                forbid_implicit_copies=(
                    forbid_implicit_copies
                ),
            )
        )
    )


def test_direct_edges_wire_loaded_nodes():
    source = _loaded(
        outputs={
            "out": "core.object",
        },
    )

    sink = _loaded(
        inputs={
            "in": "core.object",
        },
    )

    materialization = (
        SimpleNamespace(
            nodes_by_graph={
                "main": (
                    _planned_node(
                        graph="main",
                        name="source",
                        identity="main/source",
                    ),
                    _planned_node(
                        graph="main",
                        name="sink",
                        identity="main/sink",
                    ),
                ),
            },
            connections_by_graph={
                "main": (
                    _connection(
                        capacity=7,
                        policy="latest",
                    ),
                ),
            },
        )
    )

    edges = materialize_direct_edges(
        materialization,
        {
            "main/source": source,
            "main/sink": sink,
        },
        _mechanics(),
    )

    assert len(
        edges
    ) == 1

    edge = edges[0]

    assert isinstance(
        edge,
        RuntimeEdgeQueue,
    )

    assert (
        edge.binding.capacity
        == 7
    )

    assert (
        edge.binding.policy
        == "latest"
    )

    assert (
        source.outputs["out"]
        == [
            edge,
        ]
    )

    assert (
        sink.inputs["in"]
        is edge
    )


def test_direct_edges_preserve_graph_local_node_identity():
    first_source = _loaded(
        outputs={
            "out": "core.object",
        },
    )

    first_sink = _loaded(
        inputs={
            "in": "core.object",
        },
    )

    second_source = _loaded(
        outputs={
            "out": "core.object",
        },
    )

    second_sink = _loaded(
        inputs={
            "in": "core.object",
        },
    )

    materialization = (
        SimpleNamespace(
            nodes_by_graph={
                "first": (
                    _planned_node(
                        graph="first",
                        name="source",
                        identity="first/source",
                    ),
                    _planned_node(
                        graph="first",
                        name="sink",
                        identity="first/sink",
                    ),
                ),
                "second": (
                    _planned_node(
                        graph="second",
                        name="source",
                        identity="second/source",
                    ),
                    _planned_node(
                        graph="second",
                        name="sink",
                        identity="second/sink",
                    ),
                ),
            },
            connections_by_graph={
                "first": (
                    _connection(
                        graph="first",
                    ),
                ),
                "second": (
                    _connection(
                        graph="second",
                    ),
                ),
            },
        )
    )

    edges = materialize_direct_edges(
        materialization,
        {
            "first/source": first_source,
            "first/sink": first_sink,
            "second/source": second_source,
            "second/sink": second_sink,
        },
        _mechanics(),
    )

    assert len(
        edges
    ) == 2

    assert (
        first_source.outputs["out"][0]
        is edges[0]
    )

    assert (
        first_sink.inputs["in"]
        is edges[0]
    )

    assert (
        second_source.outputs["out"][0]
        is edges[1]
    )

    assert (
        second_sink.inputs["in"]
        is edges[1]
    )


def test_direct_edges_apply_resolved_graph_memory_mechanics():
    source = _loaded(
        outputs={
            "out": "core.object",
        },
    )

    sink = _loaded(
        inputs={
            "in": "core.object",
        },
    )

    materialization = (
        SimpleNamespace(
            nodes_by_graph={
                "main": (
                    _planned_node(
                        graph="main",
                        name="source",
                        identity="main/source",
                    ),
                    _planned_node(
                        graph="main",
                        name="sink",
                        identity="main/sink",
                    ),
                ),
            },
            connections_by_graph={
                "main": (
                    _connection(
                        domain="auto",
                    ),
                ),
            },
        )
    )

    edges = materialize_direct_edges(
        materialization,
        {
            "main/source": source,
            "main/sink": sink,
        },
        _mechanics(
            default_domain="shared",
        ),
    )

    assert (
        edges[0]
        .memory_plan
        .selected
        == "shared"
    )


def test_direct_edges_are_returned_as_immutable_tuple():
    materialization = (
        SimpleNamespace(
            nodes_by_graph={},
            connections_by_graph={},
        )
    )

    edges = materialize_direct_edges(
        materialization,
        {},
        _mechanics(),
    )

    assert edges == ()
    assert isinstance(
        edges,
        tuple,
    )


def test_direct_preparation_preserves_materialized_edges(
    monkeypatch,
):
    from nodrix.system import (
        direct_preparation,
    )

    context = SimpleNamespace(
        backend="local",
        resources=(),
        applications=(),
        nodes=(),
        execution_context=None,
    )

    materialization = SimpleNamespace(
        context=context,
        nodes_by_graph={},
        connections_by_graph={},
    )

    sentinel_edge = object()
    calls = []

    monkeypatch.setattr(
        direct_preparation,
        "materialize_direct_context",
        lambda value: materialization,
    )

    def materialize_edges(
        value,
        nodes,
        mechanics,
    ):
        calls.append(
            (
                value,
                nodes,
                mechanics,
            )
        )
        return (
            sentinel_edge,
        )

    monkeypatch.setattr(
        direct_preparation,
        "materialize_direct_edges",
        materialize_edges,
    )

    prepared = (
        direct_preparation
        .prepare_direct_execution(
            context
        )
    )

    assert len(calls) == 1

    assert (
        calls[0][0]
        is materialization
    )

    assert (
        calls[0][1]
        == {}
    )

    assert (
        prepared.payload.edges
        == (
            sentinel_edge,
        )
    )

    assert (
        prepared.payload.edges[0]
        is sentinel_edge
    )
