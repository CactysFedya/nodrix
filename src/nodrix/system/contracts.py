"""Canonical external contracts exposed by a System Definition."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import Field, field_validator

from ._base import Metadata, NamedSystemModel


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
    "SystemPort",
]
