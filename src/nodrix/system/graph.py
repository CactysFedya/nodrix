"""Graph-local connections and explicit system boundaries."""

from __future__ import annotations

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


def split_system_endpoint(value: str) -> tuple[str | None, str, str]:
    """Parse a System boundary endpoint.

    ``application.port`` refers to a system Application.
    ``graph/node.port`` refers to a Node inside a named Graph.
    """

    scope, slash, local = value.partition("/")
    if slash:
        node, port = split_local_endpoint(local)
        if not scope:
            raise ValueError(f"system endpoint has an empty Graph name: {value!r}")
        return scope, node, port

    instance, port = split_local_endpoint(value)
    return None, instance, port


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
        split_system_endpoint(self.source)
        split_system_endpoint(self.target)
        return self
