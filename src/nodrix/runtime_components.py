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


@dataclass(slots=True)
class LoadedNode:
    name: str
    node: Node
    config: NodeConfig
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
