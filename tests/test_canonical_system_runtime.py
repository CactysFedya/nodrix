from datetime import datetime, timedelta, timezone

import pytest

from nodrix.model import ExecutionState
from nodrix.system import (
    BackendCapabilities,
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    Graph,
    NodeInstance,
    PreparedExecution,
    SystemModel,
    SystemOrchestrator,
    Target,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.canonical_runtime import (
    SYSTEM_ORCHESTRATOR_EXECUTOR,
    inspect_canonical_system_execution,
    start_canonical_system_execution,
    stop_canonical_system_execution,
)


class RuntimeBackend(ExecutionBackend):
    def __init__(self) -> None:
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds={"host"},
            ),
        )
        self.state = BackendExecutionState.PREPARED

    def _prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        self.state = BackendExecutionState.PREPARED

        return PreparedExecution(
            backend=self.backend_id,
            context=context,
        )

    def _start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        self.state = BackendExecutionState.RUNNING

        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id="backend-execution-001",
            prepared=prepared,
        )

    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=self.state,
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        self.state = BackendExecutionState.STOPPED

        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=self.state,
            details={
                "timeout_seconds": timeout_seconds,
            },
        )


def system_plan():
    system = SystemModel(
        name="mapping",
        targets=(
            Target(
                name="pi5",
                kind="host",
                properties={
                    "backend": "local",
                },
            ),
        ),
        graphs=(
            Graph(
                name="mapping",
                nodes=(
                    NodeInstance(
                        name="mapper",
                        uses="mapping.voxel-map",
                        target="pi5",
                    ),
                ),
            ),
        ),
    )

    return plan_canonical_system(system)


def runtime():
    backend = RuntimeBackend()

    orchestrator = SystemOrchestrator(
        {
            ("pi5", "local"): backend,
        }
    )

    return orchestrator, backend


def fixed_clock(value: datetime):
    def clock() -> datetime:
        return value

    return clock


def test_start_tracks_real_orchestrator_execution() -> None:
    orchestrator, backend = runtime()

    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )

    execution = start_canonical_system_execution(
        orchestrator,
        system_plan(),
        clock=fixed_clock(started),
    )

    assert execution.started_at == started
    assert execution.finished_at is None
    assert execution.execution_id.startswith(
        "system-"
    )

    assert (
        backend.state
        is BackendExecutionState.RUNNING
    )


def test_inspect_returns_running_canonical_execution_record() -> None:
    orchestrator, _ = runtime()

    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )

    execution = start_canonical_system_execution(
        orchestrator,
        system_plan(),
        clock=fixed_clock(started),
    )

    record = inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=fixed_clock(
            started + timedelta(seconds=2)
        ),
    )

    assert (
        record.execution_id
        == execution.execution_id
    )
    assert record.state is ExecutionState.RUNNING
    assert record.executor == SYSTEM_ORCHESTRATOR_EXECUTOR
    assert record.started_at == started
    assert record.finished_at is None
    assert not record.terminal

    assert record.details["scope_count"] == 1


def test_stop_returns_terminal_canonical_execution_record() -> None:
    orchestrator, _ = runtime()

    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )
    stopped = started + timedelta(seconds=10)

    execution = start_canonical_system_execution(
        orchestrator,
        system_plan(),
        clock=fixed_clock(started),
    )

    record = stop_canonical_system_execution(
        orchestrator,
        execution,
        timeout_seconds=2.5,
        clock=fixed_clock(stopped),
    )

    assert record.state is ExecutionState.STOPPED
    assert record.terminal
    assert record.successful
    assert record.started_at == started
    assert record.finished_at == stopped

    scopes = record.details["scopes"]

    assert len(scopes) == 1
    assert scopes[0]["target"] == "pi5"
    assert scopes[0]["backend"] == "local"
    assert scopes[0]["state"] == "stopped"
    assert (
        scopes[0]["details"]["timeout_seconds"]
        == 2.5
    )


def test_first_terminal_observation_time_is_stable() -> None:
    orchestrator, _ = runtime()

    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )

    first_terminal = (
        started + timedelta(seconds=10)
    )

    execution = start_canonical_system_execution(
        orchestrator,
        system_plan(),
        clock=fixed_clock(started),
    )

    first = stop_canonical_system_execution(
        orchestrator,
        execution,
        clock=fixed_clock(first_terminal),
    )

    later = inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=fixed_clock(
            started + timedelta(seconds=20)
        ),
    )

    assert first.finished_at == first_terminal
    assert later.finished_at == first_terminal


def test_same_plan_can_create_multiple_real_executions() -> None:
    plan = system_plan()

    first_orchestrator, _ = runtime()
    second_orchestrator, _ = runtime()

    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )

    first = start_canonical_system_execution(
        first_orchestrator,
        plan,
        clock=fixed_clock(started),
    )

    second = start_canonical_system_execution(
        second_orchestrator,
        plan,
        clock=fixed_clock(started),
    )

    assert first.plan == second.plan
    assert first.execution_id != second.execution_id


def test_terminal_backend_completion_maps_to_completed_state() -> None:
    orchestrator, backend = runtime()

    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )

    execution = start_canonical_system_execution(
        orchestrator,
        system_plan(),
        clock=fixed_clock(started),
    )

    backend.state = BackendExecutionState.COMPLETED

    record = inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=fixed_clock(
            started + timedelta(seconds=5)
        ),
    )

    assert record.state is ExecutionState.COMPLETED
    assert record.successful
    assert record.finished_at == (
        started + timedelta(seconds=5)
    )


def test_failed_backend_maps_to_failed_state() -> None:
    orchestrator, backend = runtime()

    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )

    execution = start_canonical_system_execution(
        orchestrator,
        system_plan(),
        clock=fixed_clock(started),
    )

    backend.state = BackendExecutionState.FAILED

    record = inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=fixed_clock(
            started + timedelta(seconds=5)
        ),
    )

    assert record.state is ExecutionState.FAILED
    assert record.terminal
    assert not record.successful


def test_clock_must_return_timezone_aware_datetime() -> None:
    orchestrator, _ = runtime()

    naive = datetime(
        2026,
        8,
        15,
        20,
        0,
    )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        start_canonical_system_execution(
            orchestrator,
            system_plan(),
            clock=fixed_clock(naive),
        )
