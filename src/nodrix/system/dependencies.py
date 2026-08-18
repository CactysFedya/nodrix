"""Backend-neutral startup dependencies between sibling System instances."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from pydantic import Field, field_validator

from ._base import Metadata, SystemBaseModel


class SystemDependencyCondition(StrEnum):
    """Startup condition that a prerequisite System must satisfy."""

    STARTED = "started"
    READY = "ready"
    HEALTHY = "healthy"


class SystemDependency(SystemBaseModel):
    """One explicit startup edge between sibling System instances.

    ``system`` names the dependent sibling. ``requires`` names its prerequisite.
    The edge belongs to their parent System Definition and therefore cannot
    address ancestors, descendants, execution scopes, or backend objects.
    """

    system: str = Field(min_length=1)
    requires: str = Field(min_length=1)
    condition: SystemDependencyCondition
    timeout_seconds: float = Field(
        alias="timeoutSeconds",
        gt=0,
        allow_inf_nan=False,
    )
    metadata: Metadata = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("system", "requires")
    @classmethod
    def validate_instance_name(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("System dependency instance name must be non-empty")

        if "." in normalized or "/" in normalized:
            raise ValueError(
                "System dependency instance name cannot contain '.' or '/'"
            )

        return normalized


__all__ = [
    "SystemDependency",
    "SystemDependencyCondition",
]
