from __future__ import annotations

import os
from pathlib import Path
import time

from nodrix.system import (
    BackendExecutionState,
    Graph,
    NodeInstance,
    ProcessBackend,
    SystemModel,
    Target,
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
    assert prepared.payload.manifest_path.name.endswith("-worker-process.yaml")
    if os.name == "posix":
        assert status.details["process_group"] is True
        assert status.details["pgid"] == status.details["pid"]


def test_process_backend_graceful_stop(tmp_path: Path) -> None:
    backend = ProcessBackend(
        working_directory=tmp_path,
        scope_name="worker",
        startup_timeout_seconds=10,
        stop_timeout_seconds=2,
    )
    prepared = backend.prepare_plan(
        _process_plan(count=100_000, interval_ms=10)
    )
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
