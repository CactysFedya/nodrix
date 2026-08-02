from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
import inspect
import json
import threading
import time
from typing import Any

from .manifest import (
    ApplicationConfig,
    EdgeConfig,
    NodeConfig,
    ProviderResourceConfig,
)
from .messages import Message
from .node import Node
from .telemetry import LatencyWindow
from .memory import MemoryPlan
from .cv_types import EncodedFrame, Frame, ManagedBuffer, Tensor
from .queueing import PythonBoundedQueue

try:
    from ._native_queue import BoundedQueue as _NativeBoundedQueue
except Exception:  # pragma: no cover
    _NativeBoundedQueue = None


_EOS = object()


@dataclass(slots=True)
class Envelope:
    message: Message
    enqueued_ns: int = field(default_factory=time.perf_counter_ns)


@dataclass(slots=True)
class Received:
    message: Message
    queue_wait_ns: int


@dataclass(slots=True)
class NodeStats:
    sample_capacity: int = 4096
    messages: int = 0
    errors: int = 0
    synchronization_drops: int = 0
    type_validations: int = 0
    process: LatencyWindow = field(init=False)
    queue_wait: LatencyWindow = field(init=False)
    end_to_end: LatencyWindow = field(init=False)

    def __post_init__(self) -> None:
        self.process = LatencyWindow(self.sample_capacity)
        self.queue_wait = LatencyWindow(self.sample_capacity)
        self.end_to_end = LatencyWindow(self.sample_capacity)

    def observe(self, duration_ns: int, inputs: dict[str, Received] | None = None) -> None:
        self.messages += 1
        self.process.observe(duration_ns)
        if inputs:
            now = time.perf_counter_ns()
            for received in inputs.values():
                self.queue_wait.observe(received.queue_wait_ns)
                self.end_to_end.observe(now - received.message.created_ns)

    def report(self, duration_seconds: float | None = None) -> dict[str, Any]:
        processing = self.process.report_ms()
        queue_wait = self.queue_wait.report_ms()
        end_to_end = self.end_to_end.report_ms()
        return {
            "messages": self.messages,
            "errors": self.errors,
            "synchronization_drops": self.synchronization_drops,
            "type_validations": self.type_validations,
            "rate_hz": self.messages / duration_seconds if duration_seconds and duration_seconds > 0 else 0.0,
            # Compatibility fields retained for 0.3 tooling.
            "mean_ms": processing["mean_ms"],
            "min_ms": processing["min_ms"],
            "max_ms": processing["max_ms"],
            "p50_ms": processing["p50_ms"],
            "p95_ms": processing["p95_ms"],
            "p99_ms": processing["p99_ms"],
            "total_ms": self.process.total_ns / 1e6,
            "processing": processing,
            "queue_wait": queue_wait,
            "end_to_end": end_to_end,
        }


class _PythonQueueFallback(PythonBoundedQueue):
    """Compatibility name retained for tests and third-party diagnostics."""


def _message_managed_buffer(message: Message) -> ManagedBuffer | None:
    payload = message.payload
    if isinstance(payload, ManagedBuffer):
        return payload
    if isinstance(payload, (Frame, Tensor, EncodedFrame)):
        return payload.buffer
    return None


def _estimate_message_bytes(message: Message) -> int:
    managed = _message_managed_buffer(message)
    if managed is not None:
        try:
            return int(managed.nbytes)
        except (TypeError, ValueError):
            return 0
    payload = message.payload
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return memoryview(payload).nbytes
    nbytes = getattr(payload, "nbytes", None)
    if nbytes is not None:
        try:
            return int(nbytes)
        except (TypeError, ValueError):
            pass
    try:
        return len(json.dumps(payload, default=str).encode("utf-8"))
    except Exception:
        return 0


class EdgeQueue:
    def __init__(self, edge: EdgeConfig, memory_plan: MemoryPlan | None = None) -> None:
        self.edge = edge
        self.memory_plan = memory_plan
        self.bytes = 0
        self.memory_types: dict[str, int] = defaultdict(int)
        queue_cls = _NativeBoundedQueue or _PythonQueueFallback
        self.queue = queue_cls(edge.queue.capacity, edge.queue.policy)

    def put(self, message: Message) -> bool:
        managed = _message_managed_buffer(message)
        if managed is not None:
            try:
                self.bytes += managed.nbytes
            except (TypeError, ValueError):
                pass
            self.memory_types[managed.memory_type.value] += 1
        return bool(self.queue.put(Envelope(message)))

    def put_control(self, item: Any) -> bool:
        method = getattr(self.queue, "put_control", None)
        return bool(method(item) if method is not None else self.queue.put(item))

    @staticmethod
    def _decode(item: Any) -> Received | Any:
        if isinstance(item, Envelope):
            return Received(item.message, time.perf_counter_ns() - item.enqueued_ns)
        return item

    def get(self) -> Received | Any:
        return self._decode(self.queue.get())

    def try_get(self) -> Received | Any:
        method = getattr(self.queue, "try_get", None)
        if method is not None:
            return self._decode(method())
        if self.queue.qsize() <= 0:
            return None
        return self._decode(self.queue.get())

    def close(self) -> None:
        self.queue.close()

    def report(self) -> dict[str, Any]:
        stats = dict(self.queue.stats())
        dropped = int(stats.get("dropped", 0))
        stale_skips = dropped if self.edge.queue.policy in {"latest", "drop_oldest"} else 0
        overflow_drops = dropped if self.edge.queue.policy == "drop_newest" else 0
        return {
            "source": self.edge.source,
            "target": self.edge.target,
            "enqueued": int(stats.get("enqueued", 0)),
            "dequeued": int(stats.get("dequeued", 0)),
            "dropped": dropped,
            "stale_skips": stale_skips,
            "overflow_drops": overflow_drops,
            "max_depth": int(stats.get("max_depth", 0)),
            "depth": int(stats.get("depth", 0)),
            "capacity": self.edge.queue.capacity,
            "policy": self.edge.queue.policy,
            "bytes": self.bytes,
            "observed_memory": dict(self.memory_types),
            "memory": None if self.memory_plan is None else self.memory_plan.as_dict(),
        }


@dataclass(slots=True)
class LoadedNode:
    name: str
    node: Node
    config: NodeConfig
    inputs: dict[str, EdgeQueue] = field(default_factory=dict)
    outputs: dict[str, list[EdgeQueue]] = field(default_factory=lambda: defaultdict(list))
    stats: NodeStats | None = None
    ready: threading.Event = field(default_factory=threading.Event)
    latest_inputs: dict[str, Received] = field(default_factory=dict)
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


class _AsyncBridge:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None

    def resolve(self, value: Any) -> Any:
        if not inspect.isawaitable(value):
            return value
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
        return self.loop.run_until_complete(value)

    def close(self) -> None:
        if self.loop is not None:
            self.loop.close()
            self.loop = None
