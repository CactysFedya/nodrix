from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nodrix.execution_history import persist_execution
from nodrix.model import (
    CONSUMES,
    DERIVED_FROM,
    PRODUCES,
    SUPERSEDES,
    ArtifactRecord,
    DatasetRecord,
    EntityRef,
    ExecutionRecord,
    ExecutionState,
    Operation,
    PlanRecord,
    RevisionRef,
    materialized_lineage_relations,
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
    execution_id: str = "execution-lineage",
) -> ExecutionRecord:
    subject = EntityRef(
        kind="project",
        namespace="workspace",
        name="mapping",
    )

    revision = RevisionRef.from_sha256(
        subject,
        "a" * 64,
    )

    operation = Operation(
        kind="run",
        subject=subject,
        subject_revision=revision,
    )

    plan = PlanRecord(
        plan_id=f"plan-{execution_id}",
        kind="workflow",
        operation=operation,
        subject_revision=revision,
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
        name="cloud",
    )

    return DatasetRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            "b" * 64,
        ),
        kind="point-cloud",
        uri="datasets/cloud.ndrx",
    )


def _artifact(
    digest: str,
    uri: str,
) -> ArtifactRecord:
    entity = EntityRef(
        kind="artifact",
        namespace="project",
        name="global-map",
    )

    return ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            digest * 64,
        ),
        kind="mapping.point-cloud",
        uri=uri,
    )


def _materialized_case():
    source = _dataset()

    previous = _artifact(
        "c",
        "artifacts/map-v1.ply",
    )

    current = _artifact(
        "d",
        "artifacts/map-v2.ply",
    )

    lineage = materialized_lineage_relations(
        current,
        derived_from=(source,),
        supersedes=(previous,),
    )

    return (
        source,
        previous,
        current,
        lineage,
    )


def test_persist_execution_combines_lifecycle_io_and_lineage(
    tmp_path: Path,
) -> None:
    source, previous, current, lineage = (
        _materialized_case()
    )

    persisted = persist_execution(
        _execution(),
        project=tmp_path,
        inputs=(source,),
        outputs=(current,),
        additional_provenance=lineage,
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
        "derived_from",
        "supersedes",
    )

    assert relations[2].kind == CONSUMES
    assert relations[2].target == source.revision

    assert relations[3].kind == PRODUCES
    assert relations[3].target == current.revision

    assert relations[4].kind == DERIVED_FROM
    assert relations[4].source == current.revision
    assert relations[4].target == source.revision

    assert relations[5].kind == SUPERSEDES
    assert relations[5].source == current.revision
    assert relations[5].target == previous.revision


def test_combined_lineage_is_serialized_and_validated(
    tmp_path: Path,
) -> None:
    source, previous, current, lineage = (
        _materialized_case()
    )

    persisted = persist_execution(
        _execution(),
        project=tmp_path,
        inputs=(source,),
        outputs=(current,),
        additional_provenance=lineage,
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
        "derived_from",
        "supersedes",
    ]

    validated = read_run_document(
        persisted.path
    )

    assert tuple(
        relation.kind_name
        for relation
        in validated.relations.relations
    ) == (
        "executed_as",
        "recorded_as",
        "consumes",
        "produces",
        "derived_from",
        "supersedes",
    )


def test_additional_provenance_none_preserves_existing_contract(
    tmp_path: Path,
) -> None:
    persisted = persist_execution(
        _execution(),
        project=tmp_path,
    )

    assert tuple(
        relation.kind_name
        for relation
        in persisted.provenance.relations
    ) == (
        "executed_as",
        "recorded_as",
    )


def test_invalid_additional_provenance_is_rejected_before_write(
    tmp_path: Path,
) -> None:
    execution = _execution(
        execution_id="execution-invalid-provenance",
    )

    with pytest.raises(
        TypeError,
        match="additional_provenance",
    ):
        persist_execution(
            execution,
            project=tmp_path,
            additional_provenance=object(),  # type: ignore[arg-type]
        )

    path = (
        tmp_path
        / ".nodrix"
        / "runs"
        / execution.execution_id
        / "run.json"
    )

    assert not path.exists()


def test_failed_execution_preserves_materialized_lineage(
    tmp_path: Path,
) -> None:
    source, previous, current, lineage = (
        _materialized_case()
    )

    persisted = persist_execution(
        _execution(
            state=ExecutionState.FAILED,
            execution_id="execution-failed-lineage",
        ),
        project=tmp_path,
        inputs=(source,),
        outputs=(current,),
        additional_provenance=lineage,
    )

    assert persisted.run.state is ExecutionState.FAILED

    assert any(
        relation.kind == DERIVED_FROM
        and relation.source == current.revision
        and relation.target == source.revision
        for relation
        in persisted.provenance.relations
    )

    assert any(
        relation.kind == SUPERSEDES
        and relation.source == current.revision
        and relation.target == previous.revision
        for relation
        in persisted.provenance.relations
    )
