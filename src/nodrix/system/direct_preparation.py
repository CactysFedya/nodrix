"""Preparation state for direct canonical System execution.

This module converts one already-resolved BackendContext into backend-owned
runtime state.

It does not introduce another execution plan.  DirectRuntimeMaterialization
remains an immutable index over the canonical BackendContext, while
DirectPreparedRuntime owns instantiated runtime components created from that
materialization.

No resource/application lifecycle method is invoked here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from ..runtime_primitives import (
    RuntimeEdgeQueue,
)
from ..runtime_components import (
    LoadedApplication,
    LoadedNode,
    LoadedResource,
)
from .backend import (
    BackendContext,
    PreparedExecution,
)
from .direct_environment import (
    DirectExecutionEnvironment,
)
from .direct_node_preparation import (
    DirectNodePreparationError,
    materialize_direct_node,
)
from .direct_graph_preparation import (
    materialize_direct_edges,
)
from .direct_materialization import (
    DirectRuntimeMaterialization,
    materialize_direct_context,
)
from .runtime_mechanics import (
    ResolvedRuntimeMechanics,
    resolve_runtime_mechanics,
)
from .direct_provider_materialization import (
    materialize_direct_application,
    materialize_direct_resource,
)


@dataclass(
    frozen=True,
    slots=True,
)
class DirectPreparedRuntime:
    """Instantiated backend-owned state for one prepared direct execution."""

    materialization: DirectRuntimeMaterialization

    resources: Mapping[
        str,
        LoadedResource,
    ]

    applications: Mapping[
        str,
        LoadedApplication,
    ]

    environment: (
        DirectExecutionEnvironment
        | None
    ) = None

    nodes: Mapping[
        str,
        LoadedNode,
    ] = field(
        default_factory=dict
    )

    mechanics: (
        ResolvedRuntimeMechanics
    ) = field(
        default_factory=ResolvedRuntimeMechanics
    )

    edges: tuple[
        RuntimeEdgeQueue,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resources",
            MappingProxyType(
                dict(
                    self.resources
                )
            ),
        )

        object.__setattr__(
            self,
            "applications",
            MappingProxyType(
                dict(
                    self.applications
                )
            ),
        )

        object.__setattr__(
            self,
            "nodes",
            MappingProxyType(
                dict(
                    self.nodes
                )
            ),
        )

        object.__setattr__(
            self,
            "edges",
            tuple(
                self.edges
            ),
        )

    @property
    def context(self) -> BackendContext:
        return self.materialization.context


def prepare_direct_execution(
    context: BackendContext,
    *,
    environment: (
        DirectExecutionEnvironment
        | None
    ) = None,
) -> PreparedExecution:
    """Prepare providers and nodes directly from BackendContext."""

    materialization = materialize_direct_context(
        context
    )

    mechanics = resolve_runtime_mechanics(
        context.execution_context
    )

    planned_nodes = tuple(
        context.nodes
    )

    if (
        planned_nodes
        and environment is None
    ):
        raise DirectNodePreparationError(
            planned_nodes[0].id,
            (
                "direct node preparation requires "
                "a backend-owned "
                "DirectExecutionEnvironment"
            ),
        )


    resources: dict[
        str,
        LoadedResource,
    ] = {}

    for planned in context.resources:
        resources[
            planned.name
        ] = materialize_direct_resource(
            planned
        )

    applications: dict[
        str,
        LoadedApplication,
    ] = {}

    for planned in context.applications:
        applications[
            planned.name
        ] = materialize_direct_application(
            planned
        )

    nodes: dict[
        str,
        LoadedNode,
    ] = {}

    if environment is not None:
        for planned in planned_nodes:
            nodes[
                planned.id
            ] = materialize_direct_node(
                planned,
                environment=environment,
                mechanics=mechanics,
            )

    edges = materialize_direct_edges(
        materialization,
        nodes,
        mechanics,
    )

    payload = DirectPreparedRuntime(
        materialization=materialization,
        resources=resources,
        applications=applications,
        environment=environment,
        nodes=nodes,
        mechanics=mechanics,
        edges=edges,
    )

    return PreparedExecution(
        backend=context.backend,
        context=context,
        payload=payload,
    )


__all__ = [
    "DirectPreparedRuntime",
    "prepare_direct_execution",
]
