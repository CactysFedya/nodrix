"""Direct runtime binding for canonical planned nodes.

The planner is the sole owner of execution-policy resolution.  This module
performs only a mechanical conversion from one fully resolved PlannedNode to
backend-neutral RuntimeNodeBinding state.

It must not read SystemExecutionContext, legacy extensions, Pipeline manifests,
or invent runtime defaults.
"""

from __future__ import annotations

from ..runtime_primitives import (
    RuntimeNodeBinding,
)
from .planning import PlannedNode


def runtime_node_binding_from_planned(
    planned: PlannedNode,
) -> RuntimeNodeBinding:
    """Convert one fully resolved PlannedNode to runtime mechanics."""

    policy = planned.execution

    return RuntimeNodeBinding(
        uses=planned.uses,
        parameters=planned.parameters,
        resource_bindings=planned.resources,
        synchronization_policy=(
            policy.synchronization.policy
        ),
        synchronization_tolerance_ns=(
            policy.synchronization.tolerance_ns
        ),
        synchronization_trigger_port=(
            policy.synchronization.trigger_port
        ),
        synchronization_optional_inputs=(
            policy.synchronization.optional_inputs
        ),
        failure_policy=(
            policy.failure.policy
        ),
        fallback_uses=(
            policy.failure.fallback_uses
        ),
        failure_max_restarts=(
            policy.failure.max_restarts
        ),
        failure_backoff_ms=(
            policy.failure.backoff_ms
        ),
        health_timeout_ns=(
            policy.health.timeout_ns
        ),
        health_on_timeout=(
            policy.health.on_timeout
        ),
        max_message_bytes=(
            policy.limits.max_message_bytes
        ),
        memory_limit_mb=(
            policy.limits.memory_limit_mb
        ),
        cpu_limit=(
            policy.limits.cpu_limit
        ),
        isolation=(
            policy.execution.isolation
        ),
        cpu_affinity=(
            policy.execution.cpu_affinity
        ),
        device=(
            policy.execution.device
        ),
        memory_inputs=(
            policy.memory.inputs
        ),
        memory_outputs=(
            policy.memory.outputs
        ),
    )


__all__ = [
    "runtime_node_binding_from_planned",
]
