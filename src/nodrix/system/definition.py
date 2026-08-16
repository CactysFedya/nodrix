"""Canonical identity bridge for Nodrix System definitions.

SystemModel remains the authoritative domain definition model.

This module connects one immutable System definition revision to the shared
canonical object model without introducing a second System representation:

    SystemModel
        -> system_to_canonical()
        -> semantic SHA-256
        -> EntityRef / RevisionRef
        -> DefinitionRecord

The same semantic digest is consumed by System planning so Definition and Plan
refer to exactly the same System revision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from nodrix.model import (
    DefinitionRecord,
    EntityRef,
    RevisionRef,
)

from .io import system_to_canonical
from .model import (
    SYSTEM_MODEL_API_VERSION,
    SystemModel,
)


DEFAULT_SYSTEM_NAMESPACE = "project"


def system_entity_ref(
    name: str,
    *,
    namespace: str = DEFAULT_SYSTEM_NAMESPACE,
) -> EntityRef:
    """Return the canonical logical identity of one System."""

    return EntityRef(
        kind="system",
        namespace=namespace,
        name=name,
    )


def system_definition_digest(
    system: SystemModel,
) -> str:
    """Return the semantic SHA-256 of one canonical System Definition.

    This function is the authoritative System definition digest policy.

    It intentionally preserves the serialization previously used internally
    by the System planner so existing ``system_sha256`` values remain stable.
    """

    if not isinstance(
        system,
        SystemModel,
    ):
        raise TypeError(
            "system must be a SystemModel"
        )

    encoded = json.dumps(
        system_to_canonical(system),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def system_definition_record(
    system: SystemModel,
    *,
    entity: EntityRef | None = None,
    namespace: str = DEFAULT_SYSTEM_NAMESPACE,
    metadata: Mapping[str, Any] | None = None,
) -> DefinitionRecord:
    """Wrap one canonical System Definition revision in DefinitionRecord."""

    if not isinstance(
        system,
        SystemModel,
    ):
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

    if not isinstance(
        canonical_entity,
        EntityRef,
    ):
        raise TypeError(
            "entity must be an EntityRef or None"
        )

    if canonical_entity.kind != "system":
        raise ValueError(
            "canonical System definition entity "
            "must have kind 'system'"
        )

    revision = (
        RevisionRef.from_sha256(
            canonical_entity,
            system_definition_digest(
                system
            ),
        )
    )

    return DefinitionRecord(
        entity=canonical_entity,
        revision=revision,
        schema=SYSTEM_MODEL_API_VERSION,
        definition=system_to_canonical(
            system
        ),
        metadata=(
            {}
            if metadata is None
            else metadata
        ),
    )


__all__ = [
    "DEFAULT_SYSTEM_NAMESPACE",
    "system_definition_digest",
    "system_definition_record",
    "system_entity_ref",
]
