"""Canonical external contracts exposed by a System Definition."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import Field, field_validator

from ._base import Metadata, NamedSystemModel, SystemBaseModel
from .graph import split_system_endpoint


class SystemPortBinding(SystemBaseModel):
    """Bind one external System port to one internal endpoint.

    The endpoint uses the existing canonical System endpoint vocabulary:

    - ``application.port``
    - ``graph/node.port``

    A binding contains no transport or backend realization. It only identifies
    where an external System contract is implemented internally.
    """

    port: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("port")
    @classmethod
    def validate_port(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "binding port must be non-empty"
            )

        return normalized

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        split_system_endpoint(
            normalized
        )

        return normalized


class SystemBoundaryBindings(SystemBaseModel):
    """External-to-internal realization of a System contract."""

    inputs: tuple[SystemPortBinding, ...] = ()
    outputs: tuple[SystemPortBinding, ...] = ()

    def input(
        self,
        port: str,
    ) -> SystemPortBinding:
        for item in self.inputs:
            if item.port == port:
                return item
        raise KeyError(port)

    def output(
        self,
        port: str,
    ) -> SystemPortBinding:
        for item in self.outputs:
            if item.port == port:
                return item
        raise KeyError(port)


class SystemPort(NamedSystemModel):
    """One externally visible typed port of a System Definition.

    SystemPort describes the logical contract exposed by a System. It does not
    describe transport realization, ROS topics, queues, processes, or backend
    routing. Those concerns belong to composition/planning/integration layers.

    ``type_id`` uses the same backend-neutral contract identity language as
    Nodrix MessageDefinition/PortDefinition without making the canonical
    System Model depend on the SDK authoring frontend.
    """

    type_id: str = Field(min_length=1)
    optional: bool = False
    description: str | None = None
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("type_id")
    @classmethod
    def validate_type_id(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "type_id must be non-empty"
            )

        return normalized


__all__ = [
    "SystemBoundaryBindings",
    "SystemPort",
    "SystemPortBinding",
]
