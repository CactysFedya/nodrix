"""Graph-local connections and explicit system boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from pydantic import Field, model_validator

from ._base import Metadata, NamedSystemModel, SystemBaseModel
from .instances import NodeInstance


def split_local_endpoint(value: str) -> tuple[str, str]:
    """Parse ``node.port`` used inside one Graph."""

    node, separator, port = value.partition(".")
    if not separator or not node or not port:
        raise ValueError(f"endpoint must use node.port syntax: {value!r}")
    if "/" in node:
        raise ValueError(f"local Graph endpoint cannot contain '/': {value!r}")
    return node, port


class SystemEndpointKind(StrEnum):
    """Namespace of one endpoint visible at a System boundary."""

    APPLICATION = "application"
    GRAPH = "graph"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class SystemEndpoint:
    """Parsed, backend-neutral System endpoint reference."""

    kind: SystemEndpointKind
    instance: str
    port: str
    scope: str | None = None


def parse_system_endpoint(value: str) -> SystemEndpoint:
    """Parse an Application, Graph node, or child System endpoint.

    Canonical forms are:

    - ``application.port``
    - ``graph/node.port``
    - ``system:instance.port``
    """

    normalized = value.strip()
    if normalized.startswith("system:"):
        instance, port = split_local_endpoint(
            normalized.removeprefix("system:")
        )
        return SystemEndpoint(
            kind=SystemEndpointKind.SYSTEM,
            instance=instance,
            port=port,
        )

    scope, slash, local = normalized.partition("/")
    if slash:
        node, port = split_local_endpoint(local)
        if not scope:
            raise ValueError(
                f"system endpoint has an empty Graph name: {value!r}"
            )
        return SystemEndpoint(
            kind=SystemEndpointKind.GRAPH,
            scope=scope,
            instance=node,
            port=port,
        )

    instance, port = split_local_endpoint(normalized)
    return SystemEndpoint(
        kind=SystemEndpointKind.APPLICATION,
        instance=instance,
        port=port,
    )


def split_system_endpoint(value: str) -> tuple[str | None, str, str]:
    """Parse a System boundary endpoint.

    ``application.port`` refers to a system Application,
    ``graph/node.port`` to a Node inside a named Graph, and
    ``system:instance.port`` to a direct child System port.

    New code should prefer :func:`parse_system_endpoint`, which preserves the
    endpoint kind without overloading the scope string. This tuple helper
    remains for the 2.x public API.
    """

    endpoint = parse_system_endpoint(value)
    if endpoint.kind is SystemEndpointKind.APPLICATION:
        return None, endpoint.instance, endpoint.port
    if endpoint.kind is SystemEndpointKind.SYSTEM:
        return "system", endpoint.instance, endpoint.port
    return endpoint.scope, endpoint.instance, endpoint.port


class Connection(SystemBaseModel):
    """One backend-neutral logical connection inside a Graph."""

    source: str = Field(alias="from")
    target: str = Field(alias="to")
    type_id: str | None = None
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_endpoints(self) -> "Connection":
        split_local_endpoint(self.source)
        split_local_endpoint(self.target)
        return self


class Graph(NamedSystemModel):
    """A data-flow composition of NodeInstances."""

    nodes: tuple[NodeInstance, ...] = ()
    connections: tuple[Connection, ...] = ()
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    def node(self, name: str) -> NodeInstance:
        for item in self.nodes:
            if item.name == name:
                return item
        raise KeyError(name)


class SystemLink(SystemBaseModel):
    """Explicit boundary outside one local Graph.

    A link can connect an Application to a Graph node, or two Graphs. It is a
    model-level contract only; transport/backend realization is intentionally a
    later planner concern.
    """

    source: str = Field(alias="from")
    target: str = Field(alias="to")
    uses: str | None = None
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    type_id: str | None = None
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_endpoints(self) -> "SystemLink":
        parse_system_endpoint(self.source)
        parse_system_endpoint(self.target)
        return self


__all__ = [
    "Connection",
    "Graph",
    "SystemEndpoint",
    "SystemEndpointKind",
    "SystemLink",
    "parse_system_endpoint",
    "split_local_endpoint",
    "split_system_endpoint",
]
