from types import MappingProxyType

import pytest

from nodrix.model import (
    CONSUMES,
    DERIVED_FROM,
    EXECUTED_AS,
    PRODUCES,
    RECORDED_AS,
    ArtifactRecord,
    DatasetRecord,
    EntityRef,
    RecordRef,
    Relation,
    RelationGraph,
    RelationKind,
    RevisionRef,
    parse_canonical_ref,
)


def test_record_ref_has_canonical_form() -> None:
    ref = RecordRef(
        kind="Run",
        record_id="run-001",
    )

    assert ref.kind == "run"
    assert ref.record_id == "run-001"
    assert str(ref) == "nodrix://record/run/run-001"


def test_record_ref_round_trip() -> None:
    original = RecordRef(
        kind="execution",
        record_id="execution-001",
    )

    parsed = RecordRef.parse(
        original.canonical
    )

    assert parsed == original


def test_custom_record_kinds_are_supported() -> None:
    ref = RecordRef(
        kind="deployment",
        record_id="deploy-42",
    )

    assert str(ref) == (
        "nodrix://record/deployment/deploy-42"
    )


@pytest.mark.parametrize(
    ("kind", "record_id"),
    [
        ("", "run-001"),
        ("bad kind", "run-001"),
        ("1run", "run-001"),
        ("run", ""),
        ("run", "bad/id"),
        ("run", "bad id"),
    ],
)
def test_record_ref_rejects_invalid_values(
    kind: str,
    record_id: str,
) -> None:
    with pytest.raises(ValueError):
        RecordRef(
            kind=kind,
            record_id=record_id,
        )


def test_parse_canonical_ref_supports_entity() -> None:
    original = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )

    assert (
        parse_canonical_ref(original.canonical)
        == original
    )


def test_parse_canonical_ref_supports_revision() -> None:
    entity = EntityRef(
        kind="artifact",
        namespace="project",
        name="map",
    )

    original = RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )

    assert (
        parse_canonical_ref(original.canonical)
        == original
    )


def test_parse_canonical_ref_supports_record() -> None:
    original = RecordRef(
        kind="run",
        record_id="run-001",
    )

    assert (
        parse_canonical_ref(original.canonical)
        == original
    )


def test_relation_kind_is_extensible() -> None:
    kind = RelationKind(
        "robotics.calibrated_by"
    )

    assert str(kind) == (
        "robotics.calibrated_by"
    )


def test_relation_connects_run_to_consumed_dataset_revision() -> None:
    dataset_entity = EntityRef(
        kind="dataset",
        namespace="project",
        name="livox-session",
    )

    dataset_revision = RevisionRef.from_sha256(
        dataset_entity,
        "a" * 64,
    )

    dataset = DatasetRecord(
        entity=dataset_entity,
        revision=dataset_revision,
        kind="recording",
        uri="datasets/session.ndrx",
    )

    run = RecordRef(
        kind="run",
        record_id="run-001",
    )

    relation = Relation(
        source=run,
        kind=CONSUMES,
        target=dataset.revision,
    )

    assert relation.source == run
    assert relation.kind == CONSUMES
    assert relation.target == dataset.revision


def test_relation_connects_run_to_produced_artifact_revision() -> None:
    artifact_entity = EntityRef(
        kind="artifact",
        namespace="project",
        name="global-map",
    )

    artifact = ArtifactRecord(
        entity=artifact_entity,
        revision=RevisionRef.from_sha256(
            artifact_entity,
            "b" * 64,
        ),
        kind="map",
        uri="artifacts/map.ply",
    )

    relation = Relation(
        source=RecordRef(
            kind="run",
            record_id="run-001",
        ),
        kind=PRODUCES,
        target=artifact.revision,
    )

    assert relation.kind_name == "produces"
    assert relation.target == artifact.revision


def test_relation_can_capture_data_lineage() -> None:
    entity = EntityRef(
        kind="artifact",
        namespace="project",
        name="global-map",
    )

    first = RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )
    second = RevisionRef.from_sha256(
        entity,
        "b" * 64,
    )

    relation = Relation(
        source=second,
        kind=DERIVED_FROM,
        target=first,
    )

    assert relation.source == second
    assert relation.target == first


def test_relation_can_capture_execution_lifecycle() -> None:
    plan = RecordRef(
        kind="plan",
        record_id="plan-001",
    )
    execution = RecordRef(
        kind="execution",
        record_id="execution-001",
    )
    run = RecordRef(
        kind="run",
        record_id="run-001",
    )

    executed = Relation(
        source=plan,
        kind=EXECUTED_AS,
        target=execution,
    )

    recorded = Relation(
        source=execution,
        kind=RECORDED_AS,
        target=run,
    )

    assert executed.target == execution
    assert recorded.target == run


def test_relation_metadata_is_copied_and_read_only() -> None:
    metadata = {
        "role": "input",
    }

    relation = Relation(
        source=RecordRef(
            kind="run",
            record_id="run-001",
        ),
        kind=CONSUMES,
        target=EntityRef(
            kind="dataset",
            namespace="project",
            name="input",
        ),
        metadata=metadata,
    )

    metadata["role"] = "changed"

    assert isinstance(
        relation.metadata,
        MappingProxyType,
    )
    assert relation.metadata["role"] == "input"

    with pytest.raises(TypeError):
        relation.metadata["role"] = "other"  # type: ignore[index]


def test_relation_graph_queries_outgoing_edges() -> None:
    run = RecordRef(
        kind="run",
        record_id="run-001",
    )

    first = EntityRef(
        kind="dataset",
        namespace="project",
        name="input-a",
    )
    second = EntityRef(
        kind="dataset",
        namespace="project",
        name="input-b",
    )
    artifact = EntityRef(
        kind="artifact",
        namespace="project",
        name="output",
    )

    graph = RelationGraph(
        relations=(
            Relation(
                source=run,
                kind=CONSUMES,
                target=first,
            ),
            Relation(
                source=run,
                kind=CONSUMES,
                target=second,
            ),
            Relation(
                source=run,
                kind=PRODUCES,
                target=artifact,
            ),
        )
    )

    assert len(
        graph.outgoing(run)
    ) == 3

    assert len(
        graph.outgoing(
            run,
            kind=CONSUMES,
        )
    ) == 2

    assert len(
        graph.outgoing(
            run,
            kind="produces",
        )
    ) == 1


def test_relation_graph_queries_incoming_edges() -> None:
    artifact = EntityRef(
        kind="artifact",
        namespace="project",
        name="map",
    )

    first_run = RecordRef(
        kind="run",
        record_id="run-001",
    )
    second_run = RecordRef(
        kind="run",
        record_id="run-002",
    )

    graph = RelationGraph(
        relations=(
            Relation(
                source=first_run,
                kind=PRODUCES,
                target=artifact,
            ),
            Relation(
                source=second_run,
                kind=PRODUCES,
                target=artifact,
            ),
        )
    )

    incoming = graph.incoming(
        artifact,
        kind=PRODUCES,
    )

    assert len(incoming) == 2


def test_provenance_distinguishes_artifact_revisions() -> None:
    artifact = EntityRef(
        kind="artifact",
        namespace="project",
        name="global-map",
    )

    v1 = RevisionRef.from_sha256(
        artifact,
        "a" * 64,
    )
    v2 = RevisionRef.from_sha256(
        artifact,
        "b" * 64,
    )

    run1 = RecordRef(
        kind="run",
        record_id="run-001",
    )
    run2 = RecordRef(
        kind="run",
        record_id="run-002",
    )

    graph = RelationGraph(
        relations=(
            Relation(
                source=run1,
                kind=PRODUCES,
                target=v1,
            ),
            Relation(
                source=run2,
                kind=PRODUCES,
                target=v2,
            ),
        )
    )

    assert (
        graph.incoming(
            v1,
            kind=PRODUCES,
        )[0].source
        == run1
    )

    assert (
        graph.incoming(
            v2,
            kind=PRODUCES,
        )[0].source
        == run2
    )
