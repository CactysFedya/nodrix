"""Canonical identity bridge for Nodrix Workflow definitions.

A Workflow has its own Definition identity even when the Operation implemented
by that Workflow targets another entity such as a Project.

For example:

    Workflow Definition: nodrix://workflow/workspace/demo/build
    BUILD Operation subject: nodrix://project/workspace/demo

The Workflow tells Nodrix how an Operation may be implemented.  It does not
implicitly redefine the subject of that Operation.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

from .model import (
    DefinitionRecord,
    EntityRef,
    RevisionRef,
)
from .project_canonical import (
    project_entity_ref,
)
from .workflow_execution import (
    load_workflow,
)
from .workflow_schema import WORKFLOW_SCHEMA


def _workflow_document(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            "workflow definition must be a mapping"
        )

    document = dict(value)

    schema = document.get(
        "schema"
    )

    if schema != WORKFLOW_SCHEMA:
        raise ValueError(
            "workflow definition must use schema "
            f"{WORKFLOW_SCHEMA!r}"
        )

    name = document.get(
        "name"
    )

    if not isinstance(
        name,
        str,
    ) or not name.strip():
        raise ValueError(
            "workflow definition must declare "
            "a non-empty name"
        )

    # Round-trip through canonical JSON-compatible data.  This both validates
    # the semantic document and detaches the DefinitionRecord from mutations
    # to the caller's outer/nested containers.
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    normalized = json.loads(
        encoded
    )

    if not isinstance(
        normalized,
        dict,
    ):
        raise TypeError(
            "workflow definition must normalize "
            "to a mapping"
        )

    return normalized


def workflow_definition_digest(
    definition: Mapping[str, Any],
) -> str:
    """Return semantic SHA-256 of one Workflow Definition."""

    document = _workflow_document(
        definition
    )

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def workflow_entity_ref(
    name: str,
    *,
    project: EntityRef,
) -> EntityRef:
    """Return the logical identity of one Workflow inside a Project."""

    if not isinstance(
        project,
        EntityRef,
    ):
        raise TypeError(
            "project must be an EntityRef"
        )

    if project.kind != "project":
        raise ValueError(
            "Workflow project identity must "
            "have kind 'project'"
        )

    if not isinstance(
        name,
        str,
    ):
        raise TypeError(
            "workflow name must be a string"
        )

    normalized = name.strip()

    if not normalized:
        raise ValueError(
            "workflow name must be non-empty"
        )

    return EntityRef(
        kind="workflow",
        namespace=(
            f"{project.namespace}/"
            f"{project.name}"
        ),
        name=normalized,
    )


def workflow_definition_record(
    definition: Mapping[str, Any],
    *,
    project: EntityRef,
    metadata: Mapping[str, Any] | None = None,
) -> DefinitionRecord:
    """Wrap one exact Workflow Definition in the canonical model."""

    document = _workflow_document(
        definition
    )

    entity = workflow_entity_ref(
        str(document["name"]),
        project=project,
    )

    revision = (
        RevisionRef.from_sha256(
            entity,
            workflow_definition_digest(
                document
            ),
        )
    )

    return DefinitionRecord(
        entity=entity,
        revision=revision,
        schema=WORKFLOW_SCHEMA,
        definition=document,
        metadata=dict(
            metadata or {}
        ),
    )


def load_canonical_workflow_definition(
    name: str,
    *,
    root: str | Path | None = None,
) -> DefinitionRecord:
    """Load one project Workflow as a canonical DefinitionRecord."""

    (
        document,
        source_path,
        project_root,
    ) = load_workflow(
        name,
        root=root,
    )

    project = project_entity_ref(
        project_root
    )

    return workflow_definition_record(
        document,
        project=project,
        metadata={
            "source_path": str(
                source_path
            ),
            "project": (
                project.canonical
            ),
        },
    )


__all__ = [
    "load_canonical_workflow_definition",
    "workflow_definition_digest",
    "workflow_definition_record",
    "workflow_entity_ref",
]
