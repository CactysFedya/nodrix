from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodrix.materialized_storage import (
    MaterializationConflictError,
    MaterializedLocation,
    find_artifact_revision,
    find_dataset_revision,
    list_artifact_revisions,
    list_dataset_revisions,
    materialize_artifact,
    materialize_dataset,
)
from nodrix.model import EntityRef


def _dataset_entity() -> EntityRef:
    return EntityRef(
        kind="dataset",
        namespace="mapping",
        name="livox-session",
    )


def _artifact_entity() -> EntityRef:
    return EntityRef(
        kind="artifact",
        namespace="mapping",
        name="global-map",
    )


def test_materialization_writes_self_describing_descriptor(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "map.ply"
    )

    source.write_bytes(
        b"map"
    )

    record = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="map",
    )

    descriptor = (
        tmp_path
        / record.uri
    ).parent / "materialization.json"

    raw = json.loads(
        descriptor.read_text(
            encoding="utf-8",
        )
    )

    assert raw["schema"] == "nodrix.materialization/v1"
    assert raw["scope"] == "artifact"
    assert raw["entity"] == record.entity.canonical
    assert raw["revision"] == record.revision.canonical
    assert raw["uri"] == record.uri
    assert raw["payload_type"] == "file"
    assert raw["size_bytes"] == 3

    # Semantic record metadata intentionally does not become storage truth.
    assert "kind" not in raw
    assert "media_type" not in raw
    assert "metadata" not in raw


def test_find_dataset_revision(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "bag"
    )

    source.mkdir()

    (
        source
        / "metadata.yaml"
    ).write_text(
        "rosbag2",
        encoding="utf-8",
    )

    record = materialize_dataset(
        project=tmp_path,
        source=source,
        entity=_dataset_entity(),
        kind="rosbag2",
    )

    found = find_dataset_revision(
        tmp_path,
        record.revision,
    )

    assert isinstance(
        found,
        MaterializedLocation,
    )

    assert found.scope == "dataset"
    assert found.revision == record.revision
    assert found.uri == record.uri
    assert found.payload_type == "directory"
    assert found.size_bytes == record.size_bytes


def test_find_artifact_revision_with_custom_entity_kind(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "detector.ncnn"
    )

    source.write_bytes(
        b"model"
    )

    entity = EntityRef(
        kind="model",
        namespace="vision",
        name="detector",
    )

    record = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=entity,
        kind="model.ncnn",
    )

    found = find_artifact_revision(
        tmp_path,
        record.revision,
    )

    assert found is not None
    assert found.revision.entity == entity


def test_find_returns_none_for_unmaterialized_revision(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "map.ply"
    )

    source.write_bytes(
        b"map"
    )

    record = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="map",
    )

    empty_project = (
        tmp_path
        / "empty-project"
    )

    assert (
        find_artifact_revision(
            empty_project,
            record.revision,
        )
        is None
    )


def test_list_dataset_revisions_is_entity_scoped_and_sorted(
    tmp_path: Path,
) -> None:
    entity = _dataset_entity()

    revisions = []

    for name, content in (
        ("first.bin", b"one"),
        ("second.bin", b"two"),
        ("third.bin", b"three"),
    ):
        source = (
            tmp_path
            / name
        )

        source.write_bytes(
            content
        )

        revisions.append(
            materialize_dataset(
                project=tmp_path,
                source=source,
                entity=entity,
                kind="binary",
            ).revision
        )

    other_entity = EntityRef(
        kind="dataset",
        namespace="mapping",
        name="other-session",
    )

    other_source = (
        tmp_path
        / "other.bin"
    )

    other_source.write_bytes(
        b"other"
    )

    materialize_dataset(
        project=tmp_path,
        source=other_source,
        entity=other_entity,
        kind="binary",
    )

    found = list_dataset_revisions(
        tmp_path,
        entity,
    )

    assert {
        item.revision
        for item in found
    } == set(revisions)

    assert [
        (
            item.revision.algorithm,
            item.revision.digest,
        )
        for item in found
    ] == sorted(
        (
            revision.algorithm,
            revision.digest,
        )
        for revision in revisions
    )


def test_list_artifact_revisions(
    tmp_path: Path,
) -> None:
    entity = _artifact_entity()

    first_source = (
        tmp_path
        / "first.ply"
    )

    second_source = (
        tmp_path
        / "second.ply"
    )

    first_source.write_bytes(
        b"first"
    )

    second_source.write_bytes(
        b"second"
    )

    first = materialize_artifact(
        project=tmp_path,
        source=first_source,
        entity=entity,
        kind="map",
    )

    second = materialize_artifact(
        project=tmp_path,
        source=second_source,
        entity=entity,
        kind="map",
    )

    found = list_artifact_revisions(
        tmp_path,
        entity,
    )

    assert {
        item.revision
        for item in found
    } == {
        first.revision,
        second.revision,
    }


def test_missing_descriptor_is_backfilled_on_repeated_materialization(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "map.ply"
    )

    source.write_bytes(
        b"map"
    )

    first = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="map",
    )

    descriptor = (
        tmp_path
        / first.uri
    ).parent / "materialization.json"

    descriptor.unlink()

    assert not descriptor.exists()

    second = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="different.nonidentity-kind",
    )

    assert (
        second.revision
        == first.revision
    )

    assert descriptor.is_file()

    found = find_artifact_revision(
        tmp_path,
        second.revision,
    )

    assert found is not None
    assert found.revision == second.revision


def test_record_metadata_does_not_change_storage_descriptor(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "map.ply"
    )

    source.write_bytes(
        b"same-content"
    )

    first = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="map",
        media_type="application/octet-stream",
        metadata={
            "producer": "first",
        },
    )

    descriptor = (
        tmp_path
        / first.uri
    ).parent / "materialization.json"

    before = descriptor.read_bytes()

    second = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="mapping.point-cloud",
        media_type="application/x-ply",
        metadata={
            "producer": "second",
        },
    )

    after = descriptor.read_bytes()

    assert first.revision == second.revision
    assert first.uri == second.uri
    assert before == after

    assert first.kind != second.kind
    assert first.metadata != second.metadata


def test_tampered_descriptor_is_rejected(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "map.ply"
    )

    source.write_bytes(
        b"map"
    )

    record = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="map",
    )

    descriptor = (
        tmp_path
        / record.uri
    ).parent / "materialization.json"

    raw = json.loads(
        descriptor.read_text(
            encoding="utf-8",
        )
    )

    raw["scope"] = "dataset"

    descriptor.write_text(
        json.dumps(
            raw,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        MaterializationConflictError,
        match="requested revision",
    ):
        find_artifact_revision(
            tmp_path,
            record.revision,
        )


def test_listing_ignores_staging_directories(
    tmp_path: Path,
) -> None:
    entity = _artifact_entity()

    source = (
        tmp_path
        / "map.ply"
    )

    source.write_bytes(
        b"map"
    )

    record = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=entity,
        kind="map",
    )

    revision_directory = (
        tmp_path
        / record.uri
    ).parent

    staging = (
        revision_directory.parent
        / ".temporary.materialize-test"
    )

    staging.mkdir()

    found = list_artifact_revisions(
        tmp_path,
        entity,
    )

    assert [
        item.revision
        for item in found
    ] == [
        record.revision
    ]
