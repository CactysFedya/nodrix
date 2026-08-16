from datetime import datetime, timedelta, timezone
import json

import pytest

from nodrix.model import (
    ArtifactRecord,
    DatasetRecord,
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RevisionRef,
    combine_provenance,
    record_run,
    run_io_relations,
    run_lifecycle_relations,
)
from nodrix.run_document import (
    RUN_DOCUMENT_KIND,
    RUN_DOCUMENT_SCHEMA,
    canonical_run_directory,
    dumps_run_document,
    run_to_document,
    write_run_document,
)
from nodrix.runs import load_run


def finished_run(
    *,
    run_id: str = "run-001",
    summary=None,
    metadata=None,
):
    system = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )

    operation = Operation(
        kind="run",
        subject=system,
        parameters={
            "profile": "mapping",
        },
    )

    plan = PlanRecord(
        plan_id="plan-001",
        kind="system-execution",
        operation=operation,
        subject_revision=RevisionRef.from_sha256(
            system,
            "a" * 64,
        ),
        payload={},
        metadata={
            "planner": "nodrix.system",
        },
    )

    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )

    execution = ExecutionRecord(
        execution_id="execution-001",
        plan=plan,
        executor="nodrix.system.orchestrator",
        state="completed",
        started_at=started,
        finished_at=(
            started + timedelta(seconds=30)
        ),
        details={
            "scope_count": 1,
        },
    )

    return record_run(
        execution,
        run_id=run_id,
        summary=(
            {"messages": 1000}
            if summary is None
            else summary
        ),
        metadata=(
            {"source": "test"}
            if metadata is None
            else metadata
        ),
    )


def provenance_for(run):
    dataset_entity = EntityRef(
        kind="dataset",
        namespace="project",
        name="livox-session",
    )

    dataset = DatasetRecord(
        entity=dataset_entity,
        revision=RevisionRef.from_sha256(
            dataset_entity,
            "b" * 64,
        ),
        kind="recording",
        uri="datasets/livox.ndrx",
    )

    artifact_entity = EntityRef(
        kind="artifact",
        namespace="project",
        name="global-map",
    )

    artifact = ArtifactRecord(
        entity=artifact_entity,
        revision=RevisionRef.from_sha256(
            artifact_entity,
            "c" * 64,
        ),
        kind="mapping.point-cloud",
        uri="artifacts/global-map.ply",
    )

    return combine_provenance(
        run_lifecycle_relations(run),
        run_io_relations(
            run,
            inputs=(dataset,),
            outputs=(artifact,),
        ),
    )


def test_run_document_has_versioned_identity() -> None:
    document = run_to_document(
        finished_run()
    )

    assert document["schema"] == RUN_DOCUMENT_SCHEMA
    assert document["schema"] == "nodrix.run/v1"
    assert document["kind"] == RUN_DOCUMENT_KIND
    assert document["kind"] == "Run"

    assert document["id"] == "run-001"
    assert document["ref"] == (
        "nodrix://record/run/run-001"
    )


def test_run_document_preserves_execution_chain() -> None:
    document = run_to_document(
        finished_run()
    )

    assert document["subject"]["entity"] == (
        "nodrix://system/project/mapping"
    )

    assert document["operation"]["kind"] == "run"

    assert document["plan"]["id"] == "plan-001"
    assert document["plan"]["ref"] == (
        "nodrix://record/plan/plan-001"
    )

    assert document["execution"]["id"] == (
        "execution-001"
    )

    assert document["execution"]["ref"] == (
        "nodrix://record/execution/execution-001"
    )


def test_run_document_has_legacy_friendly_top_level_status() -> None:
    document = run_to_document(
        finished_run()
    )

    assert document["status"] == "completed"
    assert document["successful"] is True
    assert document["duration_seconds"] == 30.0


def test_run_document_serializes_provenance() -> None:
    run = finished_run()

    document = run_to_document(
        run,
        provenance=provenance_for(run),
    )

    assert len(document["relations"]) == 4

    kinds = [
        item["kind"]
        for item in document["relations"]
    ]

    assert kinds == [
        "executed_as",
        "recorded_as",
        "consumes",
        "produces",
    ]


def test_run_document_serialization_is_deterministic() -> None:
    run = finished_run()
    provenance = provenance_for(run)

    first = dumps_run_document(
        run,
        provenance=provenance,
    )

    second = dumps_run_document(
        run,
        provenance=provenance,
    )

    assert first == second

    parsed = json.loads(first)

    assert parsed["schema"] == "nodrix.run/v1"


def test_run_document_uses_utc_timestamp_text() -> None:
    document = run_to_document(
        finished_run()
    )

    assert document["execution"]["started_at"] == (
        "2026-08-15T20:00:00Z"
    )

    assert document["execution"]["finished_at"] == (
        "2026-08-15T20:00:30Z"
    )


def test_write_run_document_uses_canonical_layout(
    tmp_path,
) -> None:
    run = finished_run()

    path = write_run_document(
        run,
        project=tmp_path,
        provenance=provenance_for(run),
    )

    assert path == (
        tmp_path
        / ".nodrix"
        / "runs"
        / "run-001"
        / "run.json"
    )

    assert path.is_file()

    loaded = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert loaded["schema"] == "nodrix.run/v1"
    assert loaded["id"] == "run-001"


def test_canonical_run_directory_is_safe(
    tmp_path,
) -> None:
    run = finished_run()

    assert canonical_run_directory(
        run,
        project=tmp_path,
    ) == (
        tmp_path
        / ".nodrix"
        / "runs"
        / "run-001"
    )


def test_storage_rejects_unsafe_run_id(
    tmp_path,
) -> None:
    run = finished_run(
        run_id="../outside",
    )

    with pytest.raises(ValueError):
        canonical_run_directory(
            run,
            project=tmp_path,
        )


def test_identical_write_is_idempotent(
    tmp_path,
) -> None:
    run = finished_run()
    provenance = provenance_for(run)

    first = write_run_document(
        run,
        project=tmp_path,
        provenance=provenance,
    )

    second = write_run_document(
        run,
        project=tmp_path,
        provenance=provenance,
    )

    assert first == second


def test_different_content_cannot_replace_existing_run(
    tmp_path,
) -> None:
    first = finished_run(
        summary={
            "messages": 1000,
        },
    )

    second = finished_run(
        summary={
            "messages": 2000,
        },
    )

    write_run_document(
        first,
        project=tmp_path,
    )

    with pytest.raises(
        FileExistsError,
        match="different content",
    ):
        write_run_document(
            second,
            project=tmp_path,
        )


def test_legacy_run_loader_can_read_canonical_run_json(
    tmp_path,
) -> None:
    run = finished_run()

    write_run_document(
        run,
        project=tmp_path,
        provenance=provenance_for(run),
    )

    loaded = load_run(
        "run-001",
        project=tmp_path,
    )

    assert loaded["schema"] == "nodrix.run/v1"
    assert loaded["id"] == "run-001"
    assert loaded["status"] == "completed"
    assert loaded["duration_seconds"] == 30.0


def test_non_json_metadata_is_rejected() -> None:
    run = finished_run(
        metadata={
            "bad": object(),
        },
    )

    with pytest.raises(
        TypeError,
        match="not supported",
    ):
        run_to_document(run)


def test_non_finite_float_is_rejected() -> None:
    run = finished_run(
        summary={
            "score": float("nan"),
        },
    )

    with pytest.raises(
        ValueError,
        match="NaN or infinite",
    ):
        run_to_document(run)
