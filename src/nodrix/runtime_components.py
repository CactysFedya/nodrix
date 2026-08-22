"""Legacy runtime materialization adapters.

Generic message/queue/statistics primitives live in runtime_primitives.
This module retains the Pipeline 2.x configuration adapters and loaded
component records while the direct System runtime is introduced.

New backend-neutral runtime code must import generic mechanics from
runtime_primitives rather than introducing PipelineManifest configuration
dependencies here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import threading
from typing import Any

from .manifest import (
    ApplicationConfig,
    EdgeConfig,
    NodeConfig,
    ProviderResourceConfig,
)
from .memory import MemoryPlan
from .node import Node
from .runtime_primitives import (
    _EOS,
    _PythonQueueFallback,
    _estimate_message_bytes,
    _message_managed_buffer,
    Envelope,
    NodeStats,
    Received,
    RuntimeAsyncBridge as _AsyncBridge,
    RuntimeEdgeQueue,
    RuntimeNodeBinding,
    RuntimeQueueBinding,
)


class EdgeQueue(
    RuntimeEdgeQueue
):
    """Pipeline 2.x EdgeConfig adapter over the generic runtime queue."""

    def __init__(
        self,
        edge: EdgeConfig,
        memory_plan: MemoryPlan | None = None,
    ) -> None:
        self.edge = edge

        super().__init__(
            RuntimeQueueBinding(
                source=edge.source,
                target=edge.target,
                capacity=(
                    edge.queue.capacity
                ),
                policy=(
                    edge.queue.policy
                ),
            ),
            memory_plan,
        )



def runtime_node_binding_from_config(
    config: NodeConfig,
) -> RuntimeNodeBinding:
    """Adapt validated Pipeline 2.x node configuration to runtime mechanics.

    This is an explicit compatibility boundary.  Runtime consumers downstream
    of this function must not need Pipeline NodeConfig semantics.
    """

    return RuntimeNodeBinding(
        uses=config.uses,
        parameters=config.parameters,
        resource_bindings=config.bindings,
        synchronization_policy=(
            config.synchronization.policy
        ),
        synchronization_tolerance_ns=int(
            config.synchronization.tolerance_ms
            * 1_000_000
        ),
        synchronization_trigger_port=(
            config.synchronization.trigger_port
        ),
        synchronization_optional_inputs=tuple(
            config.synchronization.optional_inputs
        ),
        failure_policy=(
            config.failure.policy
        ),
        fallback_uses=(
            config.failure.fallback_uses
        ),
        failure_max_restarts=(
            config.failure.max_restarts
        ),
        failure_backoff_ms=(
            config.failure.backoff_ms
        ),
        health_timeout_ns=(
            int(
                config.health.timeout_ms
            )
            * 1_000_000
        ),
        health_on_timeout=(
            config.health.on_timeout
        ),
        max_message_bytes=(
            config.resources.max_message_bytes
        ),
        memory_limit_mb=(
            config.resources.memory_limit_mb
        ),
        cpu_limit=(
            config.resources.cpu_limit
        ),
        isolation=(
            config.execution.isolation
        ),
        cpu_affinity=tuple(
            config.execution.cpu_affinity
        ),
        device=(
            config.execution.device
        ),
        memory_inputs=(
            config.memory.inputs
        ),
        memory_outputs=(
            config.memory.outputs
        ),
    )

@dataclass(slots=True)
class LoadedNode:
    name: str
    node: Node
    binding: RuntimeNodeBinding
    inputs: dict[
        str,
        EdgeQueue,
    ] = field(
        default_factory=dict
    )
    outputs: dict[
        str,
        list[EdgeQueue],
    ] = field(
        default_factory=(
            lambda: defaultdict(
                list
            )
        )
    )
    stats: NodeStats | None = None
    ready: threading.Event = field(
        default_factory=(
            threading.Event
        )
    )
    latest_inputs: dict[
        str,
        Received,
    ] = field(
        default_factory=dict
    )
    watchdog_triggered: bool = False
    fallback_active: bool = False


@dataclass(slots=True)
class LoadedSession:
    name: str
    uses: str
    instance: Any
    opened: bool = False


@dataclass(slots=True)
class LoadedResource:
    name: str
    uses: str
    instance: Any
    config: ProviderResourceConfig
    opened: bool = False


@dataclass(slots=True)
class LoadedApplication:
    name: str
    uses: str
    instance: Any
    config: ApplicationConfig
    configured: bool = False
    started: bool = False
    completed: bool = False
