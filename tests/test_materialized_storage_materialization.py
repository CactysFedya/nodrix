from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from nodrix.materialized_storage import (
    MaterializationConflictError,
    MaterializationError,
    materialize_artifact,
    materialize_dataset,
    verify_materialized_record,
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


def _make_symlink(
    link: Path,
    target: Path,
) -> None:
    try:
        link.symlink_to(
            target,
            target_is_directory=target.is_dir(),
        )
    except (
        OSError,
        NotImplementedError,
    ):
        pytest.skip(
            "symbolic links are unavailable on this platform"
        )


def test_materialize_dataset_file(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "session.ndrx"
    )

    content = b"livox-recording"

    source.write_bytes(
        content
    )

    record = materialize_dataset(
        project=tmp_path,
        source="session.ndrx",
        entity=_dataset_entity(),
        kind="recording",
        media_type="application/x-nodrix-recording",
        metadata={
            "sensor": "livox-mid360",
        },
    )

    expected_digest = hashlib.sha256(
        content
    ).hexdigest()

    assert (
        record.revision.digest
        == expected_digest
    )

    assert record.size_bytes == len(
        content
    )

    assert record.uri.endswith(
        "/payload"
    )

    payload = (
        tmp_path
        / record.uri
    )

    assert payload.read_bytes() == content
    assert source.read_bytes() == content

    assert (
        record.metadata["sensor"]
        == "livox-mid360"
    )

    assert verify_materialized_record(
        tmp_path,
        record,
    )


def test_materialize_artifact_file_with_custom_entity_kind(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "detector.ncnn"
    )

    source.write_bytes(
        b"ncnn-model"
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
        media_type="application/octet-stream",
    )

    assert record.entity == entity
    assert record.kind == "model.ncnn"
    assert (
        tmp_path
        / record.uri
    ).read_bytes() == b"ncnn-model"


def test_directory_materialization_is_deterministic_and_ignores_mtime(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    for root in (
        first,
        second,
    ):
        (root / "nested").mkdir(
            parents=True
        )
        (root / "empty").mkdir()
        (root / "a.txt").write_text(
            "alpha",
            encoding="utf-8",
        )
        (
            root
            / "nested"
            / "b.bin"
        ).write_bytes(
            b"beta"
        )

    os.utime(
        first / "a.txt",
        (1000, 1000),
    )

    os.utime(
        second / "a.txt",
        (2000, 2000),
    )

    first_record = materialize_dataset(
        project=tmp_path,
        source=first,
        entity=_dataset_entity(),
        kind="rosbag2",
    )

    second_record = materialize_dataset(
        project=tmp_path,
        source=second,
        entity=_dataset_entity(),
        kind="rosbag2",
    )

    assert (
        first_record.revision
        == second_record.revision
    )

    assert (
        first_record.uri
        == second_record.uri
    )

    assert (
        first_record.size_bytes
        == len(b"alpha") + len(b"beta")
    )

    payload = (
        tmp_path
        / first_record.uri
    )

    assert payload.is_dir()
    assert (
        payload
        / "empty"
    ).is_dir()

    assert verify_materialized_record(
        tmp_path,
        first_record,
    )


def test_empty_directory_is_part_of_tree_identity(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first.mkdir()
    second.mkdir()

    (first / "value.txt").write_text(
        "same",
        encoding="utf-8",
    )

    (second / "value.txt").write_text(
        "same",
        encoding="utf-8",
    )

    (
        second
        / "empty"
    ).mkdir()

    first_record = materialize_artifact(
        project=tmp_path,
        source=first,
        entity=_artifact_entity(),
        kind="bundle",
    )

    second_record = materialize_artifact(
        project=tmp_path,
        source=second,
        entity=_artifact_entity(),
        kind="bundle",
    )

    assert (
        first_record.revision
        != second_record.revision
    )


def test_repeated_materialization_is_idempotent(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "map.ply"
    )

    source.write_bytes(
        b"map-data"
    )

    first = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="mapping.point-cloud",
    )

    second = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="mapping.point-cloud",
    )

    assert first == second


def test_same_content_with_different_source_name_reuses_revision(
    tmp_path: Path,
) -> None:
    first_source = (
        tmp_path
        / "map.ply"
    )

    second_source = (
        tmp_path
        / "renamed.bin"
    )

    first_source.write_bytes(
        b"identical-content"
    )

    second_source.write_bytes(
        b"identical-content"
    )

    first = materialize_artifact(
        project=tmp_path,
        source=first_source,
        entity=_artifact_entity(),
        kind="map",
    )

    second = materialize_artifact(
        project=tmp_path,
        source=second_source,
        entity=_artifact_entity(),
        kind="map",
    )

    assert (
        first.revision
        == second.revision
    )

    assert first.uri == second.uri
    assert Path(first.uri).name == "payload"


def test_corrupted_existing_revision_is_rejected(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "map.ply"
    )

    source.write_bytes(
        b"expected"
    )

    record = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="map",
    )

    payload = (
        tmp_path
        / record.uri
    )

    payload.write_bytes(
        b"corrupted"
    )

    with pytest.raises(
        MaterializationConflictError,
        match="immutable content",
    ):
        materialize_artifact(
            project=tmp_path,
            source=source,
            entity=_artifact_entity(),
            kind="map",
        )


def test_verify_detects_materialized_payload_mutation(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "map.ply"
    )

    source.write_bytes(
        b"expected"
    )

    record = materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="map",
    )

    assert verify_materialized_record(
        tmp_path,
        record,
    )

    (
        tmp_path
        / record.uri
    ).write_bytes(
        b"changed"
    )

    assert not verify_materialized_record(
        tmp_path,
        record,
    )


def test_root_symbolic_link_source_is_rejected(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "target.bin"
    )

    target.write_bytes(
        b"value"
    )

    link = (
        tmp_path
        / "source.bin"
    )

    _make_symlink(
        link,
        target,
    )

    with pytest.raises(
        MaterializationError,
        match="symbolic link",
    ):
        materialize_dataset(
            project=tmp_path,
            source=link,
            entity=_dataset_entity(),
            kind="binary",
        )


def test_nested_symbolic_link_is_rejected(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "directory"
    )

    source.mkdir()

    target = (
        tmp_path
        / "outside.bin"
    )

    target.write_bytes(
        b"value"
    )

    link = (
        source
        / "link.bin"
    )

    _make_symlink(
        link,
        target,
    )

    with pytest.raises(
        MaterializationError,
        match="symbolic links",
    ):
        materialize_dataset(
            project=tmp_path,
            source=source,
            entity=_dataset_entity(),
            kind="bundle",
        )


def test_missing_source_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        FileNotFoundError,
    ):
        materialize_dataset(
            project=tmp_path,
            source="missing.bin",
            entity=_dataset_entity(),
            kind="binary",
        )


def test_directory_cannot_materialize_inside_itself(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "input.txt"
    ).write_text(
        "value",
        encoding="utf-8",
    )

    with pytest.raises(
        MaterializationError,
        match="contained by that same source",
    ):
        materialize_dataset(
            project=tmp_path,
            source=".",
            entity=_dataset_entity(),
            kind="project-tree",
        )

    assert not (
        tmp_path
        / "datasets"
    ).exists()
