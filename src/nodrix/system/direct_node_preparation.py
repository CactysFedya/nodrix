"""Direct preparation of canonical planned nodes.

The planner already owns node execution-policy resolution. This module joins
one PlannedNode with backend-owned physical execution state and explicitly
resolved runtime mechanics, then reuses the backend-neutral runtime node
materialization stack.

Graph queues, edge wiring, lifecycle execution, transports, and Run
persistence are intentionally outside this module.
"""

from __future__ import annotations

from ..runtime_components import LoadedNode
from ..runtime_node_isolation import (
    RuntimeProcessIsolationSettings,
    materialize_runtime_node_isolation,
)
from ..runtime_node_loading import (
    load_runtime_node,
)
from ..runtime_node_materialization import (
    validate_runtime_node_materialization,
    validate_runtime_node_parameters,
)
from ..runtime_primitives import NodeStats
from .direct_environment import (
    DirectExecutionEnvironment,
)
from .direct_node_materialization import (
    runtime_node_binding_from_planned,
)
from .planning import PlannedNode
from .runtime_mechanics import (
    ResolvedRuntimeMechanics,
)


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


def _process_isolation_settings(
    planned: PlannedNode,
    *,
    environment: DirectExecutionEnvironment,
    mechanics: ResolvedRuntimeMechanics,
) -> RuntimeProcessIsolationSettings:
    process = mechanics.process

    if process is None:
        raise DirectNodePreparationError(
            planned.id,
            (
                "direct process isolation requires "
                "canonical process-memory settings "
                "at runtime.mechanics.process"
            ),
        )

    input_pool = process.input_pool
    output_pool = process.output_pool

    if (
        input_pool.threshold
        != output_pool.threshold
    ):
        raise DirectNodePreparationError(
            planned.id,
            (
                "direct process isolation currently "
                "requires matching input_pool.threshold "
                "and output_pool.threshold"
            ),
        )

    return RuntimeProcessIsolationSettings(
        base_dir=environment.base_dir,
        input_block_size=(
            input_pool.block_size
        ),
        input_capacity=(
            input_pool.capacity
        ),
        output_block_size=(
            output_pool.block_size
        ),
        output_capacity=(
            output_pool.capacity
        ),
        threshold=(
            input_pool.threshold
        ),
    )


def _node_stats(
    mechanics: ResolvedRuntimeMechanics,
) -> NodeStats | None:
    sample_capacity = (
        mechanics.telemetry_sample_capacity
    )

    if sample_capacity is None:
        return None

    return NodeStats(
        sample_capacity
    )


def materialize_direct_node(
    planned: PlannedNode,
    *,
    environment: DirectExecutionEnvironment,
    mechanics: ResolvedRuntimeMechanics = (
        ResolvedRuntimeMechanics()
    ),
) -> LoadedNode:
    """Materialize one canonical node without graph wiring or lifecycle."""

    binding = (
        runtime_node_binding_from_planned(
            planned
        )
    )

    process_settings = None

    if binding.isolation == "process":
        process_settings = (
            _process_isolation_settings(
                planned,
                environment=environment,
                mechanics=mechanics,
            )
        )
    elif binding.isolation != "in_process":
        raise DirectNodePreparationError(
            planned.id,
            (
                "unsupported direct node isolation: "
                f"{binding.isolation!r}"
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

    if process_settings is not None:
        node = (
            materialize_runtime_node_isolation(
                name=planned.id,
                node=node,
                binding=binding,
                settings=process_settings,
            )
        )

    return LoadedNode(
        name=planned.id,
        node=node,
        binding=binding,
        stats=_node_stats(
            mechanics
        ),
    )


__all__ = [
    "DirectNodePreparationError",
    "materialize_direct_node",
]
