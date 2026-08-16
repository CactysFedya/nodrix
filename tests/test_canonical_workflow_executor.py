from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from nodrix.model import (
    BUILD,
    SYSTEM_EXECUTION,
    ExecutionState,
    EntityRef,
    Operation,
    RevisionRef,
)
from nodrix.workflow_canonical import workflow_plan_record
from nodrix.workflow_execution import (
    WorkflowRunResult,
    WorkflowStepResult,
)
from nodrix.workflow_executor import (
    WORKFLOW_EXECUTOR,
    WorkflowExecutor,
)
from nodrix.workflow_planning import (
    WorkflowPlanResult,
    WorkflowStepPlan,
)


def _time(hour: int) -> datetime:
    return datetime(
        2026,
        8,
        16,
        hour,
        0,
        tzinfo=timezone.utc,
    )


def _subject() -> tuple[EntityRef, RevisionRef]:
    entity = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )
    revision = RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )
    return entity, revision


def _domain_plan() -> WorkflowPlanResult:
    return WorkflowPlanResult(
        name="build",
        root="/workspace/project",
        workflow_path="/workspace/project/workflows/build.yaml",
        environment="robot",
        generated=False,
        steps=(
            WorkflowStepPlan(
                index=1,
                step_id="compile",
                status="planned",
                recipe="cmake",
                depends_on=(),
                cache="miss",
                reasons=("cache fingerprint changed",),
                command="cmake --build build",
                cwd=".",
            ),
        ),
    )


def _canonical_plan(
    *,
    parameters: dict[str, object] | None = None,
):
    entity, revision = _subject()
    operation = Operation(
        kind=BUILD,
        subject=entity,
        subject_revision=revision,
        parameters=parameters or {},
    )

    return workflow_plan_record(
        _domain_plan(),
        operation=operation,
        subject_revision=revision,
    )


def _result(
    *,
    status: str = "succeeded",
) -> WorkflowRunResult:
    return WorkflowRunResult(
        name="build",
        status=status,
        root="/workspace/project",
        workflow_path="/workspace/project/workflows/build.yaml",
        run_directory=(
            "/workspace/project/.nodrix/operations/"
            "20260816T120000.000000Z-build"
        ),
        started_at="2026-08-16T12:00:00+00:00",
        finished_at="2026-08-16T12:00:01+00:00",
        steps=(
            WorkflowStepResult(
                step_id="compile",
                status=(
                    "succeeded"
                    if status == "succeeded"
                    else "failed"
                ),
                command="cmake --build build",
                returncode=0 if status == "succeeded" else 1,
                duration_seconds=1.0,
                log_path="/tmp/compile.log",
            ),
        ),
    )


def test_workflow_executor_returns_completed_execution_record() -> None:
    calls: list[
        tuple[WorkflowPlanResult, dict[str, object]]
    ] = []

    def runner(
        domain_plan: WorkflowPlanResult,
        **kwargs,
    ):
        calls.append((domain_plan, kwargs))
        return _result()

    times = iter((_time(12), _time(13)))

    executor = WorkflowExecutor(
        runner=runner,
        clock=lambda: next(times),
    )

    plan = _canonical_plan(
        parameters={
            "force": True,
            "dry_run": False,
        }
    )

    record = executor.execute(plan)

    assert record.plan is plan
    assert record.executor == WORKFLOW_EXECUTOR
    assert record.state is ExecutionState.COMPLETED
    assert record.successful
    assert record.terminal
    assert record.started_at == _time(12)
    assert record.finished_at == _time(13)
    assert record.execution_id.startswith("workflow-")

    assert len(calls) == 1

    called_plan, called_parameters = calls[0]

    assert called_plan is plan.payload
    assert called_parameters == {
        "dry_run": False,
        "force": True,
    }

    assert record.details["workflow"] == "build"
    assert record.details["workflow_status"] == "succeeded"
    assert record.details["step_count"] == 1


def test_workflow_executor_maps_failed_result_to_failed_execution() -> None:
    def runner(name: str, **kwargs):
        del name, kwargs
        return _result(status="failed")

    times = iter((_time(12), _time(13)))

    record = WorkflowExecutor(
        runner=runner,
        clock=lambda: next(times),
    ).execute(_canonical_plan())

    assert record.state is ExecutionState.FAILED
    assert record.terminal
    assert not record.successful
    assert record.details["workflow_status"] == "failed"


def test_workflow_executor_records_runner_exception_as_failed_execution() -> None:
    def runner(name: str, **kwargs):
        del name, kwargs
        raise RuntimeError("build exploded")

    times = iter((_time(12), _time(13)))

    record = WorkflowExecutor(
        runner=runner,
        clock=lambda: next(times),
    ).execute(_canonical_plan())

    assert record.state is ExecutionState.FAILED
    assert record.terminal
    assert record.details["exception_type"] == "RuntimeError"
    assert record.details["message"] == "build exploded"


def test_workflow_executor_requires_workflow_plan_kind() -> None:
    plan = replace(
        _canonical_plan(),
        kind=SYSTEM_EXECUTION,
    )

    with pytest.raises(
        ValueError,
        match="requires a workflow PlanRecord",
    ):
        WorkflowExecutor().execute(plan)


def test_workflow_executor_requires_workflow_payload() -> None:
    plan = replace(
        _canonical_plan(),
        payload=object(),
    )

    with pytest.raises(
        TypeError,
        match="payload must be a WorkflowPlanResult",
    ):
        WorkflowExecutor().execute(plan)


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("force", "yes"),
        ("dry_run", 1),
    ],
)
def test_workflow_executor_rejects_non_boolean_execution_parameters(
    parameter: str,
    value: object,
) -> None:
    plan = _canonical_plan(
        parameters={parameter: value},
    )

    with pytest.raises(
        TypeError,
        match=rf"operation parameter '{parameter}' must be a boolean",
    ):
        WorkflowExecutor().execute(plan)


def test_workflow_executor_defaults_execution_controls_to_false() -> None:
    captured: dict[str, object] = {}

    def runner(name: str, **kwargs):
        captured["name"] = name
        captured.update(kwargs)
        return _result()

    times = iter((_time(12), _time(13)))

    WorkflowExecutor(
        runner=runner,
        clock=lambda: next(times),
    ).execute(_canonical_plan())

    assert captured["force"] is False
    assert captured["dry_run"] is False


def test_workflow_executor_requires_timezone_aware_clock() -> None:
    executor = WorkflowExecutor(
        runner=lambda *args, **kwargs: _result(),
        clock=lambda: datetime(2026, 8, 16, 12, 0),
    )

    with pytest.raises(
        ValueError,
        match="clock result must be timezone-aware",
    ):
        executor.execute(_canonical_plan())


def test_workflow_executor_treats_dry_run_as_completed_operation() -> None:
    def runner(name: str, **kwargs):
        del name
        assert kwargs["dry_run"] is True
        return _result(status="planned")

    times = iter((_time(12), _time(13)))

    record = WorkflowExecutor(
        runner=runner,
        clock=lambda: next(times),
    ).execute(
        _canonical_plan(
            parameters={"dry_run": True},
        )
    )

    assert record.state is ExecutionState.COMPLETED
    assert record.successful
    assert record.details["workflow_status"] == "planned"
    assert record.details["dry_run"] is True
