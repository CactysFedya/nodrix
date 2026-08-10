from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from nodrix.system import (
    BackendExecutionState,
    Graph,
    NodeInstance,
    ProcessBackend,
    SystemLink,
    SystemModel,
    Target,
    backend_context_for_scope,
    plan_execution_scopes,
    plan_system,
)


def _process_plan(*, count: int = 1, interval_ms: float = 0) -> object:
    return plan_system(
        SystemModel(
            name="process-system",
            targets=(
                Target(
                    name="worker",
                    kind="host",
                    properties={"backend": "process"},
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="core.synthetic_source",
                            target="worker",
                            parameters={
                                "count": count,
                                "interval_ms": interval_ms,
                            },
                        ),
                        NodeInstance(
                            name="sink",
                            uses="core.counter_sink",
                            target="worker",
                        ),
                    ),
                    connections=(
                        {"from": "source.output", "to": "sink.input"},
                    ),
                ),
            ),
        )
    )


def _wait_terminal(backend: ProcessBackend, handle, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    status = backend.inspect(handle)
    while not status.terminal and time.monotonic() < deadline:
        time.sleep(0.02)
        status = backend.inspect(handle)
    return status


class _CooperativeRuntime:
    def __init__(self) -> None:
        self._stop = threading.Event()

    def build(self) -> None:
        return None

    def request_stop(self) -> None:
        self._stop.set()

    def run_sync(self):
        self._stop.wait(timeout=30)
        return {"status": "stopped"}


def _cooperative_runtime_factory(manifest, manifest_path, run_root):
    del manifest, manifest_path, run_root
    return _CooperativeRuntime()


class _FailingRuntime:
    def build(self) -> None:
        return None

    def request_stop(self) -> None:
        return None

    def run_sync(self):
        raise RuntimeError("runtime exploded after ready")


def _failing_runtime_factory(manifest, manifest_path, run_root):
    del manifest, manifest_path, run_root
    return _FailingRuntime()


class _StubbornRuntime:
    def __init__(self, run_root: Path | None) -> None:
        self.run_root = run_root

    def build(self) -> None:
        return None

    def request_stop(self) -> None:
        # Deliberately ignore cooperative shutdown. The backend must escalate.
        return None

    def _spawn_child(self) -> int:
        if self.run_root is None:
            raise RuntimeError("test runtime requires run_root")
        self.run_root.mkdir(parents=True, exist_ok=True)
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import signal,time; "
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    "time.sleep(60)"
                ),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        (self.run_root / "child.pid").write_text(
            str(child.pid),
            encoding="utf-8",
        )
        return child.pid

    def run_sync(self):
        self._spawn_child()
        while True:
            time.sleep(1)


def _stubborn_runtime_factory(manifest, manifest_path, run_root):
    del manifest, manifest_path
    return _StubbornRuntime(run_root)


class _LeakyRuntime(_StubbornRuntime):
    def run_sync(self):
        self._spawn_child()
        return {"status": "completed"}


def _leaky_runtime_factory(manifest, manifest_path, run_root):
    del manifest, manifest_path
    return _LeakyRuntime(run_root)


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        try:
            fields = proc_stat.read_text(encoding="utf-8").split()
        except OSError:
            return False
        if len(fields) > 2 and fields[2] == "Z":
            return False
    return True


def _wait_pid_gone(pid: int, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while _pid_running(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _pid_running(pid), f"descendant process {pid} survived shutdown"


def _wait_child_pid(path: Path, timeout: float = 5.0) -> int:
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), "child process did not start"
    return int(path.read_text(encoding="utf-8"))


def test_process_backend_runs_scope_in_separate_process(tmp_path: Path) -> None:
    backend = ProcessBackend(
        working_directory=tmp_path,
        scope_name="worker",
        startup_timeout_seconds=10,
    )
    prepared = backend.prepare_plan(_process_plan())

    handle = backend.start(prepared)
    status = _wait_terminal(backend, handle)

    assert status.state is BackendExecutionState.COMPLETED
    assert status.details["pid"] != os.getpid()
    assert status.details["exitcode"] == 0
    assert status.details["alive"] is False
    assert status.details["tree_alive"] is False
    assert prepared.payload.manifest_path.name.endswith("-worker-process.yaml")
    if os.name == "posix":
        assert status.details["process_group"] is True
        assert status.details["pgid"] == status.details["pid"]
        assert status.details["process_tree_shutdown"] == "process_group"


def test_process_backend_graceful_stop(tmp_path: Path) -> None:
    backend = ProcessBackend(
        working_directory=tmp_path,
        scope_name="worker",
        startup_timeout_seconds=10,
        stop_timeout_seconds=2,
        runtime_factory=_cooperative_runtime_factory,
    )
    prepared = backend.prepare_plan(_process_plan())
    handle = backend.start(prepared)

    status = backend.stop(handle, timeout_seconds=2)

    assert status.state is BackendExecutionState.STOPPED
    assert status.terminal
    assert status.details["alive"] is False
    assert status.details["forced"] is False


def test_process_backend_startup_failure_is_reported(tmp_path: Path) -> None:
    plan = plan_system(
        SystemModel(
            name="broken-process-system",
            targets=(
                Target(
                    name="worker",
                    kind="host",
                    properties={"backend": "process"},
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="missing",
                            uses="missing.module:MissingNode",
                            target="worker",
                        ),
                    ),
                ),
            ),
        )
    )
    backend = ProcessBackend(
        working_directory=tmp_path,
        scope_name="worker",
        startup_timeout_seconds=10,
    )
    prepared = backend.prepare_plan(plan)

    try:
        backend.start(prepared)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("broken process scope unexpectedly started")

    assert "MissingNode" in message or "missing.module" in message


