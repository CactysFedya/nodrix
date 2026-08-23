"""Mechanical PlannedConnection to runtime-edge binding adaptation.

This module does not resolve execution policy, inspect execution context,
plan memory, create queues, wire graph nodes, or perform lifecycle work.

All execution semantics must already be present in PlannedConnection.
"""

from __future__ import annotations

from nodrix.runtime_edge_materialization import (
    RuntimeEdgeBinding,
)
from nodrix.runtime_primitives import (
    RuntimeQueueBinding,
)

from .planning import (
    PlannedConnection,
)


def runtime_edge_binding_from_planned(
    planned: PlannedConnection,
) -> RuntimeEdgeBinding:
    """Adapt one canonical planned connection to runtime mechanics."""

    execution = planned.execution

    return RuntimeEdgeBinding(
        queue=RuntimeQueueBinding(
            source=planned.source,
            target=planned.target,
            capacity=(
                execution.queue.capacity
            ),
            policy=(
                execution.queue.policy
            ),
        ),
        memory_domain=(
            execution.memory.domain
        ),
        allow_copy=(
            execution.memory.allow_copy
        ),
    )


__all__ = [
    "runtime_edge_binding_from_planned",
]
