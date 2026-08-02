from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
from pathlib import Path
import threading
import time
from typing import Any

from .errors import RuntimeGraphError
from .execution_plan import compile_execution_plan, write_execution_plan
from .manifest import (
    dump_manifest_redacted,
    dump_source_manifest_redacted,
)
from .native_plugin import NativePluginNode
from .node import SourceNode
from .process_host import ProcessNodeProxy
from .provenance import write_run_provenance
from .observability import EventTracer
from .streams import StreamPublisher
from .metrics import MetricsRecorder
from .lockfile import build_lock
from .lifecycle import LifecycleState
from .resources import system_snapshot

try:
    from ._native_queue import BoundedQueue as _NativeBoundedQueue
except Exception:  # pragma: no cover
    _NativeBoundedQueue = None


from .runtime_components import LoadedNode


class RuntimeExecutionMixin:
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
            "applications": {
                name: self._application_health(loaded)
                for name, loaded in self.applications.items()
            },
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
        if not self._built:
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
        self._open_resources(run_dir)
        self._start_applications(run_dir)
        recording_path: Path | None = None
        if self.manifest.recording.enabled:
            from .recording import AsyncNdrxWriter

            recording_dir = Path(self.manifest.recording.directory)
            if not recording_dir.is_absolute():
                recording_dir = run_dir / recording_dir
            recording_dir.mkdir(parents=True, exist_ok=True)
            recording_path = recording_dir / f"{self.manifest.metadata.name}.ndrx"
            self._recording_writer = AsyncNdrxWriter(
                recording_path,
                metadata={
                    "pipeline": self.manifest.metadata.name,
                    "apiVersion": self.manifest.api_version,
                    "streams": sorted(self._recording_streams),
                },
                checkpoint_records=self.manifest.recording.checkpoint_records,
                durable=self.manifest.recording.durable,
                queue_capacity=self.manifest.recording.queue_capacity,
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
        while any(thread.is_alive() for thread in threads) or self._applications_active():
            try:
                if deadline is None and (
                    self._errors
                    or self._stop.is_set()
                    or (
                        bool(source_threads)
                        and all(not thread.is_alive() for thread in source_threads)
                    )
                ):
                    deadline = time.monotonic() + timeout_seconds
                if deadline is not None and time.monotonic() >= deadline:
                    self.request_stop()
                    self._record_error("runtime", TimeoutError("graceful shutdown timeout exceeded"))
                    break
                wait = 0.05 if deadline is None else min(0.05, max(deadline - time.monotonic(), 0.0))
                waited_for_thread = False
                for thread in threads:
                    if thread.is_alive():
                        thread.join(timeout=wait)
                        waited_for_thread = True
                        break
                if not waited_for_thread:
                    self._stop.wait(wait)
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
        resource_report = {
            name: self._managed_resource_health(loaded)
            for name, loaded in self.resources.items()
        }
        application_report = {
            name: self._application_health(loaded)
            for name, loaded in self.applications.items()
        }
        self._stop_applications()
        self._close_resources()
        self._close_sessions()
        recording_report: dict[str, Any] = {}
        if self._recording_writer is not None:
            try:
                self._recording_writer.close()
                recording_report = self._recording_writer.report()
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
            "resources": resource_report,
            "applications": application_report,
            "edges": [edge.report() for edge in self.edges],
            "streams": stream_report,
            "recording": {
                "enabled": self.manifest.recording.enabled,
                "path": None if recording_path is None else str(recording_path),
                "streams": sorted(self._recording_streams),
                **recording_report,
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
        self._stop_applications()
        self._close_resources()
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
