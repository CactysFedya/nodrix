"""Backend-neutral realization of node process isolation.

The isolation policy is already resolved in RuntimeNodeBinding.  This module
only realizes that policy using explicit engine inputs.

It does not read Pipeline manifests, System plans, execution-context defaults,
or graph topology.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import RuntimeGraphError
from .node import Node, SourceNode
from .process_host import (
    ProcessNodeProxy,
    ProcessSourceProxy,
)
from .runtime_primitives import (
    RuntimeNodeBinding,
)


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeProcessIsolationSettings:
    """Concrete engine inputs required by process-isolated nodes."""

    base_dir: Path
    input_block_size: int
    input_capacity: int
    output_block_size: int
    output_capacity: int
    threshold: int


def materialize_runtime_node_isolation(
    *,
    name: str,
    node: Node,
    binding: RuntimeNodeBinding,
    settings: RuntimeProcessIsolationSettings,
) -> Node:
    """Realize the already-resolved isolation policy for one node."""

    if binding.isolation == "in_process":
        return node

    if binding.isolation != "process":
        raise RuntimeGraphError(
            f"Node {name!r}: unsupported "
            f"isolation mode "
            f"{binding.isolation!r}"
        )

    proxy_class = (
        ProcessSourceProxy
        if isinstance(
            node,
            SourceNode,
        )
        else ProcessNodeProxy
    )

    return proxy_class(
        name=name,
        uses=binding.uses,
        base_dir=settings.base_dir,
        parameters=dict(
            binding.parameters
        ),
        input_types=dict(
            node.input_types
        ),
        output_types=dict(
            node.output_types
        ),
        input_memory=dict(
            getattr(
                node,
                "input_memory",
                {},
            )
        ),
        output_memory=dict(
            getattr(
                node,
                "output_memory",
                {},
            )
        ),
        optional_inputs=set(
            getattr(
                node,
                "optional_inputs",
                frozenset(),
            )
        ),
        block_size=(
            settings.input_block_size
        ),
        capacity=(
            settings.input_capacity
        ),
        output_block_size=(
            settings.output_block_size
        ),
        output_capacity=(
            settings.output_capacity
        ),
        threshold=settings.threshold,
        failure_policy=(
            binding.failure_policy
        ),
        max_restarts=(
            binding.failure_max_restarts
        ),
        backoff_ms=(
            binding.failure_backoff_ms
        ),
        cpu_affinity=list(
            binding.cpu_affinity
        ),
        device=binding.device,
        max_message_bytes=(
            binding.max_message_bytes
        ),
        memory_limit_mb=(
            binding.memory_limit_mb
        ),
        cpu_limit=(
            binding.cpu_limit
        ),
    )


__all__ = [
    "RuntimeProcessIsolationSettings",
    "materialize_runtime_node_isolation",
]
