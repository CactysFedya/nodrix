from types import MappingProxyType

import pytest

from nodrix.model import (
    ArtifactRecord,
    DatasetRecord,
    EntityRef,
    RevisionRef,
)


def dataset_entity() -> EntityRef:
    return EntityRef(
        kind="dataset",
        namespace="project",
        name="livox-recording",
    )


def artifact_entity() -> EntityRef:
    return EntityRef(
        kind="artifact",
        namespace="project",
        name="global-map",
    )


def test_dataset_record_preserves_identity_and_revision() -> None:
    entity = dataset_entity()
    revision = RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )

    record = DatasetRecord(
        entity=entity,
        revision=revision,
        kind="recording",
        uri="datasets/livox/session-001.ndrx",
        media_type="application/x-nodrix-recording",
        size_bytes=1024,
    )

    assert record.entity == entity
    assert record.revision == revision
    assert record.kind == "recording"
    assert record.uri == "datasets/livox/session-001.ndrx"
    assert record.media_type == "application/x-nodrix-recording"
    assert record.size_bytes == 1024


def test_artifact_record_preserves_identity_and_revision() -> None:
    entity = artifact_entity()
    revision = RevisionRef.from_sha256(
        entity,
        "b" * 64,
    )

    record = ArtifactRecord(
        entity=entity,
        revision=revision,
        kind="map",
        uri="artifacts/maps/global-map.ply",
        media_type="application/octet-stream",
        size_bytes=2048,
    )

    assert record.entity == entity
    assert record.revision == revision
    assert record.kind == "map"
    assert record.uri == "artifacts/maps/global-map.ply"
    assert record.size_bytes == 2048


def test_kinds_are_extensible_and_normalized() -> None:
    entity = artifact_entity()

    record = ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            "b" * 64,
        ),
        kind="  MAPPING.POINT-CLOUD  ",
        uri="artifact.ply",
    )

    assert record.kind == "mapping.point-cloud"


@pytest.mark.parametrize(
    "kind",
    [
        "",
        "bad kind",
        "1map",
        "map!",
        "map/type",
    ],
)
def test_record_rejects_invalid_kind(kind: str) -> None:
    entity = artifact_entity()

    with pytest.raises(ValueError):
        ArtifactRecord(
            entity=entity,
            revision=RevisionRef.from_sha256(
                entity,
                "b" * 64,
            ),
            kind=kind,
            uri="artifact.bin",
        )


def test_record_rejects_revision_of_another_entity() -> None:
    entity = artifact_entity()

    other = EntityRef(
        kind="artifact",
        namespace="project",
        name="other-map",
    )

    revision = RevisionRef.from_sha256(
        other,
        "c" * 64,
    )

    with pytest.raises(
        ValueError,
        match="must reference the record entity",
    ):
        ArtifactRecord(
            entity=entity,
            revision=revision,
            kind="map",
            uri="artifact.ply",
        )


def test_dataset_requires_non_empty_uri() -> None:
    entity = dataset_entity()

    with pytest.raises(ValueError):
        DatasetRecord(
            entity=entity,
            revision=RevisionRef.from_sha256(
                entity,
                "a" * 64,
            ),
            kind="recording",
            uri="   ",
        )


def test_artifact_requires_non_empty_uri() -> None:
    entity = artifact_entity()

    with pytest.raises(ValueError):
        ArtifactRecord(
            entity=entity,
            revision=RevisionRef.from_sha256(
                entity,
                "b" * 64,
            ),
            kind="map",
            uri="   ",
        )


@pytest.mark.parametrize(
    "size",
    [
        -1,
        -100,
    ],
)
def test_record_rejects_negative_size(size: int) -> None:
    entity = artifact_entity()

    with pytest.raises(ValueError):
        ArtifactRecord(
            entity=entity,
            revision=RevisionRef.from_sha256(
                entity,
                "b" * 64,
            ),
            kind="map",
            uri="artifact.ply",
            size_bytes=size,
        )


def test_record_accepts_zero_size() -> None:
    entity = artifact_entity()

    record = ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            "b" * 64,
        ),
        kind="report",
        uri="empty.txt",
        size_bytes=0,
    )

    assert record.size_bytes == 0


def test_metadata_is_copied_and_read_only() -> None:
    entity = dataset_entity()

    metadata = {
        "sensor": "livox-mid360",
    }

    record = DatasetRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            "a" * 64,
        ),
        kind="point-cloud",
        uri="datasets/cloud.ndrx",
        metadata=metadata,
    )

    metadata["sensor"] = "changed"

    assert isinstance(record.metadata, MappingProxyType)
    assert record.metadata["sensor"] == "livox-mid360"

    with pytest.raises(TypeError):
        record.metadata["sensor"] = "other"  # type: ignore[index]


def test_location_is_not_logical_identity() -> None:
    entity = artifact_entity()
    revision = RevisionRef.from_sha256(
        entity,
        "b" * 64,
    )

    first = ArtifactRecord(
        entity=entity,
        revision=revision,
        kind="map",
        uri="artifacts/maps/global-map.ply",
    )

    moved = ArtifactRecord(
        entity=entity,
        revision=revision,
        kind="map",
        uri="artifacts/archive/global-map.ply",
    )

    assert first.entity == moved.entity
    assert first.revision == moved.revision
    assert first.uri != moved.uri


def test_same_logical_artifact_can_have_multiple_revisions() -> None:
    entity = artifact_entity()

    first = ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            "a" * 64,
        ),
        kind="map",
        uri="artifacts/maps/map-v1.ply",
    )

    second = ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            "b" * 64,
        ),
        kind="map",
        uri="artifacts/maps/map-v2.ply",
    )

    assert first.entity == second.entity
    assert first.revision != second.revision


def test_custom_entity_kinds_are_allowed() -> None:
    entity = EntityRef(
        kind="model",
        namespace="vision",
        name="detector",
    )

    record = ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            "d" * 64,
        ),
        kind="model.ncnn",
        uri="artifacts/models/detector.ncnn",
    )

    assert record.entity.kind == "model"
    assert record.kind == "model.ncnn"
