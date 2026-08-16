import pytest

from nodrix.model import (
    BENCHMARK,
    SYSTEM_EXECUTION,
    EntityRef,
    Operation,
    RevisionRef,
)
from nodrix.system import SystemModel, plan_system
from nodrix.system.canonical import (
    plan_canonical_system,
    system_entity_ref,
    system_plan_digest,
    system_plan_record,
)


def mapping_system(
    *,
    description: str | None = None,
) -> SystemModel:
    return SystemModel(
        name="mapping",
        description=description,
    )


def test_system_entity_ref_uses_system_kind() -> None:
    ref = system_entity_ref(
        "mapping",
    )

    assert ref == EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )


def test_system_entity_ref_supports_custom_namespace() -> None:
    ref = system_entity_ref(
        "mapping",
        namespace="robot/perception",
    )

    assert str(ref) == (
        "nodrix://system/robot/perception/mapping"
    )


def test_system_plan_digest_is_deterministic() -> None:
    system = mapping_system()

    first = plan_system(system)
    second = plan_system(system)

    assert (
        system_plan_digest(first)
        == system_plan_digest(second)
    )


def test_system_plan_record_wraps_existing_plan() -> None:
    system = mapping_system()
    resolved = plan_system(system)

    record = system_plan_record(
        resolved,
    )

    assert record.kind == SYSTEM_EXECUTION

    assert record.subject == EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )

    assert record.subject_revision == (
        RevisionRef.from_sha256(
            record.subject,
            resolved.system_sha256,
        )
    )

    assert record.payload is resolved
    assert record.operation.kind_name == "run"

    assert record.metadata["schema"] == (
        resolved.schema_id
    )

    assert record.metadata["system_sha256"] == (
        resolved.system_sha256
    )


def test_plan_id_is_derived_from_resolved_plan() -> None:
    system = mapping_system()

    resolved = plan_system(system)
    digest = system_plan_digest(resolved)

    record = system_plan_record(
        resolved,
    )

    assert record.plan_id.startswith(
        "plan-"
    )
    assert len(record.plan_id) == (
        len("plan-") + 64
    )
    assert (
        record.metadata["plan_sha256"]
        == digest
    )

    assert record.metadata["plan_sha256"] == digest


def test_identical_system_plans_have_same_plan_identity() -> None:
    system = mapping_system()

    first = system_plan_record(
        plan_system(system),
    )

    second = system_plan_record(
        plan_system(system),
    )

    assert first.plan_id == second.plan_id
    assert (
        first.subject_revision
        == second.subject_revision
    )


def test_changed_system_revision_changes_plan_identity() -> None:
    first = plan_canonical_system(
        mapping_system(
            description="first",
        )
    )

    second = plan_canonical_system(
        mapping_system(
            description="second",
        )
    )

    assert first.subject == second.subject

    assert (
        first.subject_revision
        != second.subject_revision
    )

    assert first.plan_id != second.plan_id


def test_bridge_accepts_explicit_canonical_entity() -> None:
    system = mapping_system()

    entity = EntityRef(
        kind="system",
        namespace="robots/rover-01",
        name="mapping",
    )

    record = plan_canonical_system(
        system,
        entity=entity,
    )

    assert record.subject == entity
    assert record.subject_revision.entity == entity


def test_bridge_rejects_non_system_entity() -> None:
    system = mapping_system()

    entity = EntityRef(
        kind="component",
        namespace="project",
        name="mapping",
    )

    with pytest.raises(
        ValueError,
        match="kind 'system'",
    ):
        plan_canonical_system(
            system,
            entity=entity,
        )


def test_bridge_accepts_non_run_operation() -> None:
    system = mapping_system()

    entity = system_entity_ref(
        system.name,
    )

    operation = Operation(
        kind=BENCHMARK,
        subject=entity,
        parameters={
            "repeat": 3,
        },
    )

    record = plan_canonical_system(
        system,
        operation=operation,
        entity=entity,
    )

    assert record.operation == operation
    assert record.operation.kind_name == "benchmark"
    assert record.payload.system == "mapping"


def test_bridge_rejects_operation_for_another_system() -> None:
    system = mapping_system()

    operation = Operation(
        kind="run",
        subject=EntityRef(
            kind="system",
            namespace="project",
            name="perception",
        ),
    )

    with pytest.raises(
        ValueError,
        match="operation subject must match",
    ):
        plan_canonical_system(
            system,
            operation=operation,
        )


def test_bridge_respects_operation_pinned_revision() -> None:
    system = mapping_system()
    resolved = plan_system(system)

    entity = system_entity_ref(
        system.name,
    )

    revision = RevisionRef.from_sha256(
        entity,
        resolved.system_sha256,
    )

    operation = Operation(
        kind="run",
        subject=entity,
        subject_revision=revision,
    )

    record = system_plan_record(
        resolved,
        operation=operation,
        entity=entity,
    )

    assert record.operation.subject_revision == revision
    assert record.subject_revision == revision


def test_bridge_rejects_wrong_pinned_revision() -> None:
    system = mapping_system()
    resolved = plan_system(system)

    entity = system_entity_ref(
        system.name,
    )

    operation = Operation(
        kind="run",
        subject=entity,
        subject_revision=RevisionRef.from_sha256(
            entity,
            "f" * 64,
        ),
    )

    with pytest.raises(
        ValueError,
        match="must match the revision pinned",
    ):
        system_plan_record(
            resolved,
            operation=operation,
            entity=entity,
        )


def test_invalid_system_name_can_use_explicit_entity() -> None:
    system = SystemModel(
        name="Mapping System",
    )

    entity = EntityRef(
        kind="system",
        namespace="project",
        name="mapping-system",
    )

    record = plan_canonical_system(
        system,
        entity=entity,
    )

    assert record.subject == entity
    assert record.payload.system == "Mapping System"
