from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nodrix.model import (
    BUILD,
    ExecutionRecord,
    ExecutionState,
    EntityRef,
    Operation,
    PlanRecord,
    RevisionRef,
    SYSTEM_EXECUTION,
)
from nodrix.run_document_validation import read_run_document
from nodrix.workflow_canonical import workflow_plan_record
from nodrix.workflow_execution import (
    WorkflowRunResult,
    WorkflowStepResult,
)
from nodrix.workflow_executor import (
    WORKFLOW_EXECUTOR,
    WorkflowExecutor,
)
from nodrix.workflow_history import (
    PersistedWorkflowRun,
    persist_workflow_execution,
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


def _canonical_plan():
    entity = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )
    revision = RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )
    operation = Operation(
        kind=BUILD,
        subject=entity,
        subject_revision=revision,
    )
    domain_plan = WorkflowPlanResult(
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
                reasons=("cache changed",),
                command="cmake --build build",
                cwd=".",
            ),
        ),
    )

    return workflow_plan_record(
        domain_plan,
        operation=operation,
        subject_revision=revision,
    )


def _workflow_result(
    *,
    status: str = "succeeded",
) -> WorkflowRunResult:
    return WorkflowRunResult(
        name="build",
        status=status,
        root="/workspace/project",
        workflow_path="/workspace/project/workflows/build.yaml",
        run_directory="/workspace/project/.nodrix/operations/build",
        started_at="2026-08-16T12:00:00+00:00",
        finished_at="2026-08-16T13:00:00+00:00",
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


def _execution(
    *,
    status: str = "succeeded",
) -> ExecutionRecord:
    def runner(name: str, **kwargs):
        del name, kwargs
        return _workflow_result(status=status)

    times = iter((_time(12), _time(13)))

    return WorkflowExecutor(
        runner=runner,
        clock=lambda: next(times),
    ).execute(_canonical_plan())


def test_persist_workflow_execution_writes_canonical_run(
    tmp_path: Path,
) -> None:
    execution = _execution()

    persisted = persist_workflow_execution(
        execution,
        project=tmp_path,
    )

    assert isinstance(
        persisted,
        PersistedWorkflowRun,
    )
    assert persisted.run.execution is execution
    assert persisted.run.run_id == execution.execution_id

    expected = (
        tmp_path
        / ".nodrix"
        / "runs"
        / execution.execution_id
        / "run.json"
    )

    assert persisted.path == expected
    assert expected.is_file()

    document = json.loads(
        expected.read_text(encoding="utf-8")
    )

    assert document["schema"] == "nodrix.run/v1"
    assert document["kind"] == "Run"
    assert document["id"] == execution.execution_id
    assert document["status"] == "completed"
    assert document["successful"] is True
    assert document["operation"]["kind"] == "build"
    assert document["plan"]["kind"] == "workflow"
    assert document["execution"]["executor"] == WORKFLOW_EXECUTOR
    assert document["execution"]["state"] == "completed"


def test_workflow_history_persists_lifecycle_relations(
    tmp_path: Path,
) -> None:
    persisted = persist_workflow_execution(
        _execution(),
        project=tmp_path,
    )

    assert tuple(
        relation.kind_name
        for relation in persisted.provenance.relations
    ) == (
        "executed_as",
        "recorded_as",
    )

    document = json.loads(
        persisted.path.read_text(encoding="utf-8")
    )

    assert [
        relation["kind"]
        for relation in document["relations"]
    ] == [
        "executed_as",
        "recorded_as",
    ]


def test_workflow_history_document_passes_canonical_validation(
    tmp_path: Path,
) -> None:
    persisted = persist_workflow_execution(
        _execution(),
        project=tmp_path,
    )

    validated = read_run_document(
        persisted.path
    )

    assert validated.document["id"] == persisted.run.run_id
    assert validated.document["plan"]["kind"] == "workflow"


def test_failed_workflow_execution_is_durable_history(
    tmp_path: Path,
) -> None:
    execution = _execution(status="failed")

    persisted = persist_workflow_execution(
        execution,
        project=tmp_path,
    )

    assert persisted.run.state is ExecutionState.FAILED
    assert not persisted.run.successful

    document = json.loads(
        persisted.path.read_text(encoding="utf-8")
    )

    assert document["status"] == "failed"
    assert document["successful"] is False


def test_workflow_history_write_is_idempotent(
    tmp_path: Path,
) -> None:
    execution = _execution()

    first = persist_workflow_execution(
        execution,
        project=tmp_path,
    )
    second = persist_workflow_execution(
        execution,
        project=tmp_path,
    )

    assert first.path == second.path
    assert first.run == second.run
    assert (
        first.path.read_text(encoding="utf-8")
        == second.path.read_text(encoding="utf-8")
    )


def test_workflow_history_accepts_explicit_run_metadata(
    tmp_path: Path,
) -> None:
    persisted = persist_workflow_execution(
        _execution(),
        project=tmp_path,
        run_id="build-run-001",
        summary={"result": "ok"},
        metadata={"source": "unified-operations"},
    )

    assert persisted.run.run_id == "build-run-001"
    assert persisted.run.summary["result"] == "ok"
    assert persisted.run.metadata["source"] == "unified-operations"

    document = json.loads(
        persisted.path.read_text(encoding="utf-8")
    )

    assert document["summary"] == {"result": "ok"}
    assert document["metadata"] == {
        "source": "unified-operations"
    }


def test_workflow_history_rejects_non_workflow_plan(
    tmp_path: Path,
) -> None:
    execution = _execution()

    wrong_plan = PlanRecord(
        plan_id="system-plan-test",
        kind=SYSTEM_EXECUTION,
        operation=execution.operation,
        subject_revision=execution.subject_revision,
        payload=object(),
    )

    wrong_execution = ExecutionRecord(
        execution_id="system-test",
        plan=wrong_plan,
        executor=WORKFLOW_EXECUTOR,
        state=ExecutionState.COMPLETED,
        started_at=_time(12),
        finished_at=_time(13),
    )

    with pytest.raises(
        ValueError,
        match="requires a workflow PlanRecord",
    ):
        persist_workflow_execution(
            wrong_execution,
            project=tmp_path,
        )


def test_workflow_history_rejects_other_executor(
    tmp_path: Path,
) -> None:
    execution = _execution()

    wrong_execution = ExecutionRecord(
        execution_id=execution.execution_id,
        plan=execution.plan,
        executor="nodrix.system.orchestrator",
        state=execution.state,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        details=execution.details,
    )

    with pytest.raises(
        ValueError,
        match="requires a WorkflowExecutor execution",
    ):
        persist_workflow_execution(
            wrong_execution,
            project=tmp_path,
        )


def test_workflow_history_rejects_non_terminal_execution(
    tmp_path: Path,
) -> None:
    execution = ExecutionRecord(
        execution_id="workflow-live",
        plan=_canonical_plan(),
        executor=WORKFLOW_EXECUTOR,
        state=ExecutionState.RUNNING,
        started_at=_time(12),
    )

    with pytest.raises(
        ValueError,
        match="requires a terminal ExecutionRecord",
    ):
        persist_workflow_execution(
            execution,
            project=tmp_path,
        )
