"""Resolved SDK definitions used to validate a SystemModel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..sdk.definitions import MessageDefinition, NodeDefinition, ResourceDefinition


@dataclass(frozen=True, slots=True)
class DefinitionCatalog:
    """Backend-neutral lookup table.

    Keys are fully-qualified ``uses`` identifiers chosen by the package/index
    layer. Definitions themselves remain the neutral SDK dataclasses from 2.4.
    """

    nodes: Mapping[str, NodeDefinition] = field(default_factory=dict)
    resources: Mapping[str, ResourceDefinition] = field(default_factory=dict)
    messages: Mapping[str, MessageDefinition] = field(default_factory=dict)

    @classmethod
    def from_definitions(
        cls,
        *,
        nodes: Mapping[str, NodeDefinition] | None = None,
        resources: Mapping[str, ResourceDefinition] | None = None,
        messages: tuple[MessageDefinition, ...] = (),
    ) -> "DefinitionCatalog":
        return cls(
            nodes=dict(nodes or {}),
            resources=dict(resources or {}),
            messages={definition.type_id: definition for definition in messages},
        )
