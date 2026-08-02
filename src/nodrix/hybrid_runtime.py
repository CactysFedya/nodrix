from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import inspect
import json
import os
import platform
import sys
from pathlib import Path
import queue as pyqueue
import threading
import time
from typing import Any, Callable

from .cv_types import TYPE_REGISTRY, normalize_payload
from .errors import RuntimeGraphError
from .execution_plan import compile_execution_plan, write_execution_plan
from .manifest import EdgeConfig, NodeConfig, PipelineManifest, dump_manifest_redacted, dump_source_manifest_redacted
from .messages import Message
from .native_plugin import NativePluginNode
from .node import Node, NodeContext, SourceNode
from .node_docs import validate_parameters
from .process_host import ProcessNodeProxy, ProcessSourceProxy
from .provenance import write_run_provenance
from .observability import EventTracer
from .registry import load_node_class
from .providers import (
    load_provider_session,
    provider_for_link,
    provider_for_session,
)
from .provider_validation import validate_provider_parameters
from .session import SessionContext
from .telemetry import LatencyWindow
from .memory import MemoryPlan, MemoryRequirement, plan_memory, requirement_for_port
from .cv_types import EncodedFrame, Frame, ManagedBuffer, Tensor
from .streams import StreamPublisher
from .metrics import MetricsRecorder
from .lockfile import build_lock
from .lifecycle import HealthStatus, LifecycleState
from .packages import resolve_package_node
from .resources import ResourceSampler, system_snapshot

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


class _PythonQueueFallback:
    def __init__(self, capacity: int, policy: str) -> None:
        self._queue: pyqueue.Queue[Any] = pyqueue.Queue(capacity)
        self._policy = policy
        self._closed = False
        self._stats = {"enqueued": 0, "dequeued": 0, "dropped": 0, "max_depth": 0}

    def put(self, item: Any) -> bool:
        if self._closed:
            return False
        if self._policy == "block":
            self._queue.put(item)
        elif self._policy == "drop_newest":
            try:
                self._queue.put_nowait(item)
            except pyqueue.Full:
                self._stats["dropped"] += 1
                return False
        else:
            if self._policy == "latest":
                while True:
                    try:
                        self._queue.get_nowait()
                        self._stats["dropped"] += 1
                    except pyqueue.Empty:
                        break
            elif self._queue.full():
                try:
                    self._queue.get_nowait()
                    self._stats["dropped"] += 1
                except pyqueue.Empty:
                    pass
            self._queue.put(item)
        self._stats["enqueued"] += 1
        self._stats["max_depth"] = max(self._stats["max_depth"], self._queue.qsize())
        return True

    def put_control(self, item: Any) -> bool:
        if self._closed:
            return False
        self._queue.put(item)
        self._stats["enqueued"] += 1
        self._stats["max_depth"] = max(self._stats["max_depth"], self._queue.qsize())
        return True

    def get(self) -> Any:
        while True:
            if self._closed and self._queue.empty():
                return None
            try:
                item = self._queue.get(timeout=0.1)
                self._stats["dequeued"] += 1
                return item
            except pyqueue.Empty:
                continue

    def try_get(self) -> Any:
        try:
            item = self._queue.get_nowait()
        except pyqueue.Empty:
            return None
        self._stats["dequeued"] += 1
        return item

    def close(self) -> None:
        self._closed = True

    def qsize(self) -> int:
        return self._queue.qsize()

    def stats(self) -> dict[str, int]:
        return {**self._stats, "depth": self._queue.qsize()}


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


