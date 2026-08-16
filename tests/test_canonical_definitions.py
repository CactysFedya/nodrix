from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from nodrix.model import (
    DefinitionRecord,
    EntityRef,
    RevisionRef,
)


def _entity(
    *,
    kind: str = "workflow",
    name: str = "build",
) -> EntityRef:
    return EntityRef(
        kind=kind,
        namespace="project",
        name=name,
    )


def _revision(
    entity: EntityRef,
    digest: str = "a" * 64,
) -> RevisionRef:
    return RevisionRef.from_sha256(
        entity,
        digest,
    )


def test_definition_record_preserves_domain_definition() -> None:
    entity = _entity()

    definition = {
        "schema": "nodrix.workflow/v1",
        "name": "build",
        "steps": [
            {
                "id": "compile",
                "run": "cmake --build build",
            },
        ],
    }

    record = DefinitionRecord(
        entity=entity,
        revision=_revision(entity),
        schema="nodrix.workflow/v1",
        definition=definition,
    )

    assert record.entity is entity
    assert (
        record.revision.entity
        is entity
    )
    assert (
        record.definition
        is definition
    )
    assert (
        record.schema
        == "nodrix.workflow/v1"
    )
    assert record.kind == "workflow"
    assert (
        record.canonical
        == record.revision.canonical
    )


def test_definition_record_requires_matching_revision() -> None:
    workflow = _entity()

    other = _entity(
        kind="system",
        name="mapping",
    )

    with pytest.raises(
        ValueError,
        match=(
            "definition revision must reference "
            "the definition entity"
        ),
    ):
        DefinitionRecord(
            entity=workflow,
            revision=_revision(other),
            schema="nodrix.workflow/v1",
            definition={},
        )


@pytest.mark.parametrize(
    "schema",
    [
        "",
        "   ",
    ],
)
def test_definition_record_requires_non_empty_schema(
    schema: str,
) -> None:
    entity = _entity()

    with pytest.raises(
        ValueError,
        match=(
            "definition schema must be non-empty"
        ),
    ):
        DefinitionRecord(
            entity=entity,
            revision=_revision(entity),
            schema=schema,
            definition={},
        )


def test_definition_record_normalizes_schema_whitespace() -> None:
    entity = _entity()

    record = DefinitionRecord(
        entity=entity,
        revision=_revision(entity),
        schema="  vendor.robot/v3  ",
        definition=object(),
    )

    assert (
        record.schema
        == "vendor.robot/v3"
    )


def test_definition_record_metadata_is_copied_and_read_only() -> None:
    entity = _entity()

    metadata = {
        "source": "python-sdk",
    }

    record = DefinitionRecord(
        entity=entity,
        revision=_revision(entity),
        schema="nodrix.workflow/v1",
        definition={},
        metadata=metadata,
    )

    metadata["source"] = "changed"

    assert isinstance(
        record.metadata,
        MappingProxyType,
    )

    assert (
        record.metadata["source"]
        == "python-sdk"
    )

    with pytest.raises(TypeError):
        record.metadata["source"] = "other"  # type: ignore[index]


def test_definition_record_supports_custom_entity_kinds() -> None:
    entity = EntityRef(
        kind="robot.firmware",
        namespace="acme/robot-a",
        name="navigation",
    )

    record = DefinitionRecord(
        entity=entity,
        revision=_revision(
            entity,
            "b" * 64,
        ),
        schema="robot.firmware/v1",
        definition={
            "target": "controller",
        },
    )

    assert (
        record.kind
        == "robot.firmware"
    )

    assert (
        record.entity.canonical
        == (
            "nodrix://robot.firmware/"
            "acme/robot-a/navigation"
        )
    )


def test_definition_record_itself_is_immutable() -> None:
    entity = _entity()

    record = DefinitionRecord(
        entity=entity,
        revision=_revision(entity),
        schema="nodrix.workflow/v1",
        definition={},
    )

    with pytest.raises(
        FrozenInstanceError
    ):
        record.schema = "other/v1"  # type: ignore[misc]


def test_definition_record_does_not_infer_revision_from_location() -> None:
    entity = _entity(
        kind="dataset",
        name="mapping-run",
    )

    revision = _revision(
        entity,
        "c" * 64,
    )

    record = DefinitionRecord(
        entity=entity,
        revision=revision,
        schema="vendor.dataset/v1",
        definition={
            "uri": "/tmp/mapping",
        },
    )

    # Location is domain data only.  Canonical identity is exactly the
    # explicitly supplied EntityRef + RevisionRef.
    assert (
        record.revision
        == revision
    )

    assert (
        record.canonical
        == revision.canonical
    )
