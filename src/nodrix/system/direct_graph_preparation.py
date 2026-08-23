"""Direct graph queue preparation from canonical planned connections.

The canonical planner already resolved Connection execution policy.
This module only joins:

* already materialized direct nodes;
* PlannedConnection -> RuntimeEdgeBinding adaptation;
* already resolved runtime graph-memory mechanics;
* shared backend-neutral runtime edge materialization.

It does not parse definitions, resolve policy, lower to legacy manifests,
create another graph plan, or execute lifecycle methods.
"""

from __future__ import annotations

from collections.abc import Mapping

from nodrix.runtime_components import (
    LoadedNode,
)
from nodrix.runtime_edge_materialization import (
    RuntimeGraphMemorySettings,
    materialize_runtime_edge,
)
from nodrix.runtime_primitives import (
    RuntimeEdgeQueue,
)

from .direct_edge_materialization import (
    runtime_edge_binding_from_planned,
)
from .direct_materialization import (
    DirectRuntimeMaterialization,
)
from .runtime_mechanics import (
    ResolvedRuntimeMechanics,
)


def materialize_direct_edges(
    materialization: DirectRuntimeMaterialization,
    nodes: Mapping[
        str,
        LoadedNode,
    ],
    mechanics: ResolvedRuntimeMechanics,
) -> tuple[
    RuntimeEdgeQueue,
    ...,
]:
    """Materialize and wire direct queues in canonical graph order."""

    graph_memory = (
        RuntimeGraphMemorySettings(
            default_domain=(
                mechanics.graph_memory
                .default_domain
            ),
            forbid_implicit_copies=(
                mechanics.graph_memory
                .forbid_implicit_copies
            ),
        )
    )

    edges: list[
        RuntimeEdgeQueue
    ] = []

    for (
        graph,
        planned_connections,
    ) in (
        materialization
        .connections_by_graph
        .items()
    ):
        graph_nodes: dict[
            str,
            LoadedNode,
        ] = {}

        for planned_node in (
            materialization
            .nodes_by_graph
            .get(
                graph,
                (),
            )
        ):
            loaded = nodes.get(
                planned_node.id
            )

            if loaded is not None:
                graph_nodes[
                    planned_node.name
                ] = loaded

        for planned_connection in (
            planned_connections
        ):
            binding = (
                runtime_edge_binding_from_planned(
                    planned_connection
                )
            )

            result = (
                materialize_runtime_edge(
                    graph_nodes,
                    binding,
                    graph_memory,
                )
            )

            edges.append(
                result.edge
            )

    return tuple(
        edges
    )


__all__ = [
    "materialize_direct_edges",
]
