from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from nodrix.model import (
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RevisionRef,
    RunRecord,
)
from nodrix.run_comparison import (
    CanonicalRunComparison,
    compare_run_records,
)


STARTED = datetime(
    2026,
    8,
    19,
    10,
    0,
    tzinfo=timezone.utc,
)


def _system() -> EntityRef:
    return EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )


def _plan(
    *,
    plan_id: str = "plan-001",
    revision: str = "a" * 64,
) -> PlanRecord:
    system = _system()

    return PlanRecord(
        plan_id=plan_id,
        kind="system-execution",
        operation=Operation(
            kind="run",
            subject=system,
        ),
        subject_revision=(
            RevisionRef.from_sha256(
                system,
                revision,
            )
        ),
        payload={
            "target": "pi5",
            "backend": "local",
        },
    )


def _run(
    *,
    run_id: str,
    execution_id: str,
    duration_seconds: float = 10.0,
    state: str = "completed",
    plan: PlanRecord | None = None,
    executor: str = "nodrix.system.orchestrator",
) -> RunRecord:
    resolved_plan = (
        plan
        if plan is not None
        else _plan()
    )

    execution = ExecutionRecord(
        execution_id=execution_id,
        plan=resolved_plan,
        executor=executor,
        state=state,
        started_at=STARTED,
        finished_at=(
            STARTED
            + timedelta(
                seconds=duration_seconds
            )
        ),
    )

    return RunRecord(
        run_id=run_id,
        execution=execution,
    )


def test_repeated_runs_of_same_plan_are_same_workload() -> None:
    first = _run(
        run_id="run-001",
        execution_id="execution-001",
        duration_seconds=10.0,
    )

    second = _run(
        run_id="run-002",
        execution_id="execution-002",
        duration_seconds=12.0,
    )

    comparison = compare_run_records(
        first,
        second,
    )

    assert isinstance(
        comparison,
        CanonicalRunComparison,
    )

    assert (
        comparison.first.run_id
        == "run-001"
    )

    assert (
        comparison.second.run_id
        == "run-002"
    )

    assert (
        comparison.first.execution_id
        != comparison.second.execution_id
    )

    assert (
        comparison.provenance.same_plan
        is True
    )

    assert (
        comparison.provenance.same_subject_revision
        is True
    )

    assert (
        comparison.provenance.same_operation
        is True
    )

    assert (
        comparison.provenance.same_workload
        is True
    )


def test_duration_comparison_uses_second_minus_first() -> None:
    comparison = compare_run_records(
        _run(
            run_id="run-001",
            execution_id="execution-001",
            duration_seconds=10.0,
        ),
        _run(
            run_id="run-002",
            execution_id="execution-002",
            duration_seconds=12.5,
        ),
    )

    assert (
        comparison.first.duration_seconds
        == 10.0
    )

    assert (
        comparison.second.duration_seconds
        == 12.5
    )

    assert (
        comparison.outcome.duration_delta_seconds
        == 2.5
    )

    assert (
        comparison.outcome.duration_percent
        == 25.0
    )


def test_zero_first_duration_has_no_percentage_change() -> None:
    comparison = compare_run_records(
        _run(
            run_id="run-001",
            execution_id="execution-001",
            duration_seconds=0.0,
        ),
        _run(
            run_id="run-002",
            execution_id="execution-002",
            duration_seconds=1.0,
        ),
    )

    assert (
        comparison.outcome.duration_delta_seconds
        == 1.0
    )

    assert (
        comparison.outcome.duration_percent
        is None
    )


def test_different_plan_identity_is_not_same_workload() -> None:
    first = _run(
        run_id="run-001",
        execution_id="execution-001",
        plan=_plan(
            plan_id="plan-001"
        ),
    )

    second = _run(
        run_id="run-002",
        execution_id="execution-002",
        plan=_plan(
            plan_id="plan-002"
        ),
    )

    comparison = compare_run_records(
        first,
        second,
    )

    assert (
        comparison.provenance.same_subject_revision
        is True
    )

    assert (
        comparison.provenance.same_operation
        is True
    )

    assert (
        comparison.provenance.same_plan
        is False
    )

    assert (
        comparison.provenance.same_workload
        is False
    )


def test_different_subject_revision_is_explicit() -> None:
    first = _run(
        run_id="run-001",
        execution_id="execution-001",
        plan=_plan(
            plan_id="plan-001",
            revision="a" * 64,
        ),
    )

    second = _run(
        run_id="run-002",
        execution_id="execution-002",
        plan=_plan(
            plan_id="plan-002",
            revision="b" * 64,
        ),
    )

    comparison = compare_run_records(
        first,
        second,
    )

    assert (
        comparison.provenance.same_subject
        is True
    )

    assert (
        comparison.provenance.same_subject_revision
        is False
    )

    assert (
        comparison.provenance.same_workload
        is False
    )


def test_executor_difference_is_separate_from_workload_identity() -> None:
    first = _run(
        run_id="run-001",
        execution_id="execution-001",
        executor="executor-a",
    )

    second = _run(
        run_id="run-002",
        execution_id="execution-002",
        executor="executor-b",
    )

    comparison = compare_run_records(
        first,
        second,
    )

    assert (
        comparison.provenance.same_workload
        is True
    )

    assert (
        comparison.provenance.same_executor
        is False
    )


def test_terminal_outcome_difference_is_explicit() -> None:
    first = _run(
        run_id="run-001",
        execution_id="execution-001",
        state="completed",
    )

    second = _run(
        run_id="run-002",
        execution_id="execution-002",
        state="failed",
    )

    comparison = compare_run_records(
        first,
        second,
    )

    assert (
        comparison.outcome.same_state
        is False
    )

    assert (
        comparison.outcome.both_successful
        is False
    )

    assert (
        comparison.first.state
        == "completed"
    )

    assert (
        comparison.second.state
        == "failed"
    )


def test_comparison_document_is_deterministic() -> None:
    first = _run(
        run_id="run-001",
        execution_id="execution-001",
        duration_seconds=10.0,
    )

    second = _run(
        run_id="run-002",
        execution_id="execution-002",
        duration_seconds=11.0,
    )

    first_result = compare_run_records(
        first,
        second,
    )

    second_result = compare_run_records(
        first,
        second,
    )

    assert (
        first_result
        == second_result
    )

    assert (
        first_result.to_dict()
        == second_result.to_dict()
    )

    document = first_result.to_dict()

    assert set(document) == {
        "first",
        "second",
        "provenance",
        "outcome",
    }

    assert (
        document["first"]["planId"]
        == "plan-001"
    )

    assert (
        document["provenance"]["sameWorkload"]
        is True
    )

    assert (
        document["outcome"]["durationDeltaSeconds"]
        == 1.0
    )


@pytest.mark.parametrize(
    "position",
    (
        "first",
        "second",
    ),
)
def test_compare_requires_canonical_run_records(
    position,
) -> None:
    run = _run(
        run_id="run-001",
        execution_id="execution-001",
    )

    with pytest.raises(
        TypeError,
        match=(
            "first must be a RunRecord"
            if position == "first"
            else "second must be a RunRecord"
        ),
    ):
        if position == "first":
            compare_run_records(
                {},  # type: ignore[arg-type]
                run,
            )
        else:
            compare_run_records(
                run,
                {},  # type: ignore[arg-type]
            )
