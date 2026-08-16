from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from nodrix.execution_history import persist_execution
from nodrix.model import (
    ArtifactRecord,
    DatasetRecord,
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RevisionRef,
    materialized_lineage_relations,
)
from nodrix.run_document_validation import (
    RunDocumentValidationError,
    validate_run_document,
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


def _execution() -> ExecutionRecord:
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
        plan_id="plan-provenance-validation",
        kind="workflow",
        operation=operation,
        subject_revision=revision,
        payload={},
    )

    return ExecutionRecord(
        execution_id="execution-provenance-validation",
        plan=plan,
        executor="nodrix.workflow",
        state="completed",
        started_at=_time(12),
        finished_at=_time(13),
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
    *,
    name: str = "global-map",
    digest: str,
) -> ArtifactRecord:
    entity = EntityRef(
        kind="artifact",
        namespace="project",
        name=name,
    )

    return ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            digest * 64,
        ),
        kind="mapping.point-cloud",
        uri=f"artifacts/{name}-{digest}.ply",
    )


def _case(
    tmp_path: Path,
) -> tuple[
    dict[str, Any],
    DatasetRecord,
    ArtifactRecord,
    ArtifactRecord,
]:
    source = _dataset()

    previous = _artifact(
        digest="c",
    )

    current = _artifact(
        digest="d",
    )

    lineage = materialized_lineage_relations(
        current,
        derived_from=(source,),
        supersedes=(previous,),
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

    return (
        document,
        source,
        previous,
        current,
    )


def _relation(
    document: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    return next(
        relation
        for relation in document["relations"]
        if relation["kind"] == kind
    )


def test_valid_materialized_provenance_passes(
    tmp_path: Path,
) -> None:
    document, _, _, _ = _case(
        tmp_path
    )

    validated = validate_run_document(
        document
    )

    assert len(
        validated.relations.relations
    ) == 6


@pytest.mark.parametrize(
    "kind",
    [
        "consumes",
        "produces",
    ],
)
def test_run_io_must_originate_from_this_run(
    tmp_path: Path,
    kind: str,
) -> None:
    document, source, _, _ = _case(
        tmp_path
    )

    relation = _relation(
        document,
        kind,
    )

    relation["source"] = str(
        source.revision
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="must originate from this run",
    ):
        validate_run_document(
            document
        )


@pytest.mark.parametrize(
    "kind",
    [
        "consumes",
        "produces",
    ],
)
def test_run_io_must_target_revision(
    tmp_path: Path,
    kind: str,
) -> None:
    document, source, _, _ = _case(
        tmp_path
    )

    relation = _relation(
        document,
        kind,
    )

    relation["target"] = str(
        source.entity
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="must target a RevisionRef",
    ):
        validate_run_document(
            document
        )


def test_derived_from_requires_revision_endpoints(
    tmp_path: Path,
) -> None:
    document, source, _, _ = _case(
        tmp_path
    )

    relation = _relation(
        document,
        "derived_from",
    )

    relation["source"] = str(
        source.entity
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="derived_from must connect RevisionRef",
    ):
        validate_run_document(
            document
        )


def test_revision_cannot_be_derived_from_itself(
    tmp_path: Path,
) -> None:
    document, _, _, current = _case(
        tmp_path
    )

    relation = _relation(
        document,
        "derived_from",
    )

    relation["target"] = str(
        current.revision
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="derived from itself",
    ):
        validate_run_document(
            document
        )


def test_supersedes_requires_revision_endpoints(
    tmp_path: Path,
) -> None:
    document, _, _, current = _case(
        tmp_path
    )

    relation = _relation(
        document,
        "supersedes",
    )

    relation["target"] = str(
        current.entity
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="supersedes must connect RevisionRef",
    ):
        validate_run_document(
            document
        )


def test_revision_cannot_supersede_itself(
    tmp_path: Path,
) -> None:
    document, _, _, current = _case(
        tmp_path
    )

    relation = _relation(
        document,
        "supersedes",
    )

    relation["target"] = str(
        current.revision
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="supersede itself",
    ):
        validate_run_document(
            document
        )


def test_supersedes_requires_same_logical_entity(
    tmp_path: Path,
) -> None:
    document, _, _, _ = _case(
        tmp_path
    )

    other = _artifact(
        name="other-map",
        digest="e",
    )

    relation = _relation(
        document,
        "supersedes",
    )

    relation["target"] = str(
        other.revision
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="same logical entity",
    ):
        validate_run_document(
            document
        )


def test_custom_relation_remains_extensible(
    tmp_path: Path,
) -> None:
    document, source, _, current = _case(
        tmp_path
    )

    document["relations"].append(
        {
            "source": str(
                current.revision
            ),
            "kind": "mapping.aligned_with",
            "target": str(
                source.revision
            ),
            "metadata": {},
        }
    )

    validated = validate_run_document(
        document
    )

    assert any(
        relation.kind_name
        == "mapping.aligned_with"
        for relation
        in validated.relations.relations
    )
