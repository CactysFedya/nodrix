from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from nodrix.model import (
    ExecutionRecord,
    ExecutionState,
    EntityRef,
    Operation,
    PlanRecord,
    RevisionRef,
)


def mapping_system() -> EntityRef:
    return EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )


def mapping_plan() -> PlanRecord:
    system = mapping_system()

    return PlanRecord(
        plan_id="plan-001",
        kind="system-execution",
        operation=Operation(
            kind="run",
            subject=system,
        ),
        subject_revision=RevisionRef.from_sha256(
            system,
            "a" * 64,
        ),
        payload={
            "target": "pi5",
            "backend": "local",
        },
    )


def test_execution_state_parses_strings() -> None:
    assert ExecutionState.parse("RUNNING") is ExecutionState.RUNNING
    assert ExecutionState.parse(" completed ") is ExecutionState.COMPLETED


@pytest.mark.parametrize(
    "value",
    [
        "",
        "unknown",
        "succeeded",
        "running-now",
    ],
)
def test_execution_state_rejects_unknown_values(value: str) -> None:
    with pytest.raises(ValueError):
        ExecutionState.parse(value)


@pytest.mark.parametrize(
    "state",
    [
        ExecutionState.STOPPED,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    ],
)
def test_terminal_execution_states(
    state: ExecutionState,
) -> None:
    assert state.terminal


@pytest.mark.parametrize(
    "state",
    [
        ExecutionState.CREATED,
        ExecutionState.PREPARED,
        ExecutionState.RUNNING,
        ExecutionState.STOPPING,
    ],
)
def test_non_terminal_execution_states(
    state: ExecutionState,
) -> None:
    assert not state.terminal


def test_successful_execution_states() -> None:
    assert ExecutionState.COMPLETED.successful
    assert ExecutionState.STOPPED.successful
    assert not ExecutionState.FAILED.successful
    assert not ExecutionState.CANCELLED.successful


def test_execution_record_links_to_plan() -> None:
    plan = mapping_plan()

    execution = ExecutionRecord(
        execution_id="execution-001",
        plan=plan,
        executor="nodrix.system.orchestrator",
        state="running",
    )

    assert execution.execution_id == "execution-001"
    assert execution.plan == plan
    assert execution.operation == plan.operation
    assert execution.subject == plan.subject
    assert execution.subject_revision == plan.subject_revision
    assert execution.state is ExecutionState.RUNNING
    assert not execution.terminal


def test_execution_accepts_completed_timestamps() -> None:
    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )
    finished = started + timedelta(seconds=10)

    execution = ExecutionRecord(
        execution_id="execution-001",
        plan=mapping_plan(),
        executor="nodrix.system.orchestrator",
        state="completed",
        started_at=started,
        finished_at=finished,
    )

    assert execution.started_at == started
    assert execution.finished_at == finished
    assert execution.terminal
    assert execution.successful


def test_execution_requires_timezone_aware_timestamps() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        ExecutionRecord(
            execution_id="execution-001",
            plan=mapping_plan(),
            executor="nodrix.system.orchestrator",
            state="running",
            started_at=datetime(2026, 8, 15, 20, 0),
        )


def test_finished_execution_requires_started_at() -> None:
    with pytest.raises(
        ValueError,
        match="finished_at requires started_at",
    ):
        ExecutionRecord(
            execution_id="execution-001",
            plan=mapping_plan(),
            executor="nodrix.system.orchestrator",
            state="completed",
            finished_at=datetime.now(timezone.utc),
        )


def test_finished_at_cannot_precede_started_at() -> None:
    started = datetime.now(timezone.utc)

    with pytest.raises(
        ValueError,
        match="cannot be earlier",
    ):
        ExecutionRecord(
            execution_id="execution-001",
            plan=mapping_plan(),
            executor="nodrix.system.orchestrator",
            state="failed",
            started_at=started,
            finished_at=started - timedelta(seconds=1),
        )


def test_execution_requires_non_empty_id() -> None:
    with pytest.raises(ValueError):
        ExecutionRecord(
            execution_id="   ",
            plan=mapping_plan(),
            executor="nodrix.system.orchestrator",
        )


def test_execution_requires_non_empty_executor() -> None:
    with pytest.raises(ValueError):
        ExecutionRecord(
            execution_id="execution-001",
            plan=mapping_plan(),
            executor="   ",
        )


def test_execution_details_are_copied_and_read_only() -> None:
    details = {
        "scope_count": 2,
    }

    execution = ExecutionRecord(
        execution_id="execution-001",
        plan=mapping_plan(),
        executor="nodrix.system.orchestrator",
        state="running",
        details=details,
    )

    details["scope_count"] = 99

    assert isinstance(execution.details, MappingProxyType)
    assert execution.details["scope_count"] == 2

    with pytest.raises(TypeError):
        execution.details["scope_count"] = 3  # type: ignore[index]


def test_different_executions_can_use_same_plan() -> None:
    plan = mapping_plan()

    first = ExecutionRecord(
        execution_id="execution-001",
        plan=plan,
        executor="nodrix.system.orchestrator",
        state="completed",
    )

    second = ExecutionRecord(
        execution_id="execution-002",
        plan=plan,
        executor="nodrix.system.orchestrator",
        state="running",
    )

    assert first.plan == second.plan
    assert first.execution_id != second.execution_id
    assert first.state != second.state
