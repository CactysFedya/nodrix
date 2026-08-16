from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodrix.materialized_storage import (
    MaterializationPinnedError,
    delete_artifact_revision,
    find_artifact_revision,
    get_artifact_lifecycle,
    get_dataset_lifecycle,
    list_artifact_revisions,
    materialize_artifact,
    materialize_dataset,
    prune_ephemeral_artifact_revisions,
    set_artifact_lifecycle,
    set_dataset_lifecycle,
    verify_materialized_record,
)
from nodrix.model import EntityRef


def _artifact_entity() -> EntityRef:
    return EntityRef(
        kind="artifact",
        namespace="mapping",
        name="global-map",
    )


def _dataset_entity() -> EntityRef:
    return EntityRef(
        kind="dataset",
        namespace="mapping",
        name="livox-session",
    )


def _artifact(
    tmp_path: Path,
    name: str,
    content: bytes,
):
    source = (
        tmp_path
        / name
    )

    source.write_bytes(
        content
    )

    return materialize_artifact(
        project=tmp_path,
        source=source,
        entity=_artifact_entity(),
        kind="map",
    )


def test_missing_lifecycle_defaults_to_retained_and_unpinned(
    tmp_path: Path,
) -> None:
    record = _artifact(
        tmp_path,
        "map.ply",
        b"map",
    )

    lifecycle = get_artifact_lifecycle(
        tmp_path,
        record.revision,
    )

    assert lifecycle is not None
    assert lifecycle.retention == "retained"
    assert lifecycle.pinned is False

    lifecycle_path = (
        tmp_path
        / record.uri
    ).parent / "lifecycle.json"

    assert not lifecycle_path.exists()


def test_lifecycle_is_separate_from_materialization_descriptor(
    tmp_path: Path,
) -> None:
    record = _artifact(
        tmp_path,
        "map.ply",
        b"map",
    )

    revision_directory = (
        tmp_path
        / record.uri
    ).parent

    descriptor = (
        revision_directory
        / "materialization.json"
    )

    before = descriptor.read_bytes()

    lifecycle = set_artifact_lifecycle(
        tmp_path,
        record.revision,
        retention="ephemeral",
        pinned=True,
    )

    after = descriptor.read_bytes()

    assert lifecycle.retention == "ephemeral"
    assert lifecycle.pinned is True
    assert before == after

    raw = json.loads(
        (
            revision_directory
            / "lifecycle.json"
        ).read_text(
            encoding="utf-8",
        )
    )

    assert (
        raw["schema"]
        == "nodrix.materialized-lifecycle/v1"
    )

    assert (
        raw["revision"]
        == record.revision.canonical
    )

    assert raw["scope"] == "artifact"
    assert raw["retention"] == "ephemeral"
    assert raw["pinned"] is True

    assert verify_materialized_record(
        tmp_path,
        record,
    )


def test_pin_can_be_explicitly_removed(
    tmp_path: Path,
) -> None:
    record = _artifact(
        tmp_path,
        "map.ply",
        b"map",
    )

    set_artifact_lifecycle(
        tmp_path,
        record.revision,
        pinned=True,
    )

    pinned = get_artifact_lifecycle(
        tmp_path,
        record.revision,
    )

    assert pinned is not None
    assert pinned.pinned is True

    unpinned = set_artifact_lifecycle(
        tmp_path,
        record.revision,
        pinned=False,
    )

    assert unpinned.pinned is False


def test_invalid_retention_is_rejected(
    tmp_path: Path,
) -> None:
    record = _artifact(
        tmp_path,
        "map.ply",
        b"map",
    )

    with pytest.raises(
        ValueError,
        match="retention",
    ):
        set_artifact_lifecycle(
            tmp_path,
            record.revision,
            retention="forever",  # type: ignore[arg-type]
        )


