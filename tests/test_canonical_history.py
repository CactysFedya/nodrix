from datetime import datetime, timedelta, timezone

import pytest

from nodrix.model import (
    EXECUTED_AS,
    RECORDED_AS,
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RecordRef,
    RevisionRef,
    execution_record_ref,
    plan_record_ref,
    record_run,
    run_lifecycle_relations,
    run_record_ref,
)


def canonical_plan() -> PlanRecord:
    system = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )

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
        },
    )


def terminal_execution(
    *,
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
        execution_id="execution-001",
        plan=canonical_plan(),
        executor="nodrix.system.orchestrator",
        state=state,
        started_at=started,
        finished_at=(
            started + timedelta(seconds=10)
        ),
    )


def test_plan_record_ref() -> None:
    ref = plan_record_ref(
        canonical_plan()
    )

    assert ref == RecordRef(
        kind="plan",
        record_id="plan-001",
    )


def test_execution_record_ref() -> None:
    execution = terminal_execution()

    ref = execution_record_ref(
        execution
    )

    assert ref == RecordRef(
        kind="execution",
        record_id="execution-001",
    )


def test_record_run_creates_durable_run() -> None:
    execution = terminal_execution()

    run = record_run(
        execution,
        run_id="run-001",
        summary={
            "duration_seconds": 10.0,
        },
        metadata={
            "source": "system-runtime",
        },
    )

    assert run.run_id == "run-001"
    assert run.execution == execution
    assert run.execution_id == "execution-001"
    assert run.subject == execution.subject
    assert run.subject_revision == (
        execution.subject_revision
    )
    assert run.successful

    assert (
        run.summary["duration_seconds"]
        == 10.0
    )

    assert (
        run.metadata["source"]
        == "system-runtime"
    )


@pytest.mark.parametrize(
    "state",
    [
        "running",
        "prepared",
    ],
)
def test_record_run_rejects_live_execution(
    state: str,
) -> None:
    started = datetime.now(
        timezone.utc
    )

    execution = ExecutionRecord(
        execution_id="execution-live",
        plan=canonical_plan(),
        executor="executor",
        state=state,
        started_at=started,
    )

    with pytest.raises(
        ValueError,
        match="terminal ExecutionRecord",
    ):
        record_run(
            execution,
            run_id="run-001",
        )


def test_failed_execution_can_be_recorded_as_run() -> None:
    run = record_run(
        terminal_execution(
            state="failed",
        ),
        run_id="run-failed",
    )

    assert run.state.value == "failed"
    assert not run.successful


def test_run_record_ref() -> None:
    run = record_run(
        terminal_execution(),
        run_id="run-001",
    )

    assert run_record_ref(run) == RecordRef(
        kind="run",
        record_id="run-001",
    )


def test_run_lifecycle_relations() -> None:
    run = record_run(
        terminal_execution(),
        run_id="run-001",
    )

    graph = run_lifecycle_relations(
        run
    )

    assert len(graph.relations) == 2

    executed = graph.relations[0]
    recorded = graph.relations[1]

    assert executed.source == RecordRef(
        kind="plan",
        record_id="plan-001",
    )

    assert executed.kind == EXECUTED_AS

    assert executed.target == RecordRef(
        kind="execution",
        record_id="execution-001",
    )

    assert recorded.source == RecordRef(
        kind="execution",
        record_id="execution-001",
    )

    assert recorded.kind == RECORDED_AS

    assert recorded.target == RecordRef(
        kind="run",
        record_id="run-001",
    )


def test_lifecycle_graph_supports_queries() -> None:
    run = record_run(
        terminal_execution(),
        run_id="run-001",
    )

    graph = run_lifecycle_relations(
        run
    )

    plan_ref = plan_record_ref(
        run.plan
    )
    execution_ref = execution_record_ref(
        run.execution
    )
    canonical_run_ref = run_record_ref(
        run
    )

    assert graph.outgoing(
        plan_ref,
        kind=EXECUTED_AS,
    )[0].target == execution_ref

    assert graph.outgoing(
        execution_ref,
        kind=RECORDED_AS,
    )[0].target == canonical_run_ref

    assert graph.incoming(
        canonical_run_ref,
        kind=RECORDED_AS,
    )[0].source == execution_ref


def test_same_execution_can_only_differ_by_run_record_identity() -> None:
    execution = terminal_execution()

    first = record_run(
        execution,
        run_id="run-001",
    )

    second = record_run(
        execution,
        run_id="run-archive-copy",
    )

    assert first.execution == second.execution
    assert first.subject == second.subject

    assert (
        run_record_ref(first)
        != run_record_ref(second)
    )


def test_run_id_generation_is_not_owned_by_model() -> None:
    execution = terminal_execution()

    with pytest.raises(
        TypeError,
    ):
        record_run(  # type: ignore[call-arg]
            execution,
        )
