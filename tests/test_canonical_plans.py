from types import MappingProxyType

import pytest

from nodrix.model import (
    RUN,
    SYSTEM_EXECUTION,
    WORKFLOW,
    EntityRef,
    Operation,
    PlanKind,
    PlanRecord,
    RevisionRef,
)


def mapping_system() -> EntityRef:
    return EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )


def revision(
    entity: EntityRef | None = None,
    digest: str = "a" * 64,
) -> RevisionRef:
    return RevisionRef.from_sha256(
        entity or mapping_system(),
        digest,
    )


def test_plan_kind_normalizes_value() -> None:
    kind = PlanKind("  SYSTEM-EXECUTION  ")

    assert kind.value == "system-execution"
    assert str(kind) == "system-execution"


def test_plan_kind_supports_extension_names() -> None:
    kind = PlanKind("mapping.optimized")

    assert str(kind) == "mapping.optimized"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "bad kind",
        "1plan",
        "plan!",
        "plan/system",
    ],
)
def test_plan_kind_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        PlanKind(value)


def test_builtin_plan_kinds_are_canonical() -> None:
    assert str(SYSTEM_EXECUTION) == "system-execution"
    assert str(WORKFLOW) == "workflow"


def test_plan_record_resolves_operation_subject_revision() -> None:
    system = mapping_system()
    operation = Operation(
        kind=RUN,
        subject=system,
    )
    system_revision = revision(system)

    payload = {
        "targets": ["pi5"],
        "backends": ["local"],
    }

    plan = PlanRecord(
        plan_id="plan-001",
        kind=SYSTEM_EXECUTION,
        operation=operation,
        subject_revision=system_revision,
        payload=payload,
    )

    assert plan.plan_id == "plan-001"
    assert plan.kind == SYSTEM_EXECUTION
    assert plan.kind_name == "system-execution"
    assert plan.operation == operation
    assert plan.subject == system
    assert plan.subject_revision == system_revision
    assert plan.payload is payload


def test_plan_record_accepts_string_kind() -> None:
    system = mapping_system()

    plan = PlanRecord(
        plan_id="workflow-plan-001",
        kind="WORKFLOW",
        operation=Operation(
            kind="build",
            subject=system,
        ),
        subject_revision=revision(system),
        payload={"steps": ["configure", "build"]},
    )

    assert plan.kind == WORKFLOW


def test_plan_record_requires_non_empty_id() -> None:
    system = mapping_system()

    with pytest.raises(ValueError):
        PlanRecord(
            plan_id="   ",
            kind="system-execution",
            operation=Operation(
                kind="run",
                subject=system,
            ),
            subject_revision=revision(system),
            payload={},
        )


def test_plan_record_rejects_revision_of_another_subject() -> None:
    system = mapping_system()

    other = EntityRef(
        kind="system",
        namespace="project",
        name="perception",
    )

    with pytest.raises(
        ValueError,
        match="must reference the operation subject",
    ):
        PlanRecord(
            plan_id="plan-001",
            kind="system-execution",
            operation=Operation(
                kind="run",
                subject=system,
            ),
            subject_revision=revision(other),
            payload={},
        )


def test_plan_record_respects_operation_pinned_revision() -> None:
    system = mapping_system()
    pinned = revision(system, "a" * 64)

    operation = Operation(
        kind="run",
        subject=system,
        subject_revision=pinned,
    )

    plan = PlanRecord(
        plan_id="plan-001",
        kind="system-execution",
        operation=operation,
        subject_revision=pinned,
        payload={},
    )

    assert plan.subject_revision == pinned


def test_plan_record_rejects_different_revision_than_operation_pin() -> None:
    system = mapping_system()

    operation = Operation(
        kind="run",
        subject=system,
        subject_revision=revision(system, "a" * 64),
    )

    with pytest.raises(
        ValueError,
        match="must match the revision pinned",
    ):
        PlanRecord(
            plan_id="plan-001",
            kind="system-execution",
            operation=operation,
            subject_revision=revision(system, "b" * 64),
            payload={},
        )


