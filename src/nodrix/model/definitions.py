"""Canonical envelope for immutable Nodrix definition revisions.

Nodrix domains keep their authoritative definition models:

- SystemModel remains the System definition model.
- Workflow remains the Workflow authoring model.
- NodeDefinition / ResourceDefinition remain component SDK definitions.
- Future packages may provide their own definition kinds.

DefinitionRecord does not replace those models.

It connects one domain definition revision to the shared canonical identity
layer:

    domain definition
        -> EntityRef
        -> RevisionRef
        -> DefinitionRecord

Revision calculation remains owned by the domain bridge because different
domains already have established canonical serialization rules.  This module
must not guess those rules or derive identity from filesystem locations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .identity import EntityRef, RevisionRef


def _schema(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(
            "definition schema must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            "definition schema must be non-empty"
        )

    return normalized


@dataclass(frozen=True, slots=True)
class DefinitionRecord:
    """One canonical immutable revision of a domain Definition.

    ``entity`` identifies the logical entity.

    ``revision`` identifies one immutable revision of that entity and must
    therefore reference exactly the same EntityRef.

    ``schema`` identifies the authoritative domain contract represented by
    ``definition``.

    ``definition`` remains domain-specific.  This record deliberately does
    not introduce a second generic System, Workflow, Component, Dataset, or
    custom-definition model.

    ``metadata`` carries non-semantic context.  It must never be required to
    reconstruct the canonical identity of the Definition.
    """

    entity: EntityRef
    revision: RevisionRef
    schema: str
    definition: Any
    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.entity,
            EntityRef,
        ):
            raise TypeError(
                "definition entity must be an EntityRef"
            )

        if not isinstance(
            self.revision,
            RevisionRef,
        ):
            raise TypeError(
                "definition revision must be a RevisionRef"
            )

        if (
            self.revision.entity
            != self.entity
        ):
            raise ValueError(
                "definition revision must reference "
                "the definition entity"
            )

        object.__setattr__(
            self,
            "schema",
            _schema(self.schema),
        )

        if not isinstance(
            self.metadata,
            Mapping,
        ):
            raise TypeError(
                "definition metadata must be a mapping"
            )

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(
                dict(self.metadata)
            ),
        )

    @property
    def kind(self) -> str:
        """Return the canonical entity kind represented by this Definition."""

        return self.entity.kind

    @property
    def canonical(self) -> str:
        """Return the canonical immutable revision reference."""

        return self.revision.canonical


__all__ = [
    "DefinitionRecord",
]
