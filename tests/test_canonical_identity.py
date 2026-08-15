from dataclasses import FrozenInstanceError

import pytest

from nodrix.model import EntityRef, RevisionRef


def test_entity_ref_has_stable_canonical_form() -> None:
    ref = EntityRef(
        kind="System",
        namespace="project",
        name="mapping",
    )

    assert ref.kind == "system"
    assert ref.namespace == "project"
    assert ref.name == "mapping"
    assert str(ref) == "nodrix://system/project/mapping"


def test_entity_ref_supports_hierarchical_namespace() -> None:
    ref = EntityRef(
        kind="component",
        namespace="packages/nodrix-mapping",
        name="voxel_map",
    )

    assert (
        ref.canonical
        == "nodrix://component/packages/nodrix-mapping/voxel_map"
    )


def test_entity_ref_round_trip() -> None:
    original = EntityRef(
        kind="component",
        namespace="nodrix.mapping",
        name="voxel-map",
    )

    parsed = EntityRef.parse(original.canonical)

    assert parsed == original


@pytest.mark.parametrize(
    ("kind", "namespace", "name"),
    [
        ("", "project", "mapping"),
        ("system", "", "mapping"),
        ("system", "project", ""),
        ("bad kind", "project", "mapping"),
        ("system", "bad namespace!", "mapping"),
        ("system", "project", "bad/name"),
    ],
)
def test_entity_ref_rejects_invalid_identity(
    kind: str,
    namespace: str,
    name: str,
) -> None:
    with pytest.raises(ValueError):
        EntityRef(
            kind=kind,
            namespace=namespace,
            name=name,
        )


def test_entity_ref_is_immutable() -> None:
    ref = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )

    with pytest.raises(FrozenInstanceError):
        ref.name = "other"  # type: ignore[misc]


def test_revision_ref_accepts_existing_system_sha256() -> None:
    entity = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )
    digest = "a" * 64

    revision = RevisionRef.from_sha256(entity, digest)

    assert revision.entity == entity
    assert revision.algorithm == "sha256"
    assert revision.digest == digest
    assert revision.canonical == (
        "nodrix://system/project/mapping@sha256:" + digest
    )


def test_revision_ref_round_trip() -> None:
    original = RevisionRef.from_sha256(
        EntityRef(
            kind="system",
            namespace="project",
            name="mapping",
        ),
        "0123456789abcdef" * 4,
    )

    parsed = RevisionRef.parse(original.canonical)

    assert parsed == original


@pytest.mark.parametrize(
    "digest",
    [
        "",
        "abc",
        "g" * 64,
        "a" * 63,
        "a" * 65,
    ],
)
def test_revision_ref_rejects_invalid_sha256(
    digest: str,
) -> None:
    entity = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )

    with pytest.raises(ValueError):
        RevisionRef.from_sha256(entity, digest)
