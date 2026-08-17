"""Concrete system-level instances of SDK definitions and external components."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import Field, field_validator

from ..model import EntityRef, RevisionRef
from ._base import Metadata, NamedSystemModel


class NodeInstance(NamedSystemModel):
    """One concrete use of a NodeDefinition inside a Graph."""

    uses: str = Field(min_length=1)
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    resources: Mapping[str, str] = Field(default_factory=dict)
    target: str | None = None
    backend: str | None = None
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class ResourceInstance(NamedSystemModel):
    """One concrete shared resource owned by the System."""

    uses: str = Field(min_length=1)
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    bindings: Mapping[str, str] = Field(default_factory=dict)
    target: str | None = None
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class ApplicationInstance(NamedSystemModel):
    """One supervised external application outside a Graph data plane."""

    uses: str = Field(min_length=1)
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    resources: Mapping[str, str] = Field(default_factory=dict)
    target: str | None = None
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class SystemInstance(NamedSystemModel):
    """One exact child System Definition instantiated by a parent System.

    ``uses`` is the canonical immutable RevisionRef of the child System
    Definition. Filesystem paths, project aliases, source filenames, and
    unpinned EntityRefs are authoring concerns and must be resolved before
    constructing the canonical SystemModel.

    A SystemInstance is part of the canonical architecture. It is not a
    System Module and does not disappear during source resolution.
    """

    uses: str = Field(min_length=1)
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("uses")
    @classmethod
    def validate_uses(cls, value: str) -> str:
        normalized = value.strip()

        try:
            revision = RevisionRef.parse(
                normalized
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "SystemInstance.uses must be a canonical "
                "immutable System RevisionRef"
            ) from exc

        if revision.entity.kind != "system":
            raise ValueError(
                "SystemInstance.uses must reference "
                "an entity of kind 'system'"
            )

        return revision.canonical

    @property
    def revision(self) -> RevisionRef:
        """Return the pinned child System revision."""

        return RevisionRef.parse(
            self.uses
        )

    @property
    def entity(self) -> EntityRef:
        """Return the logical child System identity."""

        return self.revision.entity


class Target(NamedSystemModel):
    """Declarative execution/deployment target.

    Version 2.5 models targets only. Target resolution and deployment belong to
    the 2.6 planner/backend layer.
    """

    kind: str = "local"
    properties: Mapping[str, Any] = Field(default_factory=dict)
    metadata: Metadata = Field(default_factory=dict)


class Artifact(NamedSystemModel):
    """A first-class output expected from a System."""

    kind: str = Field(min_length=1)
    producer: str | None = None
    path: str | None = None
    media_type: str | None = None
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)
