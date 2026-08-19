"""System-domain provenance snapshots for persistent Nodrix Runs.

This module does not introduce new System or Plan models.

It serializes the already-authoritative objects:

    SystemModel
        -> DefinitionRecord
        -> definition snapshot

    PlanRecord<SystemExecutionPlan>
        -> exact PlanRecord envelope + exact payload
        -> plan snapshot
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from nodrix.model import (
    SYSTEM_EXECUTION,
    PlanRecord,
)

from .canonical import (
    system_plan_digest,
)
from .definition import (
    system_definition_record,
)
from .model import (
    SystemModel,
)
from .planning import (
    SystemExecutionPlan,
)


SYSTEM_DEFINITION_SNAPSHOT_SCHEMA = (
    "nodrix.system-definition-snapshot/v1"
)

SYSTEM_PLAN_SNAPSHOT_SCHEMA = (
    "nodrix.system-plan-snapshot/v1"
)


def _json_mapping(
    value: Mapping[str, Any],
    *,
    field_name: str,
) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            f"{field_name} must contain only "
            "finite JSON-compatible values"
        ) from exc

    result = json.loads(
        encoded
    )

    if not isinstance(
        result,
        dict,
    ):
        raise TypeError(
            f"{field_name} must serialize "
            "to a JSON object"
        )

    return result


def system_definition_snapshot(
    system: SystemModel,
    plan: PlanRecord,
) -> dict[str, Any]:
    """Return the exact canonical Definition consumed by one System Plan."""

    if not isinstance(
        system,
        SystemModel,
    ):
        raise TypeError(
            "system must be a SystemModel"
        )

    if not isinstance(
        plan,
        PlanRecord,
    ):
        raise TypeError(
            "plan must be a PlanRecord"
        )

    if (
        plan.kind
        != SYSTEM_EXECUTION
    ):
        raise ValueError(
            "System Definition snapshot requires "
            "a system-execution PlanRecord"
        )

    definition = (
        system_definition_record(
            system,
            entity=plan.subject,
        )
    )

    if (
        definition.revision
        != plan.subject_revision
    ):
        raise ValueError(
            "System Definition revision does not "
            "match PlanRecord.subject_revision"
        )

    return {
        "schema": (
            SYSTEM_DEFINITION_SNAPSHOT_SCHEMA
        ),
        "recordType": (
            "DefinitionRecord"
        ),
        "entity": (
            definition.entity.canonical
        ),
        "revision": (
            definition.revision.canonical
        ),
        "definitionSchema": (
            definition.schema
        ),
        "definition": (
            _json_mapping(
                definition.definition,
                field_name="definition",
            )
        ),
        "metadata": (
            _json_mapping(
                definition.metadata,
                field_name="definition.metadata",
            )
        ),
    }


def system_plan_snapshot(
    plan: PlanRecord,
) -> dict[str, Any]:
    """Return the complete exact SystemExecutionPlan used by execution."""

    if not isinstance(
        plan,
        PlanRecord,
    ):
        raise TypeError(
            "plan must be a PlanRecord"
        )

    if (
        plan.kind
        != SYSTEM_EXECUTION
    ):
        raise ValueError(
            "System Plan snapshot requires "
            "a system-execution PlanRecord"
        )

    payload = plan.payload

    if not isinstance(
        payload,
        SystemExecutionPlan,
    ):
        raise TypeError(
            "system-execution PlanRecord payload "
            "must be a SystemExecutionPlan"
        )

    exact_payload = (
        payload.model_dump(
            mode="json",
            by_alias=True,
        )
    )

    exact_payload = (
        _json_mapping(
            exact_payload,
            field_name="plan.payload",
        )
    )

    actual_digest = (
        system_plan_digest(
            payload
        )
    )

    expected_digest = (
        plan.metadata.get(
            "plan_sha256"
        )
    )

    if (
        expected_digest is not None
        and expected_digest
        != actual_digest
    ):
        raise ValueError(
            "PlanRecord metadata plan_sha256 "
            "does not match its SystemExecutionPlan"
        )

    operation = (
        plan.operation
    )

    return {
        "schema": (
            SYSTEM_PLAN_SNAPSHOT_SCHEMA
        ),
        "recordType": (
            "PlanRecord"
        ),
        "planId": (
            plan.plan_id
        ),
        "planKind": (
            plan.kind_name
        ),
        "operation": {
            "kind": (
                operation.kind_name
            ),
            "subject": (
                operation
                .subject
                .canonical
            ),
            "subjectRevision": (
                operation
                .subject_revision
                .canonical
                if (
                    operation
                    .subject_revision
                    is not None
                )
                else None
            ),
            "parameters": (
                _json_mapping(
                    operation.parameters,
                    field_name=(
                        "operation.parameters"
                    ),
                )
            ),
        },
        "subjectRevision": (
            plan
            .subject_revision
            .canonical
        ),
        "metadata": (
            _json_mapping(
                plan.metadata,
                field_name="plan.metadata",
            )
        ),
        "payloadSha256": (
            actual_digest
        ),
        "payload": (
            exact_payload
        ),
    }


__all__ = [
    "SYSTEM_DEFINITION_SNAPSHOT_SCHEMA",
    "SYSTEM_PLAN_SNAPSHOT_SCHEMA",
    "system_definition_snapshot",
    "system_plan_snapshot",
]
