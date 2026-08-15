"""Process-isolated execution backend for Nodrix 2.8.

``ProcessBackend`` owns one orchestration scope in a dedicated worker process.
It is deliberately separate from :mod:`nodrix.process_host`: that module
isolates individual Nodes inside an existing runtime, while this backend
isolates the complete ``(target, backend)`` scope controlled by the System
orchestrator.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
import multiprocessing as mp
from multiprocessing.connection import Connection
import os
from pathlib import Path
import signal
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from ..manifest import PipelineManifest, dump_manifest, load_manifest
from .backend import (
    BackendCapabilities,
    BackendContext,
    BackendDiagnostic,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    PreparedExecution,
)
from .local_backend import lower_local_context


RuntimeFactory = Callable[[PipelineManifest, Path, Path | None], Any]


def _default_runtime_factory(
    manifest: PipelineManifest,
    manifest_path: Path,
    run_root: Path | None,
) -> Any:
    from ..hybrid_runtime import HybridPipelineRuntime

    return HybridPipelineRuntime(
        manifest,
        manifest_path,
        run_root=run_root,
    )


def _scope_file_token(value: str) -> str:
    safe = []
    for char in value.strip():
        safe.append(char if char.isalnum() or char in "._-" else "-")
    token = "".join(safe).strip("-._")
    return token or "scope"


def _worker_process_group() -> tuple[bool, int | None]:
    """Detach the worker so its descendants can be terminated as one tree."""

    if os.name != "posix":
        return False, None
    try:
        os.setsid()
        return True, os.getpgrp()
    except OSError:
        return False, None


def _activate_project(path: Path | None):
    if path is None:
        return nullcontext()

    from ..local_dev import activate_local_project, compile_local_project

    project = compile_local_project(path)
    return activate_local_project(project)


def _process_worker(
    connection: Connection,
    *,
    manifest_path: str,
    run_root: str | None,
    project_path: str | None,
    runtime_factory: RuntimeFactory,
) -> None:
    process_group, pgid = _worker_process_group()
    try:
        connection.send(
            {
                "event": "boot",
                "pid": os.getpid(),
                "process_group": process_group,
                "pgid": pgid,
            }
        )

        path = Path(manifest_path)
        manifest = load_manifest(path)
        resolved_run_root = Path(run_root) if run_root is not None else None
        resolved_project = Path(project_path) if project_path is not None else None

        with _activate_project(resolved_project):
            runtime = runtime_factory(manifest, path, resolved_run_root)
            build = getattr(runtime, "build", None)
            if callable(build):
                build()

            stop_requested = threading.Event()

            def control() -> None:
                while not stop_requested.is_set():
                    try:
                        if not connection.poll(0.1):
                            continue
                        command = connection.recv()
                    except (EOFError, BrokenPipeError, OSError):
                        return
                    if command.get("op") != "stop":
                        continue
                    stop_requested.set()
                    request_stop = getattr(runtime, "request_stop", None)
                    if callable(request_stop):
                        request_stop()
                    return

            controller = threading.Thread(
                target=control,
                name="nodrix-process-backend-control",
                daemon=True,
            )
            controller.start()

            connection.send({"event": "ready", "pid": os.getpid()})
            report = runtime.run_sync()
            control_stop_requested = stop_requested.is_set()
            stop_requested.set()

        payload = dict(report or {})
        report_status = str(payload.get("status", "completed")).lower()
        state = (
            BackendExecutionState.FAILED.value
            if report_status == "failed"
            else BackendExecutionState.STOPPED.value
            if report_status == "stopped" or control_stop_requested
            else BackendExecutionState.COMPLETED.value
        )
        connection.send(
            {
                "event": "terminal",
                "state": state,
                "report": payload,
            }
        )
    except BaseException as exc:
        try:
            connection.send(
                {
                    "event": "fatal",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        connection.close()


@dataclass(frozen=True, slots=True)
class ProcessPreparedPayload:
    manifest_path: Path
    project_path: Path | None
    run_root: Path | None


@dataclass(slots=True)
class _ProcessExecution:
    process: mp.Process
    connection: Connection
    process_group: bool = False
    pgid: int | None = None
    state: BackendExecutionState = BackendExecutionState.RUNNING
    reported_terminal_state: BackendExecutionState | None = None
    message: str | None = None
    report: dict[str, Any] = field(default_factory=dict)
    forced: bool = False
    connection_closed: bool = False
    finalized: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class ProcessBackend(ExecutionBackend):
    """Execute one System scope inside a dedicated worker process.

    A worker-reported terminal event is intentionally not terminal from the
    backend's point of view. The scope becomes terminal only after the owned
    worker has exited and any residual POSIX process group has been cleaned up.
    """

    def __init__(
        self,
        *,
        project: str | Path | None = None,
        working_directory: str | Path | None = None,
        run_root: str | Path | None = None,
        stop_timeout_seconds: float = 10.0,
        startup_timeout_seconds: float = 20.0,
        force_grace_seconds: float = 1.0,
        scope_name: str | None = None,
        runtime_factory: RuntimeFactory | None = None,
    ) -> None:
        tree_shutdown = "process_group" if os.name == "posix" else "worker"
        super().__init__(
            "process",
            capabilities=BackendCapabilities(
                target_kinds=frozenset({"local", "host"}),
                features=frozenset(
                    {
                        "process_isolation",
                        "graphs",
                        "resources",
                        "applications",
                    }
                ),
                metadata={"process_tree_shutdown": tree_shutdown},
            ),
        )
        self.project_path = (
            Path(project).expanduser().resolve()
            if project is not None
            else None
        )
        self.working_directory = (
            Path(working_directory).expanduser().resolve()
            if working_directory is not None
            else self.project_path
            if self.project_path is not None
            else Path.cwd().resolve()
        )
        self.run_root = (
            Path(run_root).expanduser().resolve()
            if run_root is not None
            else None
        )
        if stop_timeout_seconds < 0:
            raise ValueError("stop_timeout_seconds cannot be negative")
        if startup_timeout_seconds <= 0:
            raise ValueError("startup_timeout_seconds must be positive")
        if force_grace_seconds < 0:
            raise ValueError("force_grace_seconds cannot be negative")
        self.stop_timeout_seconds = float(stop_timeout_seconds)
        self.startup_timeout_seconds = float(startup_timeout_seconds)
        self.force_grace_seconds = float(force_grace_seconds)
        self.scope_name = _scope_file_token(scope_name) if scope_name else None
        self.runtime_factory = runtime_factory or _default_runtime_factory
        self._ctx = mp.get_context("spawn")

    def _validate(self, context: BackendContext):
        diagnostics: list[BackendDiagnostic] = []
        if context.inbound_links or context.outbound_links:
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="PROCESS101",
                    path="links",
                    message=(
                        "ProcessBackend does not bridge cross-scope links yet; "
                        "a transport runtime is required"
                    ),
                )
            )
        return diagnostics

    def _prepare(self, context: BackendContext) -> PreparedExecution:
        lowering = lower_local_context(context)
        generated_dir = self.working_directory / ".nodrix" / "system-generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        scope_suffix = f"-{self.scope_name}" if self.scope_name else ""
        manifest_path = generated_dir / (
            f"{context.plan.system}-{context.plan.system_sha256[:12]}"
            f"{scope_suffix}-process.yaml"
        )
        dump_manifest(lowering.manifest, manifest_path)
        payload = ProcessPreparedPayload(
            manifest_path=manifest_path,
            project_path=self.project_path,
            run_root=self.run_root,
        )
        return PreparedExecution(
            backend=self.backend_id,
            context=context,
            payload=payload,
            metadata={
                "manifest_path": str(manifest_path),
                "scope": self.scope_name,
                "isolation": "process",
            },
        )

    def _start(self, prepared: PreparedExecution) -> BackendExecutionHandle:
        payload = prepared.payload
        if not isinstance(payload, ProcessPreparedPayload):
            raise TypeError("ProcessBackend requires ProcessPreparedPayload")

        parent, child = self._ctx.Pipe(duplex=True)
        process = self._ctx.Process(
            target=_process_worker,
            kwargs={
                "connection": child,
                "manifest_path": str(payload.manifest_path),
                "run_root": (
                    str(payload.run_root) if payload.run_root is not None else None
                ),
                "project_path": (
                    str(payload.project_path)
                    if payload.project_path is not None
                    else None
                ),
                "runtime_factory": self.runtime_factory,
            },
            name=f"nodrix-scope:{self.scope_name or 'process'}",
        )
        process.start()
        child.close()

        execution = _ProcessExecution(process=process, connection=parent)
        deadline = time.monotonic() + self.startup_timeout_seconds
        ready = False
        try:
            while time.monotonic() < deadline:
                if not parent.poll(0.05):
                    if not process.is_alive():
                        break
                    continue
                event = parent.recv()
                kind = event.get("event")
                if kind == "boot":
                    execution.process_group = bool(event.get("process_group"))
                    execution.pgid = event.get("pgid")
                elif kind == "ready":
                    ready = True
                    break
                elif kind == "fatal":
                    raise RuntimeError(event.get("error", "process worker startup failed"))
        except BaseException:
            self._force_terminate(execution)
            self._close_connection(execution)
            raise

        if not ready:
            self._force_terminate(execution)
            self._close_connection(execution)
            raise RuntimeError(
                "ProcessBackend worker did not become ready before startup timeout"
            )

        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id=f"process-{uuid4().hex[:12]}",
            prepared=prepared,
            payload=execution,
        )

    def _execution(self, handle: BackendExecutionHandle) -> _ProcessExecution:
        execution = handle.payload
        if not isinstance(execution, _ProcessExecution):
            raise TypeError("ProcessBackend handle contains an invalid payload")
        return execution

    def _close_connection(self, execution: _ProcessExecution) -> None:
        if execution.connection_closed:
            return
        try:
            execution.connection.close()
        except OSError:
            pass
        execution.connection_closed = True

    def _drain_events(self, execution: _ProcessExecution) -> None:
        if execution.connection_closed:
            return
        while True:
            try:
                if not execution.connection.poll(0):
                    return
                event = execution.connection.recv()
            except (EOFError, BrokenPipeError, OSError):
                return

            kind = event.get("event")
            with execution.lock:
                if kind == "terminal":
                    try:
                        execution.reported_terminal_state = BackendExecutionState(
                            event["state"]
                        )
                    except (KeyError, ValueError):
                        execution.reported_terminal_state = BackendExecutionState.FAILED
                        execution.message = "worker returned an invalid terminal state"
                    execution.report = dict(event.get("report") or {})
                elif kind == "fatal":
                    execution.reported_terminal_state = BackendExecutionState.FAILED
                    execution.message = str(
                        event.get("error", "process worker failed")
                    )

    def _group_alive(self, execution: _ProcessExecution) -> bool:
        if (
            os.name != "posix"
            or not execution.process_group
            or execution.pgid is None
        ):
            return False
        try:
            os.killpg(execution.pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _tree_alive(self, execution: _ProcessExecution) -> bool:
        return execution.process.is_alive() or self._group_alive(execution)

    def _signal_group(
        self,
        execution: _ProcessExecution,
        sig: signal.Signals,
    ) -> bool:
        if not self._group_alive(execution):
            return False
        try:
            os.killpg(execution.pgid, sig)
            return True
        except (ProcessLookupError, OSError):
            return False

    def _wait_tree_exit(
        self,
        execution: _ProcessExecution,
        timeout_seconds: float,
    ) -> None:
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while self._tree_alive(execution) and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if execution.process.is_alive():
                execution.process.join(timeout=min(0.05, remaining))
            else:
                time.sleep(min(0.02, remaining))
        if not execution.process.is_alive():
            execution.process.join(timeout=0)

    def _force_terminate(self, execution: _ProcessExecution) -> None:
        if not self._tree_alive(execution):
            if not execution.process.is_alive():
                execution.process.join(timeout=0)
            return

        execution.forced = True
        if self._group_alive(execution):
            self._signal_group(execution, signal.SIGTERM)
        elif execution.process.is_alive():
            execution.process.terminate()

        self._wait_tree_exit(execution, self.force_grace_seconds)

        if self._group_alive(execution):
            self._signal_group(execution, signal.SIGKILL)
        elif execution.process.is_alive():
            kill = getattr(execution.process, "kill", None)
            if callable(kill):
                kill()
            else:
                execution.process.terminate()

        self._wait_tree_exit(
            execution,
            max(self.force_grace_seconds, 0.1),
        )

    def _finalize_worker_exit(self, execution: _ProcessExecution) -> None:
        if execution.finalized:
            return

        execution.process.join(timeout=0)
        self._drain_events(execution)

        with execution.lock:
            reported = execution.reported_terminal_state
            if reported is not None:
                execution.state = reported
            elif execution.state is BackendExecutionState.STOPPING:
                execution.state = BackendExecutionState.STOPPED
            else:
                execution.state = BackendExecutionState.FAILED
                execution.message = (
                    "process worker exited unexpectedly with code "
                    f"{execution.process.exitcode}"
                )
            state_before_cleanup = execution.state

        if self._group_alive(execution):
            self._force_terminate(execution)
            with execution.lock:
                if state_before_cleanup is BackendExecutionState.COMPLETED:
                    execution.state = BackendExecutionState.FAILED
                    execution.message = (
                        "process scope completed while descendant processes "
                        "were still alive; residual process group was terminated"
                    )
                elif execution.message is None:
                    execution.message = (
                        "residual scope processes were force-terminated after "
                        "the worker exited"
                    )

        self._close_connection(execution)
        execution.finalized = True

    def _inspect(self, handle: BackendExecutionHandle) -> BackendExecutionStatus:
        execution = self._execution(handle)
        self._drain_events(execution)

        if execution.process.is_alive():
            # A terminal event means the runtime has finished, not that the
            # process-isolation boundary has finished. Keep the external state
            # non-terminal until the worker has actually exited and its tree is
            # known to be clean.
            with execution.lock:
                state = execution.state
        else:
            self._finalize_worker_exit(execution)
            with execution.lock:
                state = execution.state

        with execution.lock:
            message = execution.message
            report = dict(execution.report)
            forced = execution.forced
            pending = execution.reported_terminal_state

        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=state,
            message=message,
            details={
                "pid": execution.process.pid,
                "pgid": execution.pgid,
                "process_group": execution.process_group,
                "process_tree_shutdown": self.capabilities.metadata.get(
                    "process_tree_shutdown"
                ),
                "alive": execution.process.is_alive(),
                "tree_alive": self._tree_alive(execution),
                "exitcode": execution.process.exitcode,
                "forced": forced,
                "worker_terminal_pending": (
                    pending.value
                    if pending is not None and execution.process.is_alive()
                    else None
                ),
                "report": report,
            },
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        execution = self._execution(handle)
        current = self._inspect(handle)
        if current.terminal:
            return current

        with execution.lock:
            execution.state = BackendExecutionState.STOPPING

        try:
            execution.connection.send({"op": "stop"})
        except (EOFError, BrokenPipeError, OSError):
            pass

        timeout = (
            self.stop_timeout_seconds
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        execution.process.join(timeout=timeout)
        self._drain_events(execution)

        if self._tree_alive(execution):
            self._force_terminate(execution)
            with execution.lock:
                if execution.reported_terminal_state is BackendExecutionState.FAILED:
                    execution.state = BackendExecutionState.FAILED
                else:
                    execution.state = BackendExecutionState.STOPPED
                    execution.reported_terminal_state = BackendExecutionState.STOPPED
                    execution.message = (
                        "worker process tree force-terminated after stop timeout"
                    )

        return self._inspect(handle)


__all__ = [
    "ProcessBackend",
    "ProcessPreparedPayload",
]