def test_plan_metadata_is_copied_and_read_only() -> None:
    system = mapping_system()
    metadata = {
        "planner": "nodrix.system",
    }

    plan = PlanRecord(
        plan_id="plan-001",
        kind="system-execution",
        operation=Operation(
            kind="run",
            subject=system,
        ),
        subject_revision=revision(system),
        payload={},
        metadata=metadata,
    )

    metadata["planner"] = "changed"

    assert isinstance(plan.metadata, MappingProxyType)
    assert plan.metadata["planner"] == "nodrix.system"

    with pytest.raises(TypeError):
        plan.metadata["planner"] = "other"  # type: ignore[index]


def test_same_operation_can_have_different_plans() -> None:
    system = mapping_system()
    operation = Operation(
        kind="run",
        subject=system,
    )
    system_revision = revision(system)

    local = PlanRecord(
        plan_id="plan-local",
        kind="system-execution",
        operation=operation,
        subject_revision=system_revision,
        payload={
            "target": "pi5",
            "backend": "local",
        },
    )

    distributed = PlanRecord(
        plan_id="plan-distributed",
        kind="system-execution",
        operation=operation,
        subject_revision=system_revision,
        payload={
            "targets": ["pi5", "server"],
            "backend": "distributed",
        },
    )

    assert local.operation == distributed.operation
    assert local.subject_revision == distributed.subject_revision
    assert local.plan_id != distributed.plan_id
    assert local.payload != distributed.payload


def test_canonical_plan_id_is_deterministic_for_parameter_order() -> None:
    from nodrix.model import canonical_plan_id

    system = mapping_system()
    resolved = revision(system)

    first = Operation(
        kind="run",
        subject=system,
        parameters={
            "b": 2,
            "a": {
                "enabled": True,
                "values": [1, 2],
            },
        },
    )

    second = Operation(
        kind="run",
        subject=system,
        parameters={
            "a": {
                "values": [1, 2],
                "enabled": True,
            },
            "b": 2,
        },
    )

    assert canonical_plan_id(
        kind=SYSTEM_EXECUTION,
        operation=first,
        subject_revision=resolved,
        payload_sha256="c" * 64,
    ) == canonical_plan_id(
        kind=SYSTEM_EXECUTION,
        operation=second,
        subject_revision=resolved,
        payload_sha256="c" * 64,
    )


def test_canonical_plan_id_changes_with_operation_intent() -> None:
    from nodrix.model import canonical_plan_id

    system = mapping_system()
    resolved = revision(system)

    run = Operation(
        kind="run",
        subject=system,
        parameters={
            "mode": "normal",
        },
    )

    diagnose = Operation(
        kind="diagnose",
        subject=system,
        parameters={
            "mode": "normal",
        },
    )

    changed_parameters = Operation(
        kind="run",
        subject=system,
        parameters={
            "mode": "debug",
        },
    )

    base = canonical_plan_id(
        kind=SYSTEM_EXECUTION,
        operation=run,
        subject_revision=resolved,
        payload_sha256="c" * 64,
    )

    assert canonical_plan_id(
        kind=SYSTEM_EXECUTION,
        operation=diagnose,
        subject_revision=resolved,
        payload_sha256="c" * 64,
    ) != base

    assert canonical_plan_id(
        kind=SYSTEM_EXECUTION,
        operation=changed_parameters,
        subject_revision=resolved,
        payload_sha256="c" * 64,
    ) != base


def test_canonical_plan_id_changes_with_resolved_plan_semantics() -> None:
    from nodrix.model import canonical_plan_id

    system = mapping_system()
    resolved = revision(system)

    operation = Operation(
        kind="run",
        subject=system,
    )

    first = canonical_plan_id(
        kind=SYSTEM_EXECUTION,
        operation=operation,
        subject_revision=resolved,
        payload_sha256="c" * 64,
    )

    second = canonical_plan_id(
        kind=SYSTEM_EXECUTION,
        operation=operation,
        subject_revision=resolved,
        payload_sha256="d" * 64,
    )

    assert first != second
    assert first.startswith("plan-")
    assert len(first) == len("plan-") + 64
