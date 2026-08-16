from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from nodrix.model import (
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RevisionRef,
    RunRecord,
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


def finished_execution(
    *,
    execution_id: str = "execution-001",
    state: str = "completed",
) -> ExecutionRecord:
    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )

    return ExecutionRecord(
        execution_id=execution_id,
        plan=mapping_plan(),
        executor="nodrix.system.orchestrator",
        state=state,
        started_at=started,
        finished_at=started + timedelta(seconds=10),
    )


def test_run_record_wraps_finished_execution() -> None:
    execution = finished_execution()

    run = RunRecord(
        run_id="run-001",
        execution=execution,
    )

    assert run.run_id == "run-001"
    assert run.execution == execution
    assert run.execution_id == execution.execution_id
    assert run.plan == execution.plan
    assert run.operation == execution.operation
    assert run.subject == execution.subject
    assert run.subject_revision == execution.subject_revision
    assert run.state == execution.state
    assert run.started_at == execution.started_at
    assert run.finished_at == execution.finished_at
    assert run.successful


def test_run_requires_non_empty_id() -> None:
    with pytest.raises(ValueError):
        RunRecord(
            run_id="   ",
            execution=finished_execution(),
        )


def test_run_requires_terminal_execution() -> None:
    started = datetime.now(timezone.utc)

    execution = ExecutionRecord(
        execution_id="execution-001",
        plan=mapping_plan(),
        executor="nodrix.system.orchestrator",
        state="running",
        started_at=started,
    )

    with pytest.raises(
        ValueError,
        match="terminal ExecutionRecord",
    ):
        RunRecord(
            run_id="run-001",
            execution=execution,
        )


def test_run_requires_execution_started_at() -> None:
    execution = ExecutionRecord(
        execution_id="execution-001",
        plan=mapping_plan(),
        executor="nodrix.system.orchestrator",
        state="completed",
    )

    with pytest.raises(
        ValueError,
        match="execution.started_at",
    ):
        RunRecord(
            run_id="run-001",
            execution=execution,
        )


def test_run_requires_execution_finished_at() -> None:
    started = datetime.now(timezone.utc)

    execution = ExecutionRecord(
        execution_id="execution-001",
        plan=mapping_plan(),
        executor="nodrix.system.orchestrator",
        state="completed",
        started_at=started,
    )

    with pytest.raises(
        ValueError,
        match="execution.finished_at",
    ):
        RunRecord(
            run_id="run-001",
            execution=execution,
        )


@pytest.mark.parametrize(
    ("state", "successful"),
    [
        ("completed", True),
        ("stopped", True),
        ("failed", False),
        ("cancelled", False),
    ],
)
def test_run_preserves_terminal_result(
    state: str,
    successful: bool,
) -> None:
    run = RunRecord(
        run_id=f"run-{state}",
        execution=finished_execution(
            state=state,
        ),
    )

    assert run.state.value == state
    assert run.successful is successful


def test_run_summary_is_copied_and_read_only() -> None:
    summary = {
        "messages": 1000,
        "duration_seconds": 10.0,
    }

    run = RunRecord(
        run_id="run-001",
        execution=finished_execution(),
        summary=summary,
    )

    summary["messages"] = 9999

    assert isinstance(run.summary, MappingProxyType)
    assert run.summary["messages"] == 1000

    with pytest.raises(TypeError):
        run.summary["messages"] = 5  # type: ignore[index]


def test_run_metadata_is_copied_and_read_only() -> None:
    metadata = {
        "source": "system-orchestrator",
    }

    run = RunRecord(
        run_id="run-001",
        execution=finished_execution(),
        metadata=metadata,
    )

    metadata["source"] = "changed"

    assert isinstance(run.metadata, MappingProxyType)
    assert run.metadata["source"] == "system-orchestrator"

    with pytest.raises(TypeError):
        run.metadata["source"] = "other"  # type: ignore[index]


def test_repeated_executions_create_different_runs() -> None:
    first = RunRecord(
        run_id="run-001",
        execution=finished_execution(
            execution_id="execution-001",
        ),
    )

    second = RunRecord(
        run_id="run-002",
        execution=finished_execution(
            execution_id="execution-002",
        ),
    )

    assert first.subject == second.subject
    assert first.subject_revision == second.subject_revision
    assert first.plan.operation == second.plan.operation

    assert first.execution_id != second.execution_id
    assert first.run_id != second.run_id
