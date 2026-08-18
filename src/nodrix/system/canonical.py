"""Bridge between the Nodrix System domain and the canonical object model.

This module adapts existing SystemModel/SystemExecutionPlan objects into the
cross-domain canonical model without changing System Model v1 or the system
planner.

The bridge is intentionally one-way and read-only:
SystemModel -> SystemExecutionPlan -> canonical PlanRecord.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from nodrix.model import (
    RUN,
    SYSTEM_EXECUTION,
    EntityRef,
    Operation,
    PlanRecord,
    RevisionRef,
    canonical_plan_id,
)

from .catalog import DefinitionCatalog
from .definition import (
    DEFAULT_SYSTEM_NAMESPACE,
    system_entity_ref,
)
from .model import SystemModel
from .planning import SystemExecutionPlan, plan_system


def system_plan_digest(
    plan: SystemExecutionPlan,
) -> str:
    """Return a deterministic SHA-256 digest of one resolved system plan."""

    if not isinstance(plan, SystemExecutionPlan):
        raise TypeError(
            "plan must be a SystemExecutionPlan"
        )

    document = plan.model_dump(
        mode="json",
        by_alias=True,
    )

    # Preserve pre-2.18 Plan identity when no execution context is bound.
    if document.get(
        "execution_context_sha256"
    ) is None:
        document.pop(
            "execution_context_sha256",
            None,
        )

    # Preserve pre-2.20 Plan identity when no sibling startup topology exists.
    if document.get(
        "system_startup"
    ) is None:
        document.pop(
            "system_startup",
            None,
        )

    def remove_empty_interface_fields(
        plan_document: dict[str, Any],
    ) -> None:
        for field in (
            "inputs",
            "outputs",
            "parameters",
            "resource_requirements",
        ):
            if not plan_document.get(field):
                plan_document.pop(field, None)

        bindings = plan_document.get("bindings")
        if (
            isinstance(bindings, dict)
            and not bindings.get("inputs")
            and not bindings.get("outputs")
            and not bindings.get("parameters")
            and not bindings.get("resources")
        ):
            plan_document.pop("bindings", None)

        systems = plan_document.get("systems")
        if not isinstance(systems, list):
            return
        for instance in systems:
            if not isinstance(instance, dict):
                continue
            if not instance.get("parameters"):
                instance.pop("parameters", None)
            if not instance.get("resources"):
                instance.pop("resources", None)
            if not instance.get("resource_bindings"):
                instance.pop("resource_bindings", None)
            child_plan = instance.get("plan")
            if isinstance(child_plan, dict):
                remove_empty_interface_fields(
                    child_plan
                )

    # Preserve pre-2.21 Plan identity when interface contracts and instance
    # values are absent. Nested child plans follow the same rule recursively.
    remove_empty_interface_fields(document)

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def system_plan_record(
    plan: SystemExecutionPlan,
    *,
    operation: Operation | None = None,
    entity: EntityRef | None = None,
    namespace: str = DEFAULT_SYSTEM_NAMESPACE,
) -> PlanRecord:
    """Wrap one resolved SystemExecutionPlan in a canonical PlanRecord."""

    if not isinstance(plan, SystemExecutionPlan):
        raise TypeError(
            "plan must be a SystemExecutionPlan"
        )

    canonical_entity = (
        entity
        if entity is not None
        else system_entity_ref(
            plan.system,
            namespace=namespace,
        )
    )

    if not isinstance(canonical_entity, EntityRef):
        raise TypeError(
            "entity must be an EntityRef or None"
        )

    if canonical_entity.kind != "system":
        raise ValueError(
            "canonical System plan entity must have kind 'system'"
        )

    revision = RevisionRef.from_sha256(
        canonical_entity,
        plan.system_sha256,
    )

    canonical_operation = (
        operation
        if operation is not None
        else Operation(
            kind=RUN,
            subject=canonical_entity,
        )
    )

    if not isinstance(canonical_operation, Operation):
        raise TypeError(
            "operation must be an Operation or None"
        )

    if canonical_operation.subject != canonical_entity:
        raise ValueError(
            "operation subject must match the canonical System entity"
        )

    digest = system_plan_digest(plan)

    return PlanRecord(
        plan_id=canonical_plan_id(
            kind=SYSTEM_EXECUTION,
            operation=canonical_operation,
            subject_revision=revision,
            payload_sha256=digest,
        ),
        kind=SYSTEM_EXECUTION,
        operation=canonical_operation,
        subject_revision=revision,
        payload=plan,
        metadata={
            "schema": plan.schema_id,
            "system": plan.system,
            "system_sha256": plan.system_sha256,
            "plan_sha256": digest,
        },
    )


def plan_canonical_system(
    system: SystemModel,
    *,
    operation: Operation | None = None,
    entity: EntityRef | None = None,
    namespace: str = DEFAULT_SYSTEM_NAMESPACE,
    catalog: DefinitionCatalog | None = None,
) -> PlanRecord:
    """Plan a SystemModel and immediately expose the canonical PlanRecord."""

    if not isinstance(system, SystemModel):
        raise TypeError(
            "system must be a SystemModel"
        )

    canonical_entity = (
        entity
        if entity is not None
        else system_entity_ref(
            system.name,
            namespace=namespace,
        )
    )

    if canonical_entity.kind != "system":
        raise ValueError(
            "canonical System entity must have kind 'system'"
        )

    if (
        operation is not None
        and operation.subject != canonical_entity
    ):
        raise ValueError(
            "operation subject must match the canonical System entity"
        )

    resolved = plan_system(
        system,
        catalog=catalog,
    )

    return system_plan_record(
        resolved,
        operation=operation,
        entity=canonical_entity,
        namespace=namespace,
    )


__all__ = [
    "DEFAULT_SYSTEM_NAMESPACE",
    "plan_canonical_system",
    "system_entity_ref",
    "system_plan_digest",
    "system_plan_record",
]
