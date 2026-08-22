"""Direct preparation of canonical planned nodes.

The planner already owns node execution-policy resolution. This module joins
one PlannedNode with the backend-owned physical DirectExecutionEnvironment and
reuses the backend-neutral runtime node materialization stack.

Graph queues, edge wiring, lifecycle execution, transports, Run persistence,
and process-memory policy are intentionally outside this module.
"""

from __future__ import annotations

from ..runtime_components import LoadedNode
from ..runtime_node_loading import load_runtime_node
from ..runtime_node_materialization import (
    validate_runtime_node_materialization,
    validate_runtime_node_parameters,
)
from .direct_environment import (
    DirectExecutionEnvironment,
)
from .direct_node_materialization import (
    runtime_node_binding_from_planned,
)
from .planning import PlannedNode


class DirectNodePreparationError(RuntimeError):
    """A canonical planned node cannot be prepared directly."""

    def __init__(
        self,
        node_id: str,
        message: str,
    ) -> None:
        self.node_id = node_id
        self.message = message

        super().__init__(
            f"Node {node_id!r}: {message}"
        )


def materialize_direct_node(
    planned: PlannedNode,
    *,
    environment: DirectExecutionEnvironment,
) -> LoadedNode:
    """Materialize one canonical in-process node without graph wiring."""

    binding = (
        runtime_node_binding_from_planned(
            planned
        )
    )

    if binding.isolation != "in_process":
        raise DirectNodePreparationError(
            planned.id,
            (
                "direct process isolation is not "
                "available until canonical "
                "process-memory settings are resolved"
            ),
        )

    validate_runtime_node_parameters(
        binding
    )

    node = load_runtime_node(
        binding.uses,
        dict(
            binding.parameters
        ),
        base_dir=environment.base_dir,
    )

    validate_runtime_node_materialization(
        name=planned.id,
        node=node,
        binding=binding,
        declared_inputs=planned.inputs,
        declared_outputs=planned.outputs,
        base_dir=environment.base_dir,
    )

    return LoadedNode(
        name=planned.id,
        node=node,
        binding=binding,
        stats=None,
    )


__all__ = [
    "DirectNodePreparationError",
    "materialize_direct_node",
]
