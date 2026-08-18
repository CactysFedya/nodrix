"""Canonical backend-neutral System Model."""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import Field

from ._base import Metadata, SystemBaseModel
from .contracts import (
    SystemBoundaryBindings,
    SystemPort,
)
from .dependencies import SystemDependency
from .graph import Graph, SystemLink
from .instances import (
    ApplicationInstance,
    Artifact,
    ResourceInstance,
    SystemInstance,
    Target,
)


SYSTEM_MODEL_API_VERSION = "nodrix.system/v1"


class SystemModel(SystemBaseModel):
    """Declarative architecture of one executable system.

    SystemModel deliberately contains no runtime queues, scheduler decisions,
    process handles, or backend-specific execution plan. Those are compiled in
    later layers.
    """

    api_version: Literal["nodrix.system/v1"] = Field(
        default=SYSTEM_MODEL_API_VERSION,
        alias="apiVersion",
    )
    kind: Literal["System"] = "System"
    name: str = Field(min_length=1)
    description: str | None = None

    inputs: tuple[SystemPort, ...] = ()
    outputs: tuple[SystemPort, ...] = ()
    bindings: SystemBoundaryBindings = Field(
        default_factory=SystemBoundaryBindings
    )
    systems: tuple[SystemInstance, ...] = ()
    dependencies: tuple[SystemDependency, ...] = ()
    resources: tuple[ResourceInstance, ...] = ()
    applications: tuple[ApplicationInstance, ...] = ()
    graphs: tuple[Graph, ...] = ()
    links: tuple[SystemLink, ...] = ()
    targets: tuple[Target, ...] = ()
    artifacts: tuple[Artifact, ...] = ()

    policies: Mapping[str, Any] = Field(default_factory=dict)
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    def input(self, name: str) -> SystemPort:
        for item in self.inputs:
            if item.name == name:
                return item
        raise KeyError(name)

    def output(self, name: str) -> SystemPort:
        for item in self.outputs:
            if item.name == name:
                return item
        raise KeyError(name)

    def system(self, name: str) -> SystemInstance:
        for item in self.systems:
            if item.name == name:
                return item
        raise KeyError(name)

    def graph(self, name: str) -> Graph:
        for item in self.graphs:
            if item.name == name:
                return item
        raise KeyError(name)

    def resource(self, name: str) -> ResourceInstance:
        for item in self.resources:
            if item.name == name:
                return item
        raise KeyError(name)

    def application(self, name: str) -> ApplicationInstance:
        for item in self.applications:
            if item.name == name:
                return item
        raise KeyError(name)
