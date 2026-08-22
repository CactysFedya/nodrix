from __future__ import annotations

from collections.abc import Mapping
import os
from types import MappingProxyType

from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable

from .metric_publisher import MetricSink
from .manifest import (
    PipelineManifest,
    external_transport_bindings,
)
from .node import NodeContext, SourceNode
from .process_host import ProcessNodeProxy
from .observability import EventTracer
from .memory import MemoryPlan
from .streams import StreamPublisher
from .metrics import MetricsRecorder
from .lifecycle import HealthStatus, LifecycleState
from .resources import ResourceSampler
from .storage_layout import StorageLayout

try:
    from ._native_queue import BoundedQueue as _NativeBoundedQueue
except Exception:  # pragma: no cover
    _NativeBoundedQueue = None


from .runtime_builder import RuntimeBuildMixin
from .runtime_execution import RuntimeExecutionMixin
from .integration_runtime import IntegrationRuntimeMixin
from .runtime_workers import RuntimeWorkerMixin
from .runtime_components import (
    EdgeQueue,
    LoadedApplication,
    LoadedNode,
    LoadedResource,
    LoadedSession,
    _AsyncBridge,
)


class HybridPipelineRuntime(
    RuntimeBuildMixin,
    RuntimeExecutionMixin,
    IntegrationRuntimeMixin,
    RuntimeWorkerMixin,
):
    """Plyctl 2.x unified executor.

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

        # Materialize the minimal mechanical values consumed by worker hot
        # paths. Workers must not reach back into PipelineManifest while
        # processing messages. The direct System executor will provide the
        # same runtime-level values without constructing a PipelineManifest.
        self._runtime_type_validation = (
            self.manifest.runtime.type_validation
        )
        self._message_scope_id = (
            self.manifest.metadata.name
        )
        self.run_root = (
            run_root
            or StorageLayout(
                self.base_dir
            ).runs_root
        ).resolve()
        self._execution_environment: Mapping[str, str] | None = None
        self._execution_environment_locked = False
        self.nodes: dict[str, LoadedNode] = {}
        self.sessions: dict[str, LoadedSession] = {}
        self.resources: dict[str, LoadedResource] = {}
        self.applications: dict[str, LoadedApplication] = {}
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
        self._recording_streams = set(self.manifest.recording.streams)
        self._metrics_recorder: MetricsRecorder | None = None
        self._canonical_metric_sink: MetricSink | None = None
        self._worker_threads: list[threading.Thread] = []
        self._watchdog_thread: threading.Thread | None = None
        self._built = False
        self._nodes_closed = False

    @staticmethod
    def _freeze_execution_environment(
        environment: Mapping[str, str],
    ) -> Mapping[str, str]:
        return MappingProxyType(
            {
                str(key): str(value)
                for key, value in environment.items()
            }
        )

    @property
    def execution_environment(
        self,
    ) -> Mapping[str, str]:
        """Return the runtime-owned environment snapshot."""

        if self._execution_environment is None:
            return self._freeze_execution_environment(
                os.environ
            )

        return self._execution_environment

    def environment_value(
        self,
        name: str,
        default: str | None = None,
    ) -> str | None:
        return self.execution_environment.get(
            name,
            default,
        )

    def set_execution_environment(
        self,
        environment: Mapping[str, str],
    ) -> None:
        """Bind one exact environment before runtime build."""

        if self._execution_environment_locked:
            raise RuntimeError(
                "Execution environment is already locked "
                "for this runtime"
            )

        if not isinstance(
            environment,
            Mapping,
        ):
            raise TypeError(
                "environment must be a mapping"
            )

        self._execution_environment = (
            self._freeze_execution_environment(
                environment
            )
        )

    def set_metric_sink(
        self,
        sink: MetricSink | None,
    ) -> None:
        """Bind an executor-owned canonical Metric sink before runtime build."""

        if self._built:
            raise RuntimeError(
                "Metric sink must be bound before runtime build"
            )

        if (
            sink is not None
            and not isinstance(
                sink,
                MetricSink,
            )
        ):
            raise TypeError(
                "sink must implement MetricSink"
            )

        self._canonical_metric_sink = sink

    def _lock_execution_environment(
        self,
    ) -> None:
        if self._execution_environment is None:
            self._execution_environment = (
                self._freeze_execution_environment(
                    os.environ
                )
            )

        self._execution_environment_locked = True

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

    def _node_worker(self, loaded: LoadedNode, run_dir: Path) -> None:
        bridge = _AsyncBridge()
        try:
            context = NodeContext(
                name=loaded.name,
                run_dir=run_dir,
                project_dir=self.base_dir,
                runtime_mode=self.manifest.runtime.mode,
                engine="unified",
                environment=self.execution_environment,
                device=loaded.binding.device,
                bindings={
                    binding: self._resource_instance(resource_name)
                    for binding, resource_name in loaded.binding.resource_bindings.items()
                },
                external_links=tuple(
                    link
                    for link in external_transport_bindings(self.manifest)
                    if str(link["from"]).split(".", 1)[0] == loaded.name
                    or str(link["to"]).split(".", 1)[0] == loaded.name
                ),
            )
            context._bind_metric_sink(  # noqa: SLF001
                self._canonical_metric_sink
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
                uses=loaded.binding.uses,
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
            self._emit_event("node_failed", node=loaded.name, uses=loaded.binding.uses, error=f"{type(exc).__name__}: {exc}")
            loaded.stats.errors += 1  # type: ignore[union-attr]
            loaded.node._lifecycle.error(exc)
            loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
            if loaded.binding.failure_policy in {"disable_branch", "isolate_branch"}:
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
                self._emit_event("node_stopped", node=loaded.name, uses=loaded.binding.uses)
                if was_failed:
                    loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
            except BaseException as exc:
                loaded.node._lifecycle.error(exc)
                loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
                self._record_error(loaded.name, exc)
            finally:
                bridge.close()

    def _create_run_dir(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in self.manifest.metadata.name)
        run_dir = self.run_root / f"{timestamp}-{safe_name}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir
