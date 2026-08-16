from __future__ import annotations

import pytest

from nodrix.model import (
    DERIVED_FROM,
    SUPERSEDES,
    ArtifactRecord,
    DatasetRecord,
    EntityRef,
    Relation,
    RelationGraph,
    RevisionRef,
    materialized_lineage_relations,
    materialized_revision,
    superseded_by,
)


def _dataset_entity() -> EntityRef:
    return EntityRef(
        kind="dataset",
        namespace="project",
        name="cloud",
    )


def _artifact_entity() -> EntityRef:
    return EntityRef(
        kind="artifact",
        namespace="project",
        name="global-map",
    )


def _dataset(
    digest: str,
) -> DatasetRecord:
    entity = _dataset_entity()

    return DatasetRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            digest * 64,
        ),
        kind="point-cloud",
        uri=f"datasets/{digest}.ndrx",
    )


def _artifact(
    digest: str,
) -> ArtifactRecord:
    entity = _artifact_entity()

    return ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            digest * 64,
        ),
        kind="mapping.point-cloud",
        uri=f"artifacts/{digest}.ply",
    )


def test_materialized_revision_accepts_raw_revision() -> None:
    record = _dataset("a")

    assert (
        materialized_revision(
            record.revision
        )
        is record.revision
    )


def test_materialized_revision_extracts_dataset_revision() -> None:
    record = _dataset("a")

    assert (
        materialized_revision(
            record
        )
        == record.revision
    )


def test_materialized_revision_extracts_artifact_revision() -> None:
    record = _artifact("b")

    assert (
        materialized_revision(
            record
        )
        == record.revision
    )


def test_lineage_records_derived_from_revision() -> None:
    source = _dataset("a")
    derived = _artifact("b")

    graph = (
        materialized_lineage_relations(
            derived,
            derived_from=(
                source,
            ),
        )
    )

    assert len(
        graph.relations
    ) == 1

    relation = graph.relations[0]

    assert (
        relation.source
        == derived.revision
    )

    assert (
        relation.kind
        == DERIVED_FROM
    )

    assert (
        relation.target
        == source.revision
    )


def test_lineage_records_same_entity_supersession() -> None:
    older = _artifact("a")
    newer = _artifact("b")

    graph = (
        materialized_lineage_relations(
            newer,
            supersedes=(
                older,
            ),
        )
    )

    relation = graph.relations[0]

    assert (
        relation.source
        == newer.revision
    )

    assert (
        relation.kind
        == SUPERSEDES
    )

    assert (
        relation.target
        == older.revision
    )


def test_lineage_deduplicates_revisions_and_preserves_order() -> None:
    source = _dataset("a")
    older = _artifact("a")
    newer = _artifact("b")

    graph = (
        materialized_lineage_relations(
            newer,
            derived_from=(
                source,
                source.revision,
                source,
            ),
            supersedes=(
                older,
                older.revision,
                older,
            ),
        )
    )

    assert len(
        graph.relations
    ) == 2

    assert (
        graph.relations[0].kind
        == DERIVED_FROM
    )

    assert (
        graph.relations[1].kind
        == SUPERSEDES
    )


def test_revision_cannot_be_derived_from_itself() -> None:
    record = _dataset("a")

    with pytest.raises(
        ValueError,
        match="derived from itself",
    ):
        materialized_lineage_relations(
            record,
            derived_from=(
                record,
            ),
        )


def test_revision_cannot_supersede_itself() -> None:
    record = _artifact("a")

    with pytest.raises(
        ValueError,
        match="supersede itself",
    ):
        materialized_lineage_relations(
            record,
            supersedes=(
                record,
            ),
        )


def test_supersedes_requires_same_logical_entity() -> None:
    older = _dataset("a")
    newer = _artifact("b")

    with pytest.raises(
        ValueError,
        match="same logical entity",
    ):
        materialized_lineage_relations(
            newer,
            supersedes=(
                older,
            ),
        )


def test_superseded_by_is_inverse_query_not_second_edge() -> None:
    older = _artifact("a")
    newer = _artifact("b")

    graph = (
        materialized_lineage_relations(
            newer,
            supersedes=(
                older,
            ),
        )
    )

    assert (
        superseded_by(
            graph,
            older,
        )
        == (
            newer.revision,
        )
    )

    assert all(
        relation.kind
        == SUPERSEDES
        for relation
        in graph.relations
    )


def test_superseded_by_rejects_invalid_supersedes_source() -> None:
    older = _artifact("a")

    graph = RelationGraph(
        relations=(
            Relation(
                source=EntityRef(
                    kind="artifact",
                    namespace="project",
                    name="bad-logical-reference",
                ),
                kind=SUPERSEDES,
                target=older.revision,
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="must be a RevisionRef",
    ):
        superseded_by(
            graph,
            older,
        )
