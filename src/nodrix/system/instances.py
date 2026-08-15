"""Concrete system-level instances of SDK definitions and external components."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import Field

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
