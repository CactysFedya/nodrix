"""Backend-neutral component definitions produced by the public SDK frontend.

Definitions describe component contracts.  They intentionally do not inherit
from runtime Node/ManagedResource classes and can therefore be consumed later
by SystemModel planners or non-local execution backends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PortDefinition:
    name: str
    type_id: str
    optional: bool = False


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    name: str
    annotation: Any
    required: bool
    default: Any = None


@dataclass(frozen=True, slots=True)
class DependencyDefinition:
    name: str
    kind: str
    annotation: Any


@dataclass(frozen=True, slots=True)
class CallableDefinition:
    """Inferred contract of one Python callable used by a node definition."""

    name: str
    inputs: tuple[PortDefinition, ...]
    outputs: tuple[PortDefinition, ...]
    parameters: tuple[ParameterDefinition, ...]
    dependencies: tuple[DependencyDefinition, ...]
    implementation: Any


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    """Neutral definition of one user-visible node type."""

    name: str
    inputs: tuple[PortDefinition, ...]
    outputs: tuple[PortDefinition, ...]
    parameters: tuple[ParameterDefinition, ...]
    dependencies: tuple[DependencyDefinition, ...]
    implementation: Any
    constructor: CallableDefinition | None = None
    process: CallableDefinition | None = None
    lifecycle_dependencies: Mapping[str, tuple[DependencyDefinition, ...]] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class ResourceDefinition:
    """Neutral definition of one pipeline-scoped resource type."""

    name: str
    parameters: tuple[ParameterDefinition, ...]
    implementation: Any
    dependencies: tuple[DependencyDefinition, ...] = ()
    provided_type: Any | None = None


@dataclass(frozen=True, slots=True)
class MessageDefinition:
    """Neutral identity for one message contract.

    ``schema`` and representation/codec metadata are intentionally left open for
    later backend-neutral contract work.  The current SDK preserves the Python
    type while providing a stable type id and version now.
    """

    type_id: str
    version: int
    python_type: type[Any]
    compatible_versions: tuple[int, ...] = ()
    schema: Mapping[str, Any] | None = None

    @property
    def id(self) -> str:
        return self.type_id


# Compatibility names used by the 2.x package compiler and existing tests.
PortSpec = PortDefinition
ParameterSpec = ParameterDefinition
DependencySpec = DependencyDefinition
ComponentSpec = NodeDefinition


__all__ = [
    "CallableDefinition",
    "ComponentSpec",
    "DependencyDefinition",
    "DependencySpec",
    "MessageDefinition",
    "NodeDefinition",
    "ParameterDefinition",
    "ParameterSpec",
    "PortDefinition",
    "PortSpec",
    "ResourceDefinition",
]
