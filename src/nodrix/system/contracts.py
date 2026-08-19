"""Canonical external contracts exposed by a System Definition."""

from __future__ import annotations

from enum import StrEnum
import math
from typing import Any, Mapping
from dataclasses import dataclass

from pydantic import Field, field_validator, model_validator

from ._base import Metadata, NamedSystemModel, SystemBaseModel
from .graph import parse_system_endpoint


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

        parse_system_endpoint(
            normalized
        )

        return normalized


class SystemResourceBinding(SystemBaseModel):
    """Expose one internal ResourceInstance through a System requirement."""

    resource: str = Field(min_length=1)
    instance: str = Field(min_length=1)
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("resource", "instance")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("resource binding name must be non-empty")
        if "." in normalized or "/" in normalized:
            raise ValueError(
                "resource binding name cannot contain '.' or '/'"
            )
        return normalized


class SystemParameterTargetKind(StrEnum):
    """Internal object kind receiving one public System parameter."""

    APPLICATION = "application"
    RESOURCE = "resource"
    NODE = "node"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class SystemParameterTarget:
    kind: SystemParameterTargetKind
    instance: str
    parameter: str
    scope: str | None = None


def parse_system_parameter_target(
    value: str,
) -> SystemParameterTarget:
    """Parse an explicit internal parameter target.

    Canonical forms are ``application:name.parameter``,
    ``resource:name.parameter``, ``system:name.parameter``, and
    ``node:graph/name.parameter``.
    """

    normalized = value.strip()
    prefix, separator, local = normalized.partition(":")
    if not separator:
        raise ValueError(
            "parameter target must start with application:, resource:, system:, "
            "or node:"
        )

    if prefix == SystemParameterTargetKind.NODE.value:
        graph, slash, node_parameter = local.partition("/")
        if not slash or not graph:
            raise ValueError(
                "node parameter target must use node:graph/name.parameter"
            )
        instance, parameter = node_parameter.partition(".")[::2]
        if not instance or not parameter:
            raise ValueError(
                "node parameter target must use node:graph/name.parameter"
            )
        return SystemParameterTarget(
            kind=SystemParameterTargetKind.NODE,
            scope=graph,
            instance=instance,
            parameter=parameter,
        )

    if prefix not in {
        SystemParameterTargetKind.APPLICATION.value,
        SystemParameterTargetKind.RESOURCE.value,
        SystemParameterTargetKind.SYSTEM.value,
    }:
        raise ValueError(
            "parameter target must start with application:, resource:, system:, "
            "or node:"
        )

    instance, dot, parameter = local.partition(".")
    if not dot or not instance or not parameter:
        raise ValueError(
            "parameter target must use kind:name.parameter syntax"
        )
    return SystemParameterTarget(
        kind=SystemParameterTargetKind(prefix),
        instance=instance,
        parameter=parameter,
    )


class SystemParameterBinding(SystemBaseModel):
    """Bind one public System parameter to explicit internal targets."""

    parameter: str = Field(min_length=1)
    targets: tuple[str, ...] = Field(min_length=1)
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("parameter")
    @classmethod
    def validate_parameter(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("parameter binding name must be non-empty")
        return normalized

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        for value in normalized:
            parse_system_parameter_target(value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("parameter binding targets must be unique")
        return normalized


class SystemBoundaryBindings(SystemBaseModel):
    """External-to-internal realization of a System contract."""

    inputs: tuple[SystemPortBinding, ...] = ()
    outputs: tuple[SystemPortBinding, ...] = ()
    parameters: tuple[SystemParameterBinding, ...] = ()
    resources: tuple[SystemResourceBinding, ...] = ()

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

    def resource(
        self,
        name: str,
    ) -> SystemResourceBinding:
        for item in self.resources:
            if item.resource == name:
                return item
        raise KeyError(name)

    def parameter(
        self,
        name: str,
    ) -> SystemParameterBinding:
        for item in self.parameters:
            if item.parameter == name:
                return item
        raise KeyError(name)


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


class SystemParameterType(StrEnum):
    """Portable scalar/container types accepted by a System parameter."""

    ANY = "any"
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


class SystemParameter(NamedSystemModel):
    """One configurable value accepted by a System Definition."""

    value_type: SystemParameterType = Field(
        default=SystemParameterType.ANY,
        alias="type",
    )
    required: bool = False
    nullable: bool = False
    default: Any = None
    description: str | None = None
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @property
    def has_default(self) -> bool:
        """Return whether the Definition explicitly declares a default."""

        return "default" in self.model_fields_set

    def accepts(self, value: Any) -> bool:
        if value is None:
            return self.nullable
        if self.value_type is SystemParameterType.ANY:
            return True
        if self.value_type is SystemParameterType.STRING:
            return isinstance(value, str)
        if self.value_type is SystemParameterType.INTEGER:
            return isinstance(value, int) and not isinstance(value, bool)
        if self.value_type is SystemParameterType.NUMBER:
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
        if self.value_type is SystemParameterType.BOOLEAN:
            return isinstance(value, bool)
        if self.value_type is SystemParameterType.OBJECT:
            return isinstance(value, Mapping)
        return isinstance(value, list)

    @model_validator(mode="after")
    def validate_default(self) -> "SystemParameter":
        if self.has_default and not self.accepts(self.default):
            raise ValueError(
                f"default does not match parameter type {self.value_type.value!r}"
            )
        return self


class SystemResourceRequirement(NamedSystemModel):
    """One externally bindable ResourceDefinition required by a System."""

    uses: str = Field(min_length=1)
    optional: bool = False
    description: str | None = None
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("uses")
    @classmethod
    def validate_uses(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("uses must be non-empty")
        return normalized


__all__ = [
    "SystemBoundaryBindings",
    "SystemParameter",
    "SystemParameterBinding",
    "SystemParameterTarget",
    "SystemParameterTargetKind",
    "SystemParameterType",
    "SystemPort",
    "SystemPortBinding",
    "SystemResourceBinding",
    "SystemResourceRequirement",
    "parse_system_parameter_target",
]
