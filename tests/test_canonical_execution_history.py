from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nodrix.execution_history import (
    PersistedRun,
    persist_execution,
)
from nodrix.model import (
    BUILD,
    WORKFLOW,
    SYSTEM_EXECUTION,
    EntityRef,
    ExecutionRecord,
    ExecutionState,
    Operation,
    PlanKind,
    PlanRecord,
    RevisionRef,
)
from nodrix.run_document_validation import read_run_document


def _time(hour: int) -> datetime:
    return datetime(
        2026,
        8,
        16,
        hour,
        0,
        tzinfo=timezone.utc,
    )


def _plan(
    *,
    kind: PlanKind = WORKFLOW,
    plan_id: str = "plan-test",
) -> PlanRecord:
    entity = EntityRef(
        kind="project",
        namespace="workspace",
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

    return PlanRecord(
        plan_id=plan_id,
        kind=kind,
        operation=operation,
        subject_revision=revision,
        payload={"domain": kind.value},
    )


def _execution(
    *,
    state: ExecutionState = ExecutionState.COMPLETED,
    kind: PlanKind = WORKFLOW,
    executor: str = "nodrix.workflow",
    execution_id: str = "execution-test",
) -> ExecutionRecord:
    return ExecutionRecord(
        execution_id=execution_id,
        plan=_plan(
            kind=kind,
            plan_id=f"plan-{execution_id}",
        ),
        executor=executor,
        state=state,
        started_at=_time(12),
        finished_at=_time(13),
        details={"result": "ok"},
    )


def test_persist_execution_writes_canonical_run(
    tmp_path: Path,
) -> None:
    execution = _execution()

    persisted = persist_execution(
        execution,
        project=tmp_path,
    )

    assert isinstance(persisted, PersistedRun)
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


def test_execution_history_persists_lifecycle_relations(
    tmp_path: Path,
) -> None:
    persisted = persist_execution(
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


def test_execution_history_document_passes_validation(
    tmp_path: Path,
) -> None:
    persisted = persist_execution(
        _execution(),
        project=tmp_path,
    )

    validated = read_run_document(
        persisted.path
    )

    assert (
        validated.document["id"]
        == persisted.run.run_id
    )


def test_failed_execution_is_durable_history(
    tmp_path: Path,
) -> None:
    execution = _execution(
        state=ExecutionState.FAILED,
    )

    persisted = persist_execution(
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


def test_execution_history_write_is_idempotent(
    tmp_path: Path,
) -> None:
    execution = _execution()

    first = persist_execution(
        execution,
        project=tmp_path,
    )
    second = persist_execution(
        execution,
        project=tmp_path,
    )

    assert first.path == second.path
    assert first.run == second.run
    assert (
        first.path.read_text(encoding="utf-8")
        == second.path.read_text(encoding="utf-8")
    )


def test_execution_history_accepts_explicit_run_metadata(
    tmp_path: Path,
) -> None:
    persisted = persist_execution(
        _execution(),
        project=tmp_path,
        run_id="run-001",
        summary={"result": "ok"},
        metadata={"source": "unified-operations"},
    )

    assert persisted.run.run_id == "run-001"
    assert persisted.run.summary["result"] == "ok"
    assert (
        persisted.run.metadata["source"]
        == "unified-operations"
    )


def test_execution_history_is_not_workflow_specific(
    tmp_path: Path,
) -> None:
    execution = _execution(
        kind=SYSTEM_EXECUTION,
        executor="nodrix.system.orchestrator",
        execution_id="system-execution",
    )

    persisted = persist_execution(
        execution,
        project=tmp_path,
    )

    document = json.loads(
        persisted.path.read_text(encoding="utf-8")
    )

    assert document["plan"]["kind"] == "system-execution"
    assert (
        document["execution"]["executor"]
        == "nodrix.system.orchestrator"
    )


def test_execution_history_rejects_non_terminal_execution(
    tmp_path: Path,
) -> None:
    execution = ExecutionRecord(
        execution_id="execution-live",
        plan=_plan(),
        executor="nodrix.workflow",
        state=ExecutionState.RUNNING,
        started_at=_time(12),
    )

    with pytest.raises(
        ValueError,
        match="requires a terminal ExecutionRecord",
    ):
        persist_execution(
            execution,
            project=tmp_path,
        )


def test_execution_history_rejects_wrong_type(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        TypeError,
        match="execution must be an ExecutionRecord",
    ):
        persist_execution(
            object(),  # type: ignore[arg-type]
            project=tmp_path,
        )
