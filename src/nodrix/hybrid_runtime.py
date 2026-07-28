from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import inspect
import json
import os
import platform
import shutil
import sys
from pathlib import Path
import queue as pyqueue
import threading
import time
from typing import Any

from .cv_types import TYPE_REGISTRY, normalize_payload
from .errors import RuntimeGraphError
from .manifest import EdgeConfig, NodeConfig, PipelineManifest, dump_manifest_redacted, dump_source_manifest_redacted
from .messages import Message
from .native_plugin import NativePluginNode
from .node import Node, NodeContext, SourceNode
from .process_host import ProcessNodeProxy, ProcessSourceProxy
from .registry import load_node_class
from .telemetry import LatencyWindow
from .memory import MemoryPlan, MemoryRequirement, plan_memory, requirement_for_port, memory_summary
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
        return {
            "source": self.edge.source,
            "target": self.edge.target,
            "enqueued": int(stats.get("enqueued", 0)),
            "dequeued": int(stats.get("dequeued", 0)),
            "dropped": int(stats.get("dropped", 0)),
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
    """Nodrix 0.5 unified executor.

    Python nodes and C++ processor/sink plugins share the same native bounded
    queues, typed messages, lifecycle, synchronization, telemetry, and zero-copy
    buffer protocol.    """

    def __init__(self, manifest: PipelineManifest, manifest_path: Path, run_root: Path | None = None) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path.resolve()
        self.base_dir = self.manifest_path.parent
        self.run_root = (run_root or self.base_dir / ".nodrix" / "runs").resolve()
        self.nodes: dict[str, LoadedNode] = {}
        self.edges: list[EdgeQueue] = []
        self._start = threading.Event()
        self._stop = threading.Event()
        self._errors: list[tuple[str, BaseException]] = []
        self._error_lock = threading.Lock()
        self._validated_ports: set[tuple[str, str]] = set()
        self._stream_exports: list[dict[str, Any]] = []
        self._stream_publisher: StreamPublisher | None = None
        self._memory_plans: dict[tuple[str, str], MemoryPlan] = {}
        self._resource_sampler = ResourceSampler()
        self._last_node_resources: dict[str, dict[str, Any]] = {}

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
        self.edges.clear()
        self._stream_exports.clear()
        self._memory_plans.clear()
        sample_capacity = self.manifest.runtime.telemetry_samples
        for name, config in self.manifest.nodes.items():
            node = self._load_node(config.uses, config.parameters)
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

        for name, loaded in self.nodes.items():
            missing = sorted(set(loaded.node.input_types) - set(loaded.inputs))
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
            "streams": [
                {key: value for key, value in item.items() if key != "token"}
                for item in self._stream_exports
            ],
        }

    def _edge_type(self, source: str) -> str:
        node, port = source.split(".", 1)
        return self.nodes[node].node.output_types[port]

    async def run(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.run_sync)

    def _node_report(self, loaded: LoadedNode, duration: float | None = None) -> dict[str, Any]:
        pressures = []
        estimated_queue_bytes = 0
        dropped = 0
        for edge in loaded.inputs.values():
            stats = edge.report()
            pressures.append(float(stats.get("depth", 0)) / max(int(stats.get("capacity", 1)), 1))
            enqueued = max(int(stats.get("enqueued", 0)), 1)
            average = int(stats.get("bytes", 0)) / enqueued
            estimated_queue_bytes += int(average * int(stats.get("depth", 0)))
            dropped += int(stats.get("dropped", 0))
        loaded.node._lifecycle.set_queue_pressure(max(pressures, default=0.0))
        report = loaded.stats.report(duration)  # type: ignore[union-attr]
        if isinstance(loaded.node, ProcessNodeProxy):
            transport = loaded.node.transport_report()
            pid = loaded.node.pid
            resources = self._resource_sampler.process(pid) if pid is not None else {"available": False}
            if resources.get("available"):
                self._last_node_resources[loaded.name] = dict(resources)
            elif loaded.name in self._last_node_resources:
                resources = {**self._last_node_resources[loaded.name], "stale": True}
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
        report["resources"] = resources
        report["health"] = loaded.node.health()
        return report

    def snapshot(self, duration_seconds: float | None = None) -> dict[str, Any]:
        """Return a lock-free best-effort live telemetry snapshot."""
        return {
            "pipeline": self.manifest.metadata.name,
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
        if not self.nodes:
            self.build()
        run_dir = self._create_run_dir()
        (run_dir / "logs").mkdir(exist_ok=True)
        (run_dir / "outputs").mkdir(exist_ok=True)
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
            )
            self._stream_publisher.start()
        metrics_recorder = None
        if self.manifest.runtime.metrics.enabled:
            metrics_recorder = MetricsRecorder(
                lambda: self.snapshot(max((time.perf_counter_ns() - started_ns) / 1e9, 1e-9)),
                run_dir / "metrics.jsonl",
                self.manifest.runtime.metrics.interval_ms / 1000.0,
                status_path=run_dir / "status.json",
            )
            metrics_recorder.start()
        threads = [
            threading.Thread(
                target=self._node_worker,
                args=(loaded, run_dir),
                name=f"nodrix:{name}",
                daemon=False,
            )
            for name, loaded in self.nodes.items()
        ]
        for thread in threads:
            thread.start()
        while not all(node.ready.wait(0.01) for node in self.nodes.values()):
            if self._errors:
                break
        self._start.set()
        watchdog = threading.Thread(target=self._watchdog_loop, name="nodrix-watchdog", daemon=True)
        watchdog.start()
        timeout_seconds = self.manifest.runtime.shutdown.timeout_ms / 1000.0
        interrupted = False
        try:
            for thread in threads:
                thread.join()
        except KeyboardInterrupt:
            interrupted = True
            self.request_stop()
            deadline = time.monotonic() + timeout_seconds
            for thread in threads:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        alive = [thread for thread in threads if thread.is_alive()]
        if alive:
            self._stop.set()
            for edge in self.edges:
                edge.close()
            for thread in alive:
                thread.join(timeout=2.0)
            if any(thread.is_alive() for thread in alive):
                self._record_error("runtime", TimeoutError("graceful shutdown timeout exceeded"))
        self._stop.set()
        watchdog.join(timeout=1.0)
        # Capture process RSS/CPU before isolated children and shared pools close.
        self.snapshot(max((time.perf_counter_ns() - started_ns) / 1e9, 1e-9))
        self._close_nodes()
        if metrics_recorder is not None:
            metrics_recorder.close()
        finished_ns = time.perf_counter_ns()
        duration = (finished_ns - started_ns) / 1e9
        error = self._errors[0] if self._errors else None
        stream_report = self._stream_publisher.report() if self._stream_publisher is not None else {}
        if self._stream_publisher is not None:
            self._stream_publisher.close()
            self._stream_publisher = None
        report = {
            "pipeline": self.manifest.metadata.name,
            "status": "failed" if error else "stopped" if interrupted else "completed",
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
            "edges": [edge.report() for edge in self.edges],
            "streams": stream_report,
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
        if error is not None:
            raise error[1]
        return report

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
            )
            loaded.node._lifecycle.transition(LifecycleState.STARTING)
            bridge.resolve(loaded.node.configure(context))
            bridge.resolve(loaded.node.start())
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
            loaded.stats.errors += 1  # type: ignore[union-attr]
            loaded.node._lifecycle.error(exc)
            loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
            if loaded.config.failure.policy == "disable_branch":
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
                if was_failed:
                    loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
            except BaseException as exc:
                loaded.node._lifecycle.error(exc)
                loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
                self._record_error(loaded.name, exc)
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
                if loaded.config.failure.policy == "skip_message":
                    loaded.stats.errors += 1  # type: ignore[union-attr]
                    loaded.node._lifecycle.error(exc)
                    loaded.node._lifecycle.transition(LifecycleState.RUNNING, status=HealthStatus.DEGRADED)
                    continue
                if loaded.config.failure.policy == "disable_branch":
                    loaded.stats.errors += 1  # type: ignore[union-attr]
                    loaded.node._lifecycle.error(exc)
                    loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
                    self._publish_eos(loaded)
                    return
                raise
            loaded.stats.observe(time.perf_counter_ns() - start, received)  # type: ignore[union-attr]
            loaded.node._lifecycle.message_completed()
            if result:
                self._publish(loaded, result)
        flushed = bridge.resolve(loaded.node.drain()) if async_flush else loaded.node.drain()
        if flushed:
            self._publish(loaded, flushed)
        self._publish_eos(loaded)

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
            if port not in loaded.latest_inputs:
                initial = self._blocking_received(loaded.inputs[port])
                if initial is None:
                    return None
                loaded.latest_inputs[port] = initial
            while True:
                newest = loaded.inputs[port].try_get()
                if newest is None or newest is _EOS:
                    break
                loaded.latest_inputs[port] = newest
                loaded.stats.synchronization_drops += 1  # type: ignore[union-attr]
        return {port: loaded.latest_inputs[port] for port in input_ports}

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
            outgoing = message.with_updates(stream_id=source_name)
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
