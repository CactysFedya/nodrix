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

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..runtime_components import (
    LoadedApplication,
    LoadedResource,
)
from .backend import (
    BackendContext,
    PreparedExecution,
)
from .direct_materialization import (
    DirectRuntimeMaterialization,
    materialize_direct_context,
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

    @property
    def context(self) -> BackendContext:
        return self.materialization.context


def prepare_direct_execution(
    context: BackendContext,
) -> PreparedExecution:
    """Prepare resources and applications directly from BackendContext."""

    materialization = materialize_direct_context(
        context
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

    payload = DirectPreparedRuntime(
        materialization=materialization,
        resources=resources,
        applications=applications,
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
