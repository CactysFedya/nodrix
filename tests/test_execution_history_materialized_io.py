from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nodrix.execution_history import persist_execution
from nodrix.model import (
    CONSUMES,
    PRODUCES,
    ArtifactRecord,
    DatasetRecord,
    EntityRef,
    ExecutionRecord,
    ExecutionState,
    Operation,
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


def _execution(
    *,
    state: ExecutionState = ExecutionState.COMPLETED,
    execution_id: str = "execution-materialized-io",
) -> ExecutionRecord:
    subject = EntityRef(
        kind="project",
        namespace="workspace",
        name="mapping",
    )

    subject_revision = RevisionRef.from_sha256(
        subject,
        "a" * 64,
    )

    operation = Operation(
        kind="run",
        subject=subject,
        subject_revision=subject_revision,
    )

    plan = PlanRecord(
        plan_id=f"plan-{execution_id}",
        kind="workflow",
        operation=operation,
        subject_revision=subject_revision,
        payload={},
    )

    return ExecutionRecord(
        execution_id=execution_id,
        plan=plan,
        executor="nodrix.workflow",
        state=state,
        started_at=_time(12),
        finished_at=_time(13),
        details={},
    )


def _dataset() -> DatasetRecord:
    entity = EntityRef(
        kind="dataset",
        namespace="project",
        name="livox-session",
    )

    return DatasetRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            "b" * 64,
        ),
        kind="recording",
        uri="datasets/livox-session.ndrx",
    )


def _artifact() -> ArtifactRecord:
    entity = EntityRef(
        kind="artifact",
        namespace="project",
        name="global-map",
    )

    return ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            "c" * 64,
        ),
        kind="mapping.point-cloud",
        uri="artifacts/global-map.ply",
    )


def test_persist_execution_without_io_preserves_lifecycle_only(
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


def test_persist_execution_records_consumed_and_produced_revisions(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    artifact = _artifact()

    persisted = persist_execution(
        _execution(),
        project=tmp_path,
        inputs=(dataset,),
        outputs=(artifact,),
    )

    relations = persisted.provenance.relations

    assert tuple(
        relation.kind_name
        for relation in relations
    ) == (
        "executed_as",
        "recorded_as",
        "consumes",
        "produces",
    )

    assert relations[2].kind == CONSUMES
    assert relations[2].target == dataset.revision

    assert relations[3].kind == PRODUCES
    assert relations[3].target == artifact.revision


def test_run_document_contains_materialized_io_relations(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    artifact = _artifact()

    persisted = persist_execution(
        _execution(),
        project=tmp_path,
        inputs=(dataset,),
        outputs=(artifact,),
    )

    document = json.loads(
        persisted.path.read_text(
            encoding="utf-8"
        )
    )

    assert [
        relation["kind"]
        for relation in document["relations"]
    ] == [
        "executed_as",
        "recorded_as",
        "consumes",
        "produces",
    ]

    assert (
        document["relations"][2]["target"]
        == str(dataset.revision)
    )

    assert (
        document["relations"][3]["target"]
        == str(artifact.revision)
    )


def test_materialized_io_document_passes_canonical_validation(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    artifact = _artifact()

    persisted = persist_execution(
        _execution(),
        project=tmp_path,
        inputs=(dataset,),
        outputs=(artifact,),
    )

    validated = read_run_document(
        persisted.path
    )

    consumed = validated.relations.outgoing(
        persisted.run and
        next(
            relation.source
            for relation in validated.relations.relations
            if relation.kind == CONSUMES
        ),
        kind=CONSUMES,
    )

    produced = tuple(
        relation
        for relation in validated.relations.relations
        if relation.kind == PRODUCES
    )

    assert len(consumed) == 1
    assert consumed[0].target == dataset.revision

    assert len(produced) == 1
    assert produced[0].target == artifact.revision


def test_persist_execution_deduplicates_same_input_revision(
    tmp_path: Path,
) -> None:
    dataset = _dataset()

    persisted = persist_execution(
        _execution(),
        project=tmp_path,
        inputs=(
            dataset,
            dataset.revision,
            dataset,
        ),
    )

    consumed = tuple(
        relation
        for relation in persisted.provenance.relations
        if relation.kind == CONSUMES
    )

    assert len(consumed) == 1
    assert consumed[0].target == dataset.revision


def test_persist_execution_accepts_raw_revision_output(
    tmp_path: Path,
) -> None:
    entity = EntityRef(
        kind="robot-map",
        namespace="user",
        name="semantic-world",
    )

    revision = RevisionRef.from_sha256(
        entity,
        "d" * 64,
    )

    persisted = persist_execution(
        _execution(),
        project=tmp_path,
        outputs=(revision,),
    )

    produced = tuple(
        relation
        for relation in persisted.provenance.relations
        if relation.kind == PRODUCES
    )

    assert len(produced) == 1
    assert produced[0].target == revision


def test_invalid_materialized_io_is_rejected_before_write(
    tmp_path: Path,
) -> None:
    execution = _execution()

    with pytest.raises(
        TypeError,
        match="provenance item",
    ):
        persist_execution(
            execution,
            project=tmp_path,
            inputs=(
                object(),  # type: ignore[arg-type]
            ),
        )

    path = (
        tmp_path
        / ".nodrix"
        / "runs"
        / execution.execution_id
        / "run.json"
    )

    assert not path.exists()


def test_failed_execution_keeps_materialized_provenance(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    artifact = _artifact()

    persisted = persist_execution(
        _execution(
            state=ExecutionState.FAILED,
            execution_id="execution-failed-materialized",
        ),
        project=tmp_path,
        inputs=(dataset,),
        outputs=(artifact,),
    )

    assert persisted.run.state is ExecutionState.FAILED

    assert any(
        relation.kind == CONSUMES
        and relation.target == dataset.revision
        for relation in persisted.provenance.relations
    )

    assert any(
        relation.kind == PRODUCES
        and relation.target == artifact.revision
        for relation in persisted.provenance.relations
    )