class HybridPipelineRuntime:
    """Nodrix 2.x unified executor.

    Python nodes and C++ processor/sink plugins share the same native bounded
    queues, typed messages, lifecycle, synchronization, telemetry, and zero-copy
    buffer protocol.    """

    def __init__(
        self,
        manifest: PipelineManifest,
        manifest_path: Path,
        run_root: Path | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path.resolve()
        self.base_dir = self.manifest_path.parent
        self.run_root = (run_root or self.base_dir / ".nodrix" / "runs").resolve()
        self.nodes: dict[str, LoadedNode] = {}
        self.sessions: dict[str, LoadedSession] = {}
        self.edges: list[EdgeQueue] = []
        self._start = threading.Event()
        self._stop = threading.Event()
        self._interrupted = threading.Event()
        self._errors: list[tuple[str, BaseException]] = []
        self._error_lock = threading.Lock()
        self._validated_ports: set[tuple[str, str]] = set()
        self._stream_exports: list[dict[str, Any]] = []
        self._stream_publisher: StreamPublisher | None = None
        self._memory_plans: dict[tuple[str, str], MemoryPlan] = {}
        self._resource_sampler = ResourceSampler()
        self._last_node_resources: dict[str, dict[str, Any]] = {}
        self._event_callback = event_callback
        self._event_lock = threading.Lock()
        self._events_path: Path | None = None
        self._run_started_ns: int | None = None
        self._run_id = ""
        self._tracer: EventTracer | None = None
        self._recording_writer: Any | None = None
        self._recording_lock = threading.Lock()
        self._recording_streams = set(self.manifest.recording.streams)
        self._metrics_recorder: MetricsRecorder | None = None
        self._worker_threads: list[threading.Thread] = []
        self._watchdog_thread: threading.Thread | None = None
        self._nodes_closed = False

    def _emit_event(self, kind: str, **payload: Any) -> None:
        event = {"kind": kind, "time_ns": time.time_ns(), **payload}
        if self._events_path is not None:
            try:
                encoded = json.dumps(event, ensure_ascii=False, default=str)
                with self._event_lock, self._events_path.open("a", encoding="utf-8") as stream:
                    stream.write(encoded + "\n")
            except Exception:
                # Diagnostics must never destabilize the data plane.
                pass
        if self._event_callback is not None:
            try:
                self._event_callback(event)
            except Exception:
                pass
        if self._tracer is not None:
            try:
                self._tracer.emit(kind, event)
            except Exception:
                pass

    @property
    def native_queue_enabled(self) -> bool:
        return _NativeBoundedQueue is not None

    def _load_node(self, uses: str, parameters: dict[str, Any]) -> Node:
        uses = resolve_package_node(uses)
        if uses.startswith("native:"):
            body = uses.removeprefix("native:")
            if "#" not in body:
                raise RuntimeGraphError("Native plugin must use native:/path/library#node-type")
            library, node_type = body.rsplit("#", 1)
            path = Path(library).expanduser()
            if not path.is_absolute():
                path = (self.base_dir / path).resolve()
            if not path.exists():
                raise RuntimeGraphError(f"Native plugin library does not exist: {path}")
            return NativePluginNode(path, node_type, parameters)
        if uses.startswith("native."):
            raise RuntimeGraphError(
                "Built-in native.* nodes run in engine: native. Use a native:/path/plugin#type reference inside a unified Python/C++ graph."
            )
        cls = load_node_class(uses, base_dir=self.base_dir)
        return cls(parameters)

    def build(self) -> None:
        self.nodes.clear()
        self.sessions.clear()
        self.edges.clear()
        self._stream_exports.clear()
        self._memory_plans.clear()
        for name, config in self.manifest.sessions.items():
            resolved_session = provider_for_session(
                config.uses,
                include_legacy=False,
            )
            if resolved_session is None:
                raise RuntimeGraphError(
                    f"Unknown provider session {config.uses!r}"
                )
            _candidate, session_descriptor = resolved_session
            validate_provider_parameters(
                session_descriptor.parameters_schema,
                config.parameters,
                location=f"sessions.{name}.parameters",
            )
            session_class = load_provider_session(config.uses)
            if session_class is None:
                raise RuntimeGraphError(
                    f"Unknown provider session {config.uses!r}"
                )
            try:
                instance = session_class(config.parameters)
            except TypeError:
                instance = session_class(parameters=config.parameters)
            self.sessions[name] = LoadedSession(
                name=name,
                uses=config.uses,
                instance=instance,
            )
        for index, link in enumerate(self.manifest.links):
            resolved_link = provider_for_link(
                link.uses,
                include_legacy=False,
            )
            if resolved_link is None:
                raise RuntimeGraphError(
                    f"Unknown provider link {link.uses!r}"
                )
            _candidate, link_descriptor = resolved_link
            validate_provider_parameters(
                link_descriptor.parameters_schema,
                link.parameters,
                location=f"links[{index}].parameters",
            )
        sample_capacity = self.manifest.runtime.telemetry_samples
        for name, config in self.manifest.nodes.items():
            validate_parameters(config.uses, config.parameters)
            node = self._load_node(config.uses, config.parameters)
            if config.failure.policy == "fallback_node":
                if config.execution.isolation != "in_process":
                    raise RuntimeGraphError(
                        f"Node {name!r}: fallback_node currently requires in_process isolation"
                    )
                assert config.failure.fallback_uses is not None
                validate_parameters(
                    config.failure.fallback_uses,
                    config.parameters,
                )
                fallback = self._load_node(
                    config.failure.fallback_uses,
                    config.parameters,
                )
                if (
                    dict(fallback.input_types) != dict(node.input_types)
                    or dict(fallback.output_types) != dict(node.output_types)
                ):
                    raise RuntimeGraphError(
                        f"Node {name!r}: fallback node ports must exactly match the primary node"
                    )
            if config.execution.isolation == "process":
                original_is_source = isinstance(node, SourceNode)
                shared = self.manifest.runtime.memory.shared_pool
                output_shared = self.manifest.runtime.memory.process_output_pool
                proxy_cls = ProcessSourceProxy if original_is_source else ProcessNodeProxy
                node = proxy_cls(
                    name=name,
                    uses=config.uses,
                    base_dir=self.base_dir,
                    parameters=config.parameters,
                    input_types=dict(node.input_types),
                    output_types=dict(node.output_types),
                    input_memory=dict(getattr(node, "input_memory", {})),
                    output_memory=dict(getattr(node, "output_memory", {})),
                    optional_inputs=set(getattr(node, "optional_inputs", frozenset())),
                    block_size=shared.block_size,
                    capacity=shared.capacity,
                    output_block_size=output_shared.block_size,
                    output_capacity=output_shared.capacity,
                    threshold=shared.threshold,
                    failure_policy=config.failure.policy,
                    max_restarts=config.failure.max_restarts,
                    backoff_ms=config.failure.backoff_ms,
                    cpu_affinity=config.execution.cpu_affinity,
                    device=config.execution.device,
                    memory_limit_mb=config.resources.memory_limit_mb,
                    cpu_limit=config.resources.cpu_limit,
                )
            if config.inputs and dict(config.inputs) != dict(node.input_types):
                raise RuntimeGraphError(
                    f"Node {name!r} declared inputs {config.inputs}, but {config.uses!r} provides {node.input_types}"
                )
            if config.outputs and dict(config.outputs) != dict(node.output_types):
                raise RuntimeGraphError(
                    f"Node {name!r} declared outputs {config.outputs}, but {config.uses!r} provides {node.output_types}"
                )
            if config.synchronization.trigger_port and config.synchronization.trigger_port not in node.input_types:
                raise RuntimeGraphError(
                    f"Node {name!r} synchronization trigger_port {config.synchronization.trigger_port!r} is not an input"
                )
            implementation_optional = set(getattr(node, "optional_inputs", ()))
            configured_optional = set(config.synchronization.optional_inputs)
            unknown_optional = sorted(implementation_optional - set(node.input_types))
            if unknown_optional:
                raise RuntimeGraphError(
                    f"Node {name!r} declares unknown optional inputs: {unknown_optional}"
                )
            unknown_configured = sorted(configured_optional - set(node.input_types))
            if unknown_configured:
                raise RuntimeGraphError(
                    f"Node {name!r} configures unknown optional inputs: {unknown_configured}"
                )
            unsupported_optional = sorted(configured_optional - implementation_optional)
            if unsupported_optional:
                raise RuntimeGraphError(
                    f"Node {name!r} cannot make required inputs optional: {unsupported_optional}"
                )
            self.nodes[name] = LoadedNode(
                name=name,
                node=node,
                config=config,
                stats=NodeStats(sample_capacity),
            )

        for edge_config in self.manifest.edges:
            src_name, src_port = edge_config.source.split(".", 1)
            dst_name, dst_port = edge_config.target.split(".", 1)
            if src_name not in self.nodes or dst_name not in self.nodes:
                raise RuntimeGraphError(f"Edge references unknown node: {edge_config.source} -> {edge_config.target}")
            source = self.nodes[src_name].node
            target = self.nodes[dst_name].node
            if src_port not in source.output_types:
                raise RuntimeGraphError(f"Unknown output port: {edge_config.source}")
            if dst_port not in target.input_types:
                raise RuntimeGraphError(f"Unknown input port: {edge_config.target}")
            source_type = source.output_types[src_port]
            target_type = target.input_types[dst_port]
            if not self._types_compatible(source_type, target_type):
                raise RuntimeGraphError(
                    f"Type mismatch {edge_config.source} ({source_type}) -> {edge_config.target} ({target_type})"
                )
            if dst_port in self.nodes[dst_name].inputs:
                raise RuntimeGraphError(f"Input port already connected: {edge_config.target}")
            source_memory_map = {**dict(getattr(source, "output_memory", {})), **dict(self.nodes[src_name].config.memory.outputs)}
            target_memory_map = {**dict(getattr(target, "input_memory", {})), **dict(self.nodes[dst_name].config.memory.inputs)}
            source_requirement = requirement_for_port(source_memory_map, src_port)
            target_requirement = requirement_for_port(target_memory_map, dst_port)
            if self.nodes[src_name].config.execution.isolation == "process":
                source_requirement = MemoryRequirement(("shared",), preferred="shared")
            if self.nodes[dst_name].config.execution.isolation == "process":
                target_requirement = MemoryRequirement(("shared",), preferred="shared")
            allow_copy = edge_config.memory.allow_copy and not self.manifest.runtime.memory.forbid_implicit_copies
            forced_memory = edge_config.memory.domain
            if forced_memory == "auto" and self.manifest.runtime.memory.default_domain != "auto":
                forced_memory = self.manifest.runtime.memory.default_domain
            memory_plan = plan_memory(
                source_requirement, target_requirement, forced=forced_memory, allow_copy=allow_copy
            )
            if (
                memory_plan.adapter == "host_copy_to_shared"
                and self.nodes[dst_name].config.execution.isolation != "process"
            ):
                memory_plan = replace(
                    memory_plan,
                    runtime_supported=False,
                    reason="in-process CPU-to-shared conversion needs an explicit adapter node",
                )
            if not memory_plan.runtime_supported and (not allow_copy or memory_plan.copies):
                raise RuntimeGraphError(
                    f"Unsupported memory path {edge_config.source} -> {edge_config.target}: "
                    f"{memory_plan.reason} ({memory_plan.source} -> {memory_plan.target})"
                )
            self._memory_plans[(edge_config.source, edge_config.target)] = memory_plan
            edge = EdgeQueue(edge_config, memory_plan)
            self.edges.append(edge)
            self.nodes[src_name].outputs[src_port].append(edge)
            self.nodes[dst_name].inputs[dst_port] = edge

        for export in self.manifest.streams.exports:
            src_name, src_port = export.source.split(".", 1)
            if src_name not in self.nodes:
                raise RuntimeGraphError(f"Stream {export.name!r} references unknown node: {src_name!r}")
            source_node = self.nodes[src_name].node
            if src_port not in source_node.output_types:
                raise RuntimeGraphError(f"Stream {export.name!r} references unknown output: {export.source}")
            self._stream_exports.append({
                "name": export.name,
                "source": export.source,
                "type": source_node.output_types[src_port],
                "capacity": export.queue.capacity,
                "policy": export.queue.policy,
                "access_mode": export.access.mode,
                "token": export.access.token,
                "token_env": export.access.token_env,
                "allow_ips": list(export.access.allow_ips),
            })
        for reference in self._recording_streams:
            source_name, separator, source_port = reference.partition(".")
            if (
                not separator
                or source_name not in self.nodes
                or source_port not in self.nodes[source_name].node.output_types
            ):
                raise RuntimeGraphError(
                    f"Recording references unknown output: {reference!r}"
                )

        for name, loaded in self.nodes.items():
            optional = set(getattr(loaded.node, "optional_inputs", ()))
            missing = sorted(set(loaded.node.input_types) - optional - set(loaded.inputs))
            if missing:
                raise RuntimeGraphError(f"Node {name!r} has unconnected inputs: {missing}")
        if not any(isinstance(item.node, SourceNode) for item in self.nodes.values()):
            raise RuntimeGraphError("Unified pipeline requires at least one Python SourceNode")

    @staticmethod
    def _types_compatible(source: str, target: str) -> bool:
        return source == target or source == "core.any" or target == "core.any"

    def describe(self) -> dict[str, Any]:
        if not self.nodes:
            self.build()
        return {
            "name": self.manifest.metadata.name,
            "mode": self.manifest.runtime.mode,
            "profile": self.manifest.runtime.profile,
            "engine": "unified",
            "native_queue": self.native_queue_enabled,
            "type_validation": self.manifest.runtime.type_validation,
            "sessions": {
                name: {
                    "uses": loaded.uses,
                    "opened": loaded.opened,
                    "health": self._session_health(loaded),
                }
                for name, loaded in self.sessions.items()
            },
            "nodes": {
                name: {
                    "class": f"{loaded.node.__class__.__module__}.{loaded.node.__class__.__name__}",
                    "implementation": (
                        "process" if isinstance(loaded.node, ProcessNodeProxy)
                        else "native" if isinstance(loaded.node, NativePluginNode) else "python"
                    ),
                    "isolation": loaded.config.execution.isolation,
                    "failure": loaded.config.failure.model_dump(),
                    "health": loaded.config.health.model_dump(),
                    "resources": loaded.config.resources.model_dump(),
                    "lifecycle": loaded.node.lifecycle_state,
                    "inputs": loaded.node.input_types,
                    "optional_inputs": sorted(getattr(loaded.node, "optional_inputs", ())),
                    "outputs": loaded.node.output_types,
                    "input_memory": {**dict(getattr(loaded.node, "input_memory", {})), **dict(loaded.config.memory.inputs)},
                    "output_memory": {**dict(getattr(loaded.node, "output_memory", {})), **dict(loaded.config.memory.outputs)},
                    "device": loaded.config.execution.device,
                    "synchronization": loaded.config.synchronization.model_dump(),
                    "async_process": inspect.iscoroutinefunction(loaded.node.process),
                }
                for name, loaded in self.nodes.items()
            },
            "edges": [
                {
                    "from": edge.edge.source,
                    "to": edge.edge.target,
                    "type": self._edge_type(edge.edge.source),
                    "queue": edge.edge.queue.model_dump(),
                    "memory": None if edge.memory_plan is None else edge.memory_plan.as_dict(),
                }
                for edge in self.edges
            ],
            "links": [
                link.model_dump(by_alias=True, mode="json")
                for link in self.manifest.links
            ],
            "streams": [
                {key: value for key, value in item.items() if key != "token"}
                for item in self._stream_exports
            ],
        }

    def _edge_type(self, source: str) -> str:
        node, port = source.split(".", 1)
        return self.nodes[node].node.output_types[port]

    async def run(self) -> dict[str, Any]:
        # asyncio.to_thread() cannot forward Ctrl+C into the worker thread.
        # Convert task cancellation into an explicit graceful runtime stop and
        # wait until run artifacts have been finalized.
        worker = asyncio.create_task(asyncio.to_thread(self.run_sync))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            self._interrupted.set()
            self.request_stop()
            return await asyncio.shield(worker)

    @staticmethod
    def _safe_runtime_info(loaded: LoadedNode) -> dict[str, Any]:
        try:
            info = dict(loaded.node.runtime_info() or {})
            if loaded.fallback_active:
                info.update(
                    {
                        "fallback": loaded.config.failure.fallback_uses,
                        "primary": loaded.config.uses,
                    }
                )
            return info
        except Exception as exc:
            return {"diagnostic_error": f"{type(exc).__name__}: {exc}"}

    def _sample_isolated_resources(
        self,
        loaded: LoadedNode,
        *,
        attempts: int = 1,
    ) -> dict[str, Any]:
        pid = loaded.node.pid if isinstance(loaded.node, ProcessNodeProxy) else None
        resources: dict[str, Any] = {
            "pid": int(pid or 0),
            "available": False,
        }
        if pid is not None:
            for attempt in range(max(1, attempts)):
                resources = self._resource_sampler.process(pid)
                if resources.get("available"):
                    self._last_node_resources[loaded.name] = dict(resources)
                    break
                if attempt + 1 < attempts:
                    time.sleep(0.01)
        if not resources.get("available") and loaded.name in self._last_node_resources:
            resources = {
                **self._last_node_resources[loaded.name],
                "stale": True,
            }
        return resources

    def _node_report(self, loaded: LoadedNode, duration: float | None = None) -> dict[str, Any]:
        pressures = []
        estimated_queue_bytes = 0
        dropped = 0
        stale_skips = 0
        overflow_drops = 0
        for edge in loaded.inputs.values():
            stats = edge.report()
            pressures.append(float(stats.get("depth", 0)) / max(int(stats.get("capacity", 1)), 1))
            enqueued = max(int(stats.get("enqueued", 0)), 1)
            average = int(stats.get("bytes", 0)) / enqueued
            estimated_queue_bytes += int(average * int(stats.get("depth", 0)))
            dropped += int(stats.get("dropped", 0))
            stale_skips += int(stats.get("stale_skips", 0))
            overflow_drops += int(stats.get("overflow_drops", 0))
        loaded.node._lifecycle.set_queue_pressure(max(pressures, default=0.0))
        report = loaded.stats.report(duration)  # type: ignore[union-attr]
        if isinstance(loaded.node, ProcessNodeProxy):
            transport = loaded.node.transport_report()
            resources = self._sample_isolated_resources(loaded)
            resources["scope"] = "isolated_process"
            input_pool = dict(transport.get("shared_input_pool", {}))
            output_pool = dict(transport.get("shared_output_pool", {}))
            resources["shared_buffer_bytes"] = (
                int(input_pool.get("in_use", 0)) * int(input_pool.get("block_size", 0))
                + int(output_pool.get("in_use", 0)) * int(output_pool.get("block_size", 0))
            )
            report["transport"] = transport
        else:
            report["transport"] = {"isolation": "in_process", "payload_copies": 0}
            total_ns = int(loaded.stats.process.total_ns)  # type: ignore[union-attr]
            resources = self._resource_sampler.in_process_node(loaded.name, total_ns)
            resources["shared_buffer_bytes"] = 0
        resources["estimated_queue_bytes"] = estimated_queue_bytes
        resources["input_drops"] = dropped
        resources["stale_skips"] = stale_skips
        resources["overflow_drops"] = overflow_drops
        resources["sync_misses"] = int(report.get("synchronization_drops", 0))
        report["resources"] = resources
        report["health"] = loaded.node.health()
        report["runtime_info"] = self._safe_runtime_info(loaded)
        return report

    def snapshot(self, duration_seconds: float | None = None) -> dict[str, Any]:
        """Return a lock-free best-effort live telemetry snapshot."""
        if duration_seconds is None and self._run_started_ns is not None:
            duration_seconds = max((time.perf_counter_ns() - self._run_started_ns) / 1e9, 0.0)
        return {
            "pipeline": self.manifest.metadata.name,
            "status": "running" if self._run_started_ns is not None and not self._stop.is_set() else "idle",
            "duration_seconds": float(duration_seconds or 0.0),
            "profile": self.manifest.runtime.profile,
            "nodes": {name: self._node_report(loaded, duration_seconds) for name, loaded in self.nodes.items()},
            "edges": [edge.report() for edge in self.edges],
            "streams": self._stream_publisher.report() if self._stream_publisher is not None else {},
            "system": system_snapshot(),
        }

    def request_stop(self) -> None:
        """Request graceful source shutdown and unblock waiting edge queues."""
        self._stop.set()
        self._start.set()
        for edge in self.edges:
            edge.close()

    def run_sync(self) -> dict[str, Any]:
        """Run the graph and guarantee provider/control-plane cleanup."""

        try:
            return self._run_sync_impl()
        except BaseException:
            self._emergency_cleanup()
            raise

    def _run_sync_impl(self) -> dict[str, Any]:
        if not self.nodes:
            self.build()
        self._nodes_closed = False
        run_dir = self._create_run_dir()
        self._run_id = run_dir.name
        tracing = self.manifest.runtime.tracing
        self._tracer = EventTracer(
            enabled=tracing.enabled,
            exporter=tracing.exporter,
            endpoint=tracing.endpoint,
            service_name=tracing.service_name,
        )
        (run_dir / "logs").mkdir(exist_ok=True)
        (run_dir / "outputs").mkdir(exist_ok=True)
        self._events_path = run_dir / "events.jsonl"
        self._open_sessions(run_dir)
        recording_path: Path | None = None
        if self.manifest.recording.enabled:
            from .recording import NdrxWriter

            recording_dir = Path(self.manifest.recording.directory)
            if not recording_dir.is_absolute():
                recording_dir = run_dir / recording_dir
            recording_dir.mkdir(parents=True, exist_ok=True)
            recording_path = recording_dir / f"{self.manifest.metadata.name}.ndrx"
            self._recording_writer = NdrxWriter(
                recording_path,
                metadata={
                    "pipeline": self.manifest.metadata.name,
                    "apiVersion": self.manifest.api_version,
                    "streams": sorted(self._recording_streams),
                },
                checkpoint_records=self.manifest.recording.checkpoint_records,
                durable=self.manifest.recording.durable,
            )
        dump_source_manifest_redacted(self.manifest_path, run_dir / "manifest.yaml")
        dump_manifest_redacted(self.manifest, run_dir / "resolved-manifest.yaml")
        (run_dir / "runtime.json").write_text(
            json.dumps({"runtime": "nodrix", "version": __import__("nodrix").__version__, "engine": "unified"}, indent=2),
            encoding="utf-8",
        )
        (run_dir / "environment.json").write_text(
            json.dumps({
                "python": platform.python_version(), "executable": sys.executable,
                "platform": platform.platform(), "machine": platform.machine(),
            }, indent=2), encoding="utf-8",
        )
        try:
            (run_dir / "nodrix.lock").write_text(json.dumps(build_lock(self.manifest_path), indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            (run_dir / "logs" / "lock-warning.log").write_text(str(exc), encoding="utf-8")
        started_ns = time.perf_counter_ns()
        self._run_started_ns = started_ns
        self._emit_event("pipeline_starting", pipeline=self.manifest.metadata.name)
        if self._stream_exports:
            resolved_exports: list[dict[str, Any]] = []
            for item in self._stream_exports:
                resolved = dict(item)
                token_env = resolved.pop("token_env", None)
                if token_env and not resolved.get("token"):
                    resolved["token"] = os.environ.get(str(token_env))
                if resolved.get("access_mode") == "token" and not resolved.get("token"):
                    raise RuntimeGraphError(
                        f"Stream {resolved['name']!r} requires environment variable {token_env!r}"
                        if token_env else f"Stream {resolved['name']!r} requires an access token"
                    )
                resolved_exports.append(resolved)
            self._stream_publisher = StreamPublisher(
                self.manifest.metadata.name,
                resolved_exports,
                host=self.manifest.streams.bind_host,
                port=self.manifest.streams.listen_port,
                max_handshake_bytes=self.manifest.streams.max_handshake_bytes,
                max_message_bytes=self.manifest.streams.max_message_bytes,
                handshake_timeout=self.manifest.streams.handshake_timeout_ms / 1000.0,
                max_handshakes=self.manifest.streams.max_handshakes,
                max_clients=self.manifest.streams.max_clients,
                tls={
                    key: (
                        str(
                            value
                            if Path(str(value)).is_absolute()
                            else self.manifest_path.parent / str(value)
                        )
                        if key in {"certificate", "private_key", "client_ca"} and value
                        else value
                    )
                    for key, value in self.manifest.streams.tls.model_dump().items()
                },
            )
            self._stream_publisher.start()
            self._emit_event(
                "stream_server_ready",
                host=self.manifest.streams.bind_host,
                port=self._stream_publisher.server.port,
                streams=[item["name"] for item in resolved_exports],
                transport=(
                    "tls"
                    if self._stream_publisher.server.tls_context is not None
                    else "tcp"
                ),
            )
        metrics_recorder = None
        if self.manifest.runtime.metrics.enabled:
            metrics_recorder = MetricsRecorder(
                lambda: self.snapshot(max((time.perf_counter_ns() - started_ns) / 1e9, 1e-9)),
                run_dir / "metrics.jsonl",
                self.manifest.runtime.metrics.interval_ms / 1000.0,
                status_path=run_dir / "status.json",
            )
            metrics_recorder.start()
            self._metrics_recorder = metrics_recorder
        threads = [
            threading.Thread(
                target=self._node_worker,
                args=(loaded, run_dir),
                name=f"nodrix:{name}",
                daemon=False,
            )
            for name, loaded in self.nodes.items()
        ]
        self._worker_threads = threads
        for thread in threads:
            thread.start()
        while not all(node.ready.wait(0.01) for node in self.nodes.values()):
            if self._errors:
                break
        description = self.describe()
        execution_plan = compile_execution_plan(self.manifest, description)
        execution_plan["runtime_info"] = {
            name: self._safe_runtime_info(loaded)
            for name, loaded in self.nodes.items()
        }
        write_execution_plan(execution_plan, run_dir / "resolved-plan.json")
        write_run_provenance(
            run_dir,
            self.manifest,
            self.manifest_path,
            description,
        )
        if not self._errors:
            self._emit_event("pipeline_running", pipeline=self.manifest.metadata.name)
        self._start.set()
        watchdog = threading.Thread(target=self._watchdog_loop, name="nodrix-watchdog", daemon=True)
        self._watchdog_thread = watchdog
        watchdog.start()
        timeout_seconds = max(self.manifest.runtime.shutdown.timeout_ms / 1000.0, 0.0)
        interrupted = False
        deadline: float | None = None
        source_threads = {
            thread
            for thread, loaded in zip(threads, self.nodes.values(), strict=True)
            if isinstance(loaded.node, SourceNode)
        }
        while any(thread.is_alive() for thread in threads):
            try:
                if deadline is None and (
                    self._errors
                    or self._stop.is_set()
                    or all(not thread.is_alive() for thread in source_threads)
                ):
                    deadline = time.monotonic() + timeout_seconds
                if deadline is not None and time.monotonic() >= deadline:
                    self.request_stop()
                    self._record_error("runtime", TimeoutError("graceful shutdown timeout exceeded"))
                    break
                wait = 0.05 if deadline is None else min(0.05, max(deadline - time.monotonic(), 0.0))
                for thread in threads:
                    if thread.is_alive():
                        thread.join(timeout=wait)
                        break
            except KeyboardInterrupt:
                interrupted = True
                self._interrupted.set()
                self.request_stop()
                deadline = time.monotonic() + timeout_seconds
        alive = [thread for thread in threads if thread.is_alive()]
        if alive:
            self.request_stop()
            for thread in alive:
                thread.join(timeout=2.0)
            if any(thread.is_alive() for thread in alive):
                if not any(isinstance(exc, TimeoutError) for _, exc in self._errors):
                    self._record_error("runtime", TimeoutError("graceful shutdown timeout exceeded"))
        self._stop.set()
        watchdog.join(timeout=1.0)
        # Capture process RSS/CPU before isolated children and shared pools close.
        self.snapshot(max((time.perf_counter_ns() - started_ns) / 1e9, 1e-9))
        self._close_nodes()
        self._nodes_closed = True
        session_report = {
            name: self._session_health(loaded)
            for name, loaded in self.sessions.items()
        }
        self._close_sessions()
        if self._recording_writer is not None:
            try:
                self._recording_writer.close()
            except BaseException as exc:
                self._record_error("recording", exc)
            finally:
                self._recording_writer = None
        if metrics_recorder is not None:
            metrics_recorder.close()
            self._metrics_recorder = None
        finished_ns = time.perf_counter_ns()
        duration = (finished_ns - started_ns) / 1e9
        error = self._errors[0] if self._errors else None
        stream_report = self._stream_publisher.report() if self._stream_publisher is not None else {}
        if self._stream_publisher is not None:
            self._stream_publisher.close()
            self._stream_publisher = None
        report = {
            "pipeline": self.manifest.metadata.name,
            "status": (
                "failed"
                if error
                else "stopped"
                if interrupted or self._interrupted.is_set()
                else "completed"
            ),
            "mode": self.manifest.runtime.mode,
            "profile": self.manifest.runtime.profile,
            "engine": "unified",
            "native_queue": self.native_queue_enabled,
            "zero_copy_python_objects": True,
            "mixed_python_cpp": any(isinstance(item.node, NativePluginNode) for item in self.nodes.values()),
            "type_validation": self.manifest.runtime.type_validation,
            "run_dir": str(run_dir),
            "duration_seconds": duration,
            "error": None if error is None else f"{error[0]}: {type(error[1]).__name__}: {error[1]}",
            "nodes": {
                name: self._node_report(loaded, duration)
                for name, loaded in self.nodes.items()
            },
            "sessions": session_report,
            "edges": [edge.report() for edge in self.edges],
            "streams": stream_report,
            "recording": {
                "enabled": self.manifest.recording.enabled,
                "path": None if recording_path is None else str(recording_path),
                "streams": sorted(self._recording_streams),
            },
            "system": system_snapshot(),
        }
        encoded_report = json.dumps(report, indent=2, ensure_ascii=False, default=str)
        (run_dir / "run.json").write_text(encoded_report, encoding="utf-8")
        (run_dir / "summary.json").write_text(encoded_report, encoding="utf-8")
        if error is not None:
            (run_dir / "errors.jsonl").write_text(
                json.dumps({"node": error[0], "error": f"{type(error[1]).__name__}: {error[1]}"}) + "\n",
                encoding="utf-8",
            )
        self._emit_event("pipeline_stopped", pipeline=self.manifest.metadata.name, status=report["status"])
        if self._tracer is not None:
            self._tracer.close()
            self._tracer = None
        self._events_path = None
        self._run_started_ns = None
        self._worker_threads = []
        self._watchdog_thread = None
        if error is not None:
            raise error[1]
        return report

    def _emergency_cleanup(self) -> None:
        """Best-effort cleanup for failures during startup or report creation."""

        self.request_stop()
        for thread in tuple(self._worker_threads):
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=2.0)
        watchdog = self._watchdog_thread
        if (
            watchdog is not None
            and watchdog.is_alive()
            and watchdog is not threading.current_thread()
        ):
            watchdog.join(timeout=1.0)
        if not self._nodes_closed:
            for loaded in reversed(tuple(self.nodes.values())):
                if loaded.node.lifecycle_state == LifecycleState.CREATED.value:
                    continue
                try:
                    loaded.node.close()
                except BaseException:
                    pass
            self._nodes_closed = True
        self._close_sessions()
        if self._recording_writer is not None:
            try:
                self._recording_writer.close()
            except BaseException:
                pass
            self._recording_writer = None
        if self._metrics_recorder is not None:
            try:
                self._metrics_recorder.close()
            except BaseException:
                pass
            self._metrics_recorder = None
        if self._stream_publisher is not None:
            try:
                self._stream_publisher.close()
            except BaseException:
                pass
            self._stream_publisher = None
        if self._tracer is not None:
            try:
                self._tracer.close()
            except BaseException:
                pass
            self._tracer = None
        self._events_path = None
        self._run_started_ns = None
        self._worker_threads = []
        self._watchdog_thread = None

    def _node_worker(self, loaded: LoadedNode, run_dir: Path) -> None:
        bridge = _AsyncBridge()
        try:
            context = NodeContext(
                name=loaded.name,
                run_dir=run_dir,
                project_dir=self.base_dir,
                runtime_mode=self.manifest.runtime.mode,
                engine="unified",
                device=loaded.config.execution.device,
                bindings={
                    binding: self.sessions[session_name].instance
                    for binding, session_name in loaded.config.bindings.items()
                },
                external_links=tuple(
                    link.model_dump(by_alias=True, mode="json")
                    for link in self.manifest.links
                    if link.source.split(".", 1)[0] == loaded.name
                    or link.target.split(".", 1)[0] == loaded.name
                ),
            )
            bridge.resolve(loaded.node.configure(context))
            loaded.node._lifecycle.transition(LifecycleState.READY)
            loaded.node._lifecycle.transition(LifecycleState.STARTING)
            bridge.resolve(loaded.node.start())
            if isinstance(loaded.node, ProcessNodeProxy):
                # The child has acknowledged READY, so capture one guaranteed
                # live baseline before a short graph can finish or metrics
                # reach their first periodic interval.
                self._sample_isolated_resources(loaded, attempts=5)
            self._emit_event(
                "node_ready",
                node=loaded.name,
                uses=loaded.config.uses,
                lifecycle=loaded.node.lifecycle_state,
                runtime_info=self._safe_runtime_info(loaded),
            )
            # Publish READY before releasing the runtime-wide readiness barrier.
            # This guarantees that RUNNING is never printed before a node's
            # successful configure/start event has been delivered.
            loaded.ready.set()
            self._start.wait()
            if self._stop.is_set():
                return
            if isinstance(loaded.node, SourceNode):
                self._run_source(loaded, bridge)
            else:
                self._run_processor(
                    loaded,
                    bridge,
                    async_process=inspect.iscoroutinefunction(loaded.node.process),
                    async_flush=inspect.iscoroutinefunction(loaded.node.flush),
                )
        except BaseException as exc:
            self._emit_event("node_failed", node=loaded.name, uses=loaded.config.uses, error=f"{type(exc).__name__}: {exc}")
            loaded.stats.errors += 1  # type: ignore[union-attr]
            loaded.node._lifecycle.error(exc)
            loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
            if loaded.config.failure.policy in {"disable_branch", "isolate_branch"}:
                self._publish_eos(loaded)
            else:
                self._record_error(loaded.name, exc)
        finally:
            loaded.ready.set()
            bridge.close()

    def _close_nodes(self) -> None:
        # Close only after every worker has stopped. This keeps source-owned
        # pools, devices, and native resources alive until all downstream
        # consumers have drained their queues and released their leases.
        for loaded in reversed(tuple(self.nodes.values())):
            bridge = _AsyncBridge()
            was_failed = loaded.node.lifecycle_state == LifecycleState.FAILED.value
            try:
                bridge.resolve(loaded.node.stop())
                self._emit_event("node_stopped", node=loaded.name, uses=loaded.config.uses)
                if was_failed:
                    loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
            except BaseException as exc:
                loaded.node._lifecycle.error(exc)
                loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
                self._record_error(loaded.name, exc)
            finally:
                bridge.close()

    @staticmethod
    def _session_health(loaded: LoadedSession) -> dict[str, Any]:
        health = getattr(loaded.instance, "health", None)
        if not callable(health):
            return {"status": "ok", "open": loaded.opened}
        try:
            return dict(health() or {})
        except Exception as exc:
            return {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _open_sessions(self, run_dir: Path) -> None:
        bridge = _AsyncBridge()
        opened: list[LoadedSession] = []
        try:
            for loaded in self.sessions.values():
                opener = getattr(loaded.instance, "open", None)
                if callable(opener):
                    bridge.resolve(
                        opener(
                            SessionContext(
                                name=loaded.name,
                                run_dir=run_dir,
                                project_dir=self.base_dir,
                                runtime_mode=self.manifest.runtime.mode,
                            )
                        )
                    )
                loaded.opened = True
                opened.append(loaded)
                self._emit_event(
                    "session_ready",
                    session=loaded.name,
                    uses=loaded.uses,
                    health=self._session_health(loaded),
                )
        except BaseException:
            for loaded in reversed(opened):
                closer = getattr(loaded.instance, "close", None)
                if callable(closer):
                    try:
                        bridge.resolve(closer())
                    except Exception:
                        pass
                loaded.opened = False
            raise
        finally:
            bridge.close()

    def _close_sessions(self) -> None:
        bridge = _AsyncBridge()
        try:
            for loaded in reversed(tuple(self.sessions.values())):
                if not loaded.opened:
                    continue
                closer = getattr(loaded.instance, "close", None)
                try:
                    if callable(closer):
                        bridge.resolve(closer())
                    self._emit_event(
                        "session_stopped",
                        session=loaded.name,
                        uses=loaded.uses,
                    )
                except BaseException as exc:
                    self._record_error(loaded.name, exc)
                finally:
                    loaded.opened = False
        finally:
            bridge.close()

    def _run_source(self, loaded: LoadedNode, bridge: _AsyncBridge) -> None:
        produced = loaded.node.produce()
        if hasattr(produced, "__aiter__"):
            async_iter = produced.__aiter__()
            while not self._stop.is_set():
                try:
                    outputs = bridge.resolve(async_iter.__anext__())
                except StopAsyncIteration:
                    break
                loaded.node._lifecycle.message_started()
                start = time.perf_counter_ns()
                self._publish(loaded, outputs)
                loaded.stats.observe(time.perf_counter_ns() - start)  # type: ignore[union-attr]
                loaded.node._lifecycle.message_completed()
        else:
            for outputs in produced:  # type: ignore[union-attr]
                if self._stop.is_set():
                    break
                loaded.node._lifecycle.message_started()
                start = time.perf_counter_ns()
                self._publish(loaded, outputs)
                loaded.stats.observe(time.perf_counter_ns() - start)  # type: ignore[union-attr]
                loaded.node._lifecycle.message_completed()
        self._publish_eos(loaded)

    def _run_processor(
        self,
        loaded: LoadedNode,
        bridge: _AsyncBridge,
        *,
        async_process: bool,
        async_flush: bool,
    ) -> None:
        input_ports = tuple(loaded.inputs)
        process = loaded.node.process
        while not self._stop.is_set():
            received = self._receive_synchronized(loaded, input_ports)
            if received is None:
                break
            process_inputs = {port: item.message for port, item in received.items()}
            loaded.watchdog_triggered = False
            loaded.node._lifecycle.message_started()
            start = time.perf_counter_ns()
            try:
                result = bridge.resolve(process(process_inputs)) if async_process else process(process_inputs)
            except BaseException as exc:
                if (
                    loaded.config.failure.policy == "fallback_node"
                    and not loaded.fallback_active
                ):
                    self._activate_fallback(loaded, bridge, exc)
                    process = loaded.node.process
                    async_process = inspect.iscoroutinefunction(process)
                    result = (
                        bridge.resolve(process(process_inputs))
                        if async_process
                        else process(process_inputs)
                    )
                    loaded.stats.errors += 1  # type: ignore[union-attr]
                elif loaded.config.failure.policy == "skip_message":
                    loaded.stats.errors += 1  # type: ignore[union-attr]
                    loaded.node._lifecycle.error(exc)
                    loaded.node._lifecycle.transition(LifecycleState.RUNNING, status=HealthStatus.DEGRADED)
                    continue
                elif loaded.config.failure.policy in {"disable_branch", "isolate_branch"}:
                    loaded.stats.errors += 1  # type: ignore[union-attr]
                    loaded.node._lifecycle.error(exc)
                    loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
                    self._publish_eos(loaded)
                    return
                else:
                    raise
            loaded.stats.observe(time.perf_counter_ns() - start, received)  # type: ignore[union-attr]
            loaded.node._lifecycle.message_completed()
            if result:
                self._publish(loaded, result)
        flushed = bridge.resolve(loaded.node.drain()) if async_flush else loaded.node.drain()
        if flushed:
            self._publish(loaded, flushed)
        self._publish_eos(loaded)

    def _activate_fallback(
        self,
        loaded: LoadedNode,
        bridge: _AsyncBridge,
        primary_error: BaseException,
    ) -> None:
        fallback_uses = loaded.config.failure.fallback_uses
        if not fallback_uses:
            raise RuntimeGraphError(
                f"Node {loaded.name!r} has no configured fallback"
            )
        old_node = loaded.node
        context = old_node.context
        if context is None:
            raise RuntimeGraphError(
                f"Node {loaded.name!r} failed before a fallback could be configured"
            )
        bridge.resolve(old_node.stop())
        fallback = self._load_node(fallback_uses, loaded.config.parameters)
        if (
            dict(fallback.input_types) != dict(old_node.input_types)
            or dict(fallback.output_types) != dict(old_node.output_types)
        ):
            raise RuntimeGraphError(
                f"Node {loaded.name!r} fallback contracts changed after validation"
            )
        bridge.resolve(fallback.configure(context))
        fallback._lifecycle.transition(LifecycleState.READY)
        fallback._lifecycle.transition(LifecycleState.STARTING)
        bridge.resolve(fallback.start())
        fallback._lifecycle.transition(
            LifecycleState.DEGRADED,
            status=HealthStatus.DEGRADED,
            reason=f"fallback after {type(primary_error).__name__}: {primary_error}",
        )
        loaded.node = fallback
        loaded.fallback_active = True
        self._emit_event(
            "node_fallback",
            node=loaded.name,
            uses=fallback_uses,
            primary_error=f"{type(primary_error).__name__}: {primary_error}",
        )

    def _blocking_received(self, edge: EdgeQueue) -> Received | None:
        item = edge.get()
        if item is None or item is _EOS:
            return None
        return item

    def _receive_synchronized(self, loaded: LoadedNode, input_ports: tuple[str, ...]) -> dict[str, Received] | None:
        if len(input_ports) == 1:
            item = self._blocking_received(loaded.inputs[input_ports[0]])
            return None if item is None else {input_ports[0]: item}

        policy = loaded.config.synchronization.policy
        if policy == "zip":
            result: dict[str, Received] = {}
            for port in input_ports:
                item = self._blocking_received(loaded.inputs[port])
                if item is None:
                    return None
                result[port] = item
            return result
        if policy == "latest_available":
            return self._receive_latest(loaded, input_ports)
        return self._receive_matching(loaded, input_ports, approximate=(policy == "approximate_timestamp"))

    def _receive_latest(self, loaded: LoadedNode, input_ports: tuple[str, ...]) -> dict[str, Received] | None:
        trigger = loaded.config.synchronization.trigger_port or input_ports[0]
        item = self._blocking_received(loaded.inputs[trigger])
        if item is None:
            return None
        loaded.latest_inputs[trigger] = item
        for port in input_ports:
            if port == trigger:
                continue
            optional = port in getattr(loaded.node, "optional_inputs", ())
            if port not in loaded.latest_inputs and not optional:
                initial = self._blocking_received(loaded.inputs[port])
                if initial is None:
                    return None
                loaded.latest_inputs[port] = initial
            while True:
                newest = loaded.inputs[port].try_get()
                if newest is None or newest is _EOS:
                    break
                if port in loaded.latest_inputs:
                    loaded.stats.synchronization_drops += 1  # type: ignore[union-attr]
                loaded.latest_inputs[port] = newest
        return {port: loaded.latest_inputs[port] for port in input_ports if port in loaded.latest_inputs}

    def _receive_matching(
        self, loaded: LoadedNode, input_ports: tuple[str, ...], *, approximate: bool
    ) -> dict[str, Received] | None:
        current: dict[str, Received] = {}
        tolerance_ns = int(loaded.config.synchronization.tolerance_ms * 1e6)
        while not self._stop.is_set():
            for port in input_ports:
                if port not in current:
                    item = self._blocking_received(loaded.inputs[port])
                    if item is None:
                        return None
                    current[port] = item
            if approximate:
                timestamps = {port: item.message.timestamp_ns for port, item in current.items()}
                oldest_port = min(timestamps, key=timestamps.get)
                if max(timestamps.values()) - min(timestamps.values()) <= tolerance_ns:
                    return current
                current.pop(oldest_port)
                loaded.stats.synchronization_drops += 1  # type: ignore[union-attr]
            else:
                sequences = {port: item.message.sequence for port, item in current.items()}
                if len(set(sequences.values())) == 1:
                    return current
                oldest_port = min(sequences, key=sequences.get)
                current.pop(oldest_port)
                loaded.stats.synchronization_drops += 1  # type: ignore[union-attr]
        return None

    def _validate_payload(self, loaded: LoadedNode, port: str, message: Message) -> None:
        mode = self.manifest.runtime.type_validation
        if mode == "off":
            return
        key = (loaded.name, port)
        if mode == "first" and key in self._validated_ports:
            return
        TYPE_REGISTRY.validate(message.type, message.payload)
        self._validated_ports.add(key)
        loaded.stats.type_validations += 1  # type: ignore[union-attr]

    def _publish(self, loaded: LoadedNode, outputs: dict[str, Message]) -> None:
        for port, message in outputs.items():
            if port not in loaded.node.output_types:
                raise RuntimeGraphError(f"Node {loaded.name!r} emitted unknown port {port!r}")
            expected = loaded.node.output_types[port]
            if not self._types_compatible(message.type, expected):
                raise RuntimeGraphError(
                    f"Node {loaded.name!r} emitted {message.type!r} on {port!r}; expected {expected!r}"
                )
            normalized = normalize_payload(message.type, message.payload)
            if normalized is not message.payload:
                message = message.with_updates(payload=normalized)
            payload_size = _estimate_message_bytes(message)
            if payload_size > loaded.config.resources.max_message_bytes:
                raise RuntimeGraphError(
                    f"Node {loaded.name!r} emitted {payload_size} bytes, exceeding resources.max_message_bytes="
                    f"{loaded.config.resources.max_message_bytes}"
                )
            if len(json.dumps(message.metadata, default=str).encode("utf-8")) > 1024 * 1024:
                raise RuntimeGraphError(f"Node {loaded.name!r} emitted metadata larger than 1 MiB")
            self._validate_payload(loaded, port, message)
            source_name = f"{loaded.name}.{port}"
            outgoing = message.with_updates(
                stream_id=source_name,
                source_id=message.source_id or source_name,
                pipeline_id=message.pipeline_id or self.manifest.metadata.name,
                run_id=message.run_id or self._run_id,
            )
            if (
                self._recording_writer is not None
                and (
                    not self._recording_streams
                    or source_name in self._recording_streams
                )
            ):
                with self._recording_lock:
                    self._recording_writer.write(outgoing)
            for edge in loaded.outputs.get(port, ()):
                edge.put(outgoing)
            if self._stream_publisher is not None:
                self._stream_publisher.publish(source_name, outgoing)

    def _publish_eos(self, loaded: LoadedNode) -> None:
        for queues in loaded.outputs.values():
            for edge in queues:
                edge.put_control(_EOS)

    def _watchdog_loop(self) -> None:
        while not self._stop.wait(0.1):
            now = time.monotonic_ns()
            for loaded in self.nodes.values():
                config = loaded.config.health
                if config.timeout_ms <= 0:
                    continue
                health = loaded.node._lifecycle.snapshot()
                last = health.last_message_ns or health.last_completion_ns
                if not health.ready or last is None:
                    continue
                if now - last <= int(config.timeout_ms * 1e6) or loaded.watchdog_triggered:
                    continue
                loaded.watchdog_triggered = True
                loaded.node._lifecycle.error(f"health timeout after {config.timeout_ms} ms")
                if config.on_timeout == "stop_pipeline":
                    self._record_error(loaded.name, TimeoutError(f"node health timeout: {loaded.name}"))
                    return
                if config.on_timeout == "restart" and isinstance(loaded.node, ProcessNodeProxy):
                    loaded.node._lifecycle.mark_restart()
                    loaded.node.interrupt()
                    # The blocked worker observes EOF and performs the serialized restart.
                    loaded.node._lifecycle.transition(LifecycleState.RESTARTING, status=HealthStatus.DEGRADED)

    def _record_error(self, name: str, exc: BaseException) -> None:
        with self._error_lock:
            if not self._errors:
                self._errors.append((name, exc))
                self._stop.set()
                self._start.set()
                for edge in self.edges:
                    edge.close()

    def _create_run_dir(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in self.manifest.metadata.name)
        run_dir = self.run_root / f"{timestamp}-{safe_name}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir
