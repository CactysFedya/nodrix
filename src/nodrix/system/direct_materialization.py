"""Direct runtime materialization for canonical local System execution.

The materializer builds cheap immutable lookup indexes over one already
resolved BackendContext.

It does NOT:

* parse a System Definition;
* rebuild a SystemExecutionPlan;
* lower to a PipelineManifest;
* create legacy node aliases;
* copy node/resource/application parameters;
* infer execution semantics missing from the planner;
* depend on HybridPipelineRuntime.

Values stored in the indexes are the exact Planned* objects already owned by
BackendContext.  The additional memory cost is therefore limited to lookup
tables and graph grouping structures rather than duplicate semantic objects.

This module remains internal while the direct local runtime is under
qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, TypeVar

from .backend import BackendContext
from .planning import (
    PlannedApplication,
    PlannedConnection,
    PlannedNode,
    PlannedResource,
    PlannedTarget,
)


_T = TypeVar("_T")


class DirectMaterializationError(RuntimeError):
    """Canonical BackendContext cannot be materialized without ambiguity."""


def _immutable_unique_index(
    items: Iterable[_T],
    *,
    key: Callable[[_T], str],
    kind: str,
) -> Mapping[str, _T]:
    index: dict[str, _T] = {}

    for item in items:
        identity = key(item)

        if not isinstance(identity, str) or not identity:
            raise DirectMaterializationError(
                f"{kind} identity must be a non-empty string"
            )

        if identity in index:
            raise DirectMaterializationError(
                f"duplicate {kind} identity: {identity!r}"
            )

        index[identity] = item

    return MappingProxyType(index)


def _immutable_graph_index(
    context: BackendContext,
    *,
    selector: Callable[
        [BackendContext, str],
        tuple[_T, ...],
    ],
) -> Mapping[str, tuple[_T, ...]]:
    graphs: dict[str, tuple[_T, ...]] = {}

    for graph in context.graph_names():
        if graph in graphs:
            raise DirectMaterializationError(
                f"duplicate graph identity: {graph!r}"
            )

        values = selector(
            context,
            graph,
        )

        graphs[graph] = tuple(values)

    return MappingProxyType(graphs)


@dataclass(
    frozen=True,
    slots=True,
)
class DirectRuntimeMaterialization:
    """Immutable runtime indexes over one canonical BackendContext.

    ``context`` remains the semantic source of truth.  All values reachable
    through the lookup mappings are references to the same Planned* instances
    already present in that context.
    """

    context: BackendContext

    targets_by_name: Mapping[
        str,
        PlannedTarget,
    ]

    resources_by_name: Mapping[
        str,
        PlannedResource,
    ]

    applications_by_name: Mapping[
        str,
        PlannedApplication,
    ]

    nodes_by_id: Mapping[
        str,
        PlannedNode,
    ]

    nodes_by_graph: Mapping[
        str,
        tuple[PlannedNode, ...],
    ]

    connections_by_graph: Mapping[
        str,
        tuple[PlannedConnection, ...],
    ]


def materialize_direct_context(
    context: BackendContext,
) -> DirectRuntimeMaterialization:
    """Build deterministic O(1) indexes without duplicating plan semantics."""

    targets_by_name = _immutable_unique_index(
        context.targets,
        key=lambda item: item.name,
        kind="target",
    )

    resources_by_name = _immutable_unique_index(
        context.resources,
        key=lambda item: item.name,
        kind="resource",
    )

    applications_by_name = _immutable_unique_index(
        context.applications,
        key=lambda item: item.name,
        kind="application",
    )

    nodes_by_id = _immutable_unique_index(
        context.nodes,
        key=lambda item: item.id,
        kind="node",
    )

    nodes_by_graph = _immutable_graph_index(
        context,
        selector=lambda value, graph: (
            value.nodes_for_graph(graph)
        ),
    )

    connections_by_graph = _immutable_graph_index(
        context,
        selector=lambda value, graph: (
            value.connections_for_graph(graph)
        ),
    )

    return DirectRuntimeMaterialization(
        context=context,
        targets_by_name=targets_by_name,
        resources_by_name=resources_by_name,
        applications_by_name=applications_by_name,
        nodes_by_id=nodes_by_id,
        nodes_by_graph=nodes_by_graph,
        connections_by_graph=connections_by_graph,
    )


__all__ = [
    "DirectMaterializationError",
    "DirectRuntimeMaterialization",
    "materialize_direct_context",
]