def test_explicit_delete_removes_unpinned_revision(
    tmp_path: Path,
) -> None:
    record = _artifact(
        tmp_path,
        "map.ply",
        b"map",
    )

    assert delete_artifact_revision(
        tmp_path,
        record.revision,
    )

    assert (
        find_artifact_revision(
            tmp_path,
            record.revision,
        )
        is None
    )

    assert not delete_artifact_revision(
        tmp_path,
        record.revision,
    )


def test_explicit_delete_rejects_pinned_revision(
    tmp_path: Path,
) -> None:
    record = _artifact(
        tmp_path,
        "map.ply",
        b"map",
    )

    set_artifact_lifecycle(
        tmp_path,
        record.revision,
        pinned=True,
    )

    with pytest.raises(
        MaterializationPinnedError,
        match="unpin",
    ):
        delete_artifact_revision(
            tmp_path,
            record.revision,
        )

    assert (
        find_artifact_revision(
            tmp_path,
            record.revision,
        )
        is not None
    )


def test_prune_removes_only_unpinned_ephemeral_revisions(
    tmp_path: Path,
) -> None:
    ephemeral = _artifact(
        tmp_path,
        "ephemeral.ply",
        b"ephemeral",
    )

    retained = _artifact(
        tmp_path,
        "retained.ply",
        b"retained",
    )

    pinned = _artifact(
        tmp_path,
        "pinned.ply",
        b"pinned",
    )

    set_artifact_lifecycle(
        tmp_path,
        ephemeral.revision,
        retention="ephemeral",
    )

    set_artifact_lifecycle(
        tmp_path,
        pinned.revision,
        retention="ephemeral",
        pinned=True,
    )

    deleted = (
        prune_ephemeral_artifact_revisions(
            tmp_path,
            _artifact_entity(),
        )
    )

    assert deleted == (
        ephemeral.revision,
    )

    remaining = {
        item.revision
        for item in list_artifact_revisions(
            tmp_path,
            _artifact_entity(),
        )
    }

    assert remaining == {
        retained.revision,
        pinned.revision,
    }


def test_materialization_never_automatically_prunes_old_revisions(
    tmp_path: Path,
) -> None:
    first = _artifact(
        tmp_path,
        "first.ply",
        b"first",
    )

    set_artifact_lifecycle(
        tmp_path,
        first.revision,
        retention="ephemeral",
    )

    second = _artifact(
        tmp_path,
        "second.ply",
        b"second",
    )

    assert (
        find_artifact_revision(
            tmp_path,
            first.revision,
        )
        is not None
    )

    assert (
        find_artifact_revision(
            tmp_path,
            second.revision,
        )
        is not None
    )


def test_dataset_lifecycle_uses_same_policy_model(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "session.ndrx"
    )

    source.write_bytes(
        b"recording"
    )

    record = materialize_dataset(
        project=tmp_path,
        source=source,
        entity=_dataset_entity(),
        kind="recording",
    )

    updated = set_dataset_lifecycle(
        tmp_path,
        record.revision,
        retention="ephemeral",
        pinned=True,
    )

    assert updated.scope == "dataset"
    assert updated.retention == "ephemeral"
    assert updated.pinned is True

    loaded = get_dataset_lifecycle(
        tmp_path,
        record.revision,
    )

    assert loaded == updated


def test_lifecycle_changes_never_change_revision_identity(
    tmp_path: Path,
) -> None:
    record = _artifact(
        tmp_path,
        "map.ply",
        b"map",
    )

    revision = record.revision

    set_artifact_lifecycle(
        tmp_path,
        revision,
        retention="ephemeral",
    )

    set_artifact_lifecycle(
        tmp_path,
        revision,
        pinned=True,
    )

    set_artifact_lifecycle(
        tmp_path,
        revision,
        retention="retained",
        pinned=False,
    )

    found = find_artifact_revision(
        tmp_path,
        revision,
    )

    assert found is not None
    assert found.revision == revision
    assert verify_materialized_record(
        tmp_path,
        record,
    )
