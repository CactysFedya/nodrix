from nodrix.model import (
    EntityRef,
)
from nodrix.system import (
    SystemModel,
    plan_system,
)
from nodrix.system.canonical import (
    plan_canonical_system,
    system_entity_ref as canonical_system_entity_ref,
)
from nodrix.system.definition import (
    system_definition_digest,
    system_definition_record,
    system_entity_ref,
)


def _system(
    *,
    description: str | None = None,
) -> SystemModel:
    return SystemModel(
        name="mapping",
        description=description,
        policies={
            "restart": "on-failure",
        },
    )


def test_system_definition_digest_matches_planner_revision() -> None:
    system = _system()

    resolved = plan_system(
        system
    )

    assert (
        system_definition_digest(
            system
        )
        == resolved.system_sha256
    )


def test_system_definition_record_wraps_canonical_document() -> None:
    system = _system()

    record = system_definition_record(
        system
    )

    assert (
        record.entity.canonical
        == "nodrix://system/project/mapping"
    )

    assert (
        record.schema
        == "nodrix.system/v1"
    )

    assert (
        record.definition[
            "apiVersion"
        ]
        == "nodrix.system/v1"
    )

    assert (
        record.definition[
            "kind"
        ]
        == "System"
    )

    assert (
        record.definition[
            "name"
        ]
        == "mapping"
    )


def test_system_definition_revision_matches_plan_subject_revision() -> None:
    system = _system()

    definition = (
        system_definition_record(
            system
        )
    )

    plan = plan_canonical_system(
        system
    )

    assert (
        definition.entity
        == plan.subject
    )

    assert (
        definition.revision
        == plan.subject_revision
    )


def test_system_definition_digest_changes_with_semantic_content() -> None:
    first = _system(
        description="first",
    )

    second = _system(
        description="second",
    )

    assert (
        system_definition_digest(
            first
        )
        != system_definition_digest(
            second
        )
    )


def test_system_definition_record_supports_explicit_entity() -> None:
    system = SystemModel(
        name="Mapping System"
    )

    entity = EntityRef(
        kind="system",
        namespace="robots/rover-01",
        name="mapping-system",
    )

    record = system_definition_record(
        system,
        entity=entity,
    )

    assert (
        record.entity
        == entity
    )

    assert (
        record.revision.entity
        == entity
    )


def test_system_definition_record_rejects_non_system_entity() -> None:
    system = _system()

    entity = EntityRef(
        kind="component",
        namespace="project",
        name="mapping",
    )

    try:
        system_definition_record(
            system,
            entity=entity,
        )
    except ValueError as exc:
        assert (
            "kind 'system'"
            in str(exc)
        )
    else:
        raise AssertionError(
            "non-System entity was accepted"
        )


def test_system_definition_metadata_does_not_change_revision() -> None:
    system = _system()

    first = system_definition_record(
        system,
        metadata={
            "source_path": "/first/system.yaml",
        },
    )

    second = system_definition_record(
        system,
        metadata={
            "source_path": "/second/system.yaml",
        },
    )

    assert (
        first.revision
        == second.revision
    )


def test_canonical_bridge_reexports_authoritative_system_identity() -> None:
    direct = system_entity_ref(
        "mapping"
    )

    compatibility = (
        canonical_system_entity_ref(
            "mapping"
        )
    )

    assert direct == compatibility

    assert (
        direct.canonical
        == "nodrix://system/project/mapping"
    )