def test_process_backend_runtime_failure_propagates_after_ready(
    tmp_path: Path,
) -> None:
    backend = ProcessBackend(
        working_directory=tmp_path,
        scope_name="worker",
        startup_timeout_seconds=10,
        runtime_factory=_failing_runtime_factory,
    )
    prepared = backend.prepare_plan(_process_plan())

    handle = backend.start(prepared)
    status = _wait_terminal(backend, handle)

    assert status.state is BackendExecutionState.FAILED
    assert "runtime exploded after ready" in (status.message or "")
    assert status.details["alive"] is False
    assert status.details["tree_alive"] is False


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux process-group regression coverage",
)
def test_process_backend_forced_stop_kills_descendant_process_group(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    backend = ProcessBackend(
        working_directory=tmp_path,
        run_root=run_root,
        scope_name="worker",
        startup_timeout_seconds=10,
        stop_timeout_seconds=0.05,
        force_grace_seconds=0.1,
        runtime_factory=_stubborn_runtime_factory,
    )
    prepared = backend.prepare_plan(_process_plan())
    handle = backend.start(prepared)

    child_pid = _wait_child_pid(run_root / "child.pid")
    assert _pid_running(child_pid)

    status = backend.stop(handle, timeout_seconds=0.05)

    assert status.state is BackendExecutionState.STOPPED
    assert status.details["forced"] is True
    assert status.details["alive"] is False
    _wait_pid_gone(child_pid)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux process-group regression coverage",
)
def test_process_backend_marks_completed_scope_failed_when_descendant_leaks(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    backend = ProcessBackend(
        working_directory=tmp_path,
        run_root=run_root,
        scope_name="worker",
        startup_timeout_seconds=10,
        force_grace_seconds=0.1,
        runtime_factory=_leaky_runtime_factory,
    )
    prepared = backend.prepare_plan(_process_plan())
    handle = backend.start(prepared)
    child_pid = _wait_child_pid(run_root / "child.pid")

    status = _wait_terminal(backend, handle)

    assert status.state is BackendExecutionState.FAILED
    assert status.details["forced"] is True
    assert "descendant processes were still alive" in (status.message or "")
    _wait_pid_gone(child_pid)


def test_process_backend_rejects_cross_scope_links(tmp_path: Path) -> None:
    plan = plan_system(
        SystemModel(
            name="process-transport-boundary",
            targets=(
                Target(
                    name="worker",
                    kind="host",
                    properties={"backend": "process"},
                ),
                Target(
                    name="inline",
                    kind="host",
                    properties={"backend": "local"},
                ),
            ),
            graphs=(
                Graph(
                    name="producer",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="core.synthetic_source",
                            target="worker",
                        ),
                    ),
                ),
                Graph(
                    name="consumer",
                    nodes=(
                        NodeInstance(
                            name="sink",
                            uses="core.counter_sink",
                            target="inline",
                        ),
                    ),
                ),
            ),
            links=(
                SystemLink(
                    **{
                        "from": "producer/source.output",
                        "to": "consumer/sink.input",
                        "uses": "tcp",
                    }
                ),
            ),
        )
    )
    process_scope = next(
        scope for scope in plan_execution_scopes(plan)
        if scope.backend == "process"
    )
    backend = ProcessBackend(
        working_directory=tmp_path,
        scope_name=process_scope.target,
    )
    context = backend_context_for_scope(plan, process_scope)

    report = backend.validate(context)

    assert not report.valid
    assert any(item.code == "PROCESS101" for item in report.errors)
