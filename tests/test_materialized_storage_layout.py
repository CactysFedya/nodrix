from __future__ import annotations

import hashlib
from pathlib import Path

from nodrix.materialized_storage import (
    artifact_revision_directory,
    dataset_revision_directory,
)
from nodrix.model import (
    EntityRef,
    RevisionRef,
)
from nodrix.storage_layout import StorageLayout


def _entity_key(
    entity: EntityRef,
) -> str:
    digest = hashlib.sha256(
        entity.canonical.encode(
            "utf-8"
        )
    ).hexdigest()

    return (
        f"{entity.name.lower()[:48]}"
        f"--{digest}"
    )


def test_dataset_revision_has_deterministic_canonical_directory(
    tmp_path: Path,
) -> None:
    entity = EntityRef(
        kind="dataset",
        namespace="project",
        name="livox-recording",
    )

    revision = RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )

    assert (
        dataset_revision_directory(
            tmp_path,
            revision,
        )
        == (
            tmp_path
            / "datasets"
            / "dataset"
            / _entity_key(entity)
            / "revisions"
            / f"sha256-{'a' * 64}"
        )
    )


def test_artifact_revision_has_deterministic_canonical_directory(
    tmp_path: Path,
) -> None:
    entity = EntityRef(
        kind="artifact",
        namespace="project",
        name="global-map",
    )

    revision = RevisionRef.from_sha256(
        entity,
        "b" * 64,
    )

    assert (
        artifact_revision_directory(
            tmp_path,
            revision,
        )
        == (
            tmp_path
            / "artifacts"
            / "artifact"
            / _entity_key(entity)
            / "revisions"
            / f"sha256-{'b' * 64}"
        )
    )


def test_dataset_and_artifact_roots_remain_distinct(
    tmp_path: Path,
) -> None:
    entity = EntityRef(
        kind="model",
        namespace="vision",
        name="detector",
    )

    revision = RevisionRef.from_sha256(
        entity,
        "c" * 64,
    )

    dataset_path = (
        dataset_revision_directory(
            tmp_path,
            revision,
        )
    )

    artifact_path = (
        artifact_revision_directory(
            tmp_path,
            revision,
        )
    )

    assert (
        dataset_path
        != artifact_path
    )

    assert (
        StorageLayout(
            tmp_path
        ).datasets_root
        in dataset_path.parents
    )

    assert (
        StorageLayout(
            tmp_path
        ).artifacts_root
        in artifact_path.parents
    )


def test_same_entity_revisions_share_entity_directory(
    tmp_path: Path,
) -> None:
    entity = EntityRef(
        kind="artifact",
        namespace="mapping",
        name="global-map",
    )

    first = RevisionRef.from_sha256(
        entity,
        "1" * 64,
    )

    second = RevisionRef.from_sha256(
        entity,
        "2" * 64,
    )

    first_path = (
        artifact_revision_directory(
            tmp_path,
            first,
        )
    )

    second_path = (
        artifact_revision_directory(
            tmp_path,
            second,
        )
    )

    assert first_path != second_path

    assert (
        first_path.parent
        == second_path.parent
    )


def test_entity_storage_resists_case_insensitive_collisions(
    tmp_path: Path,
) -> None:
    upper = EntityRef(
        kind="artifact",
        namespace="Mapping",
        name="GlobalMap",
    )

    lower = EntityRef(
        kind="artifact",
        namespace="mapping",
        name="globalmap",
    )

    upper_path = (
        artifact_revision_directory(
            tmp_path,
            RevisionRef.from_sha256(
                upper,
                "a" * 64,
            ),
        )
    )

    lower_path = (
        artifact_revision_directory(
            tmp_path,
            RevisionRef.from_sha256(
                lower,
                "a" * 64,
            ),
        )
    )

    upper_entity_dir = (
        upper_path.parent.parent
    )

    lower_entity_dir = (
        lower_path.parent.parent
    )

    assert (
        upper_entity_dir
        != lower_entity_dir
    )

    assert (
        upper_entity_dir.name.lower()
        != lower_entity_dir.name.lower()
    )


def test_namespace_is_part_of_storage_identity(
    tmp_path: Path,
) -> None:
    first = EntityRef(
        kind="artifact",
        namespace="robot/a",
        name="map",
    )

    second = EntityRef(
        kind="artifact",
        namespace="robot/b",
        name="map",
    )

    first_path = (
        artifact_revision_directory(
            tmp_path,
            RevisionRef.from_sha256(
                first,
                "a" * 64,
            ),
        )
    )

    second_path = (
        artifact_revision_directory(
            tmp_path,
            RevisionRef.from_sha256(
                second,
                "a" * 64,
            ),
        )
    )

    assert (
        first_path.parent.parent
        != second_path.parent.parent
    )


def test_custom_entity_kind_is_preserved(
    tmp_path: Path,
) -> None:
    entity = EntityRef(
        kind="model",
        namespace="vision",
        name="detector",
    )

    path = artifact_revision_directory(
        tmp_path,
        RevisionRef.from_sha256(
            entity,
            "d" * 64,
        ),
    )

    assert (
        path.parent.parent.parent.name
        == "model"
    )


def test_opaque_custom_digest_cannot_escape_storage_root(
    tmp_path: Path,
) -> None:
    entity = EntityRef(
        kind="artifact",
        namespace="project",
        name="custom",
    )

    revision = RevisionRef(
        entity=entity,
        algorithm="vendor",
        digest="../../outside\\payload",
    )

    path = artifact_revision_directory(
        tmp_path,
        revision,
    )

    root = StorageLayout(
        tmp_path
    ).artifacts_root

    assert root in path.parents
    assert ".." not in path.name
    assert "/" not in path.name
    assert "\\" not in path.name

    assert path.name.startswith(
        "vendor-key-"
    )


def test_path_resolution_does_not_create_materialized_storage(
    tmp_path: Path,
) -> None:
    project = (
        tmp_path
        / "project"
    )

    entity = EntityRef(
        kind="dataset",
        namespace="project",
        name="recording",
    )

    revision = RevisionRef.from_sha256(
        entity,
        "e" * 64,
    )

    path = dataset_revision_directory(
        project,
        revision,
    )

    assert not project.exists()
    assert not path.exists()
