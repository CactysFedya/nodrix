from __future__ import annotations

from ..runtime_components import (
    LoadedApplication,
    LoadedResource,
)
from ..runtime_primitives import (
    RuntimeApplicationBinding,
    RuntimeResourceBinding,
)
from ..runtime_provider_materialization import (
    materialize_runtime_application,
    materialize_runtime_resource,
)
from .planning import (
    PlannedApplication,
    PlannedResource,
)


def runtime_resource_binding_from_planned(
    planned: PlannedResource,
) -> RuntimeResourceBinding:
    """Materialize canonical resource mechanics from an execution plan."""

    return RuntimeResourceBinding(
        uses=planned.uses,
        parameters=planned.parameters,
        bindings=planned.bindings,
    )


def runtime_application_binding_from_planned(
    planned: PlannedApplication,
) -> RuntimeApplicationBinding:
    """Materialize canonical application mechanics from an execution plan."""

    return RuntimeApplicationBinding(
        uses=planned.uses,
        parameters=planned.parameters,
        resource_bindings=planned.resources,
    )


def materialize_direct_resource(
    planned: PlannedResource,
) -> LoadedResource:
    """Instantiate one planned resource through the shared runtime path."""

    binding = runtime_resource_binding_from_planned(
        planned
    )

    return materialize_runtime_resource(
        planned.name,
        binding,
    )


def materialize_direct_application(
    planned: PlannedApplication,
) -> LoadedApplication:
    """Instantiate one planned application through the shared runtime path."""

    binding = runtime_application_binding_from_planned(
        planned
    )

    return materialize_runtime_application(
        planned.name,
        binding,
    )


__all__ = [
    "materialize_direct_application",
    "materialize_direct_resource",
    "runtime_application_binding_from_planned",
    "runtime_resource_binding_from_planned",
]
