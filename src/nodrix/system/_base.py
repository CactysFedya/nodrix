"""Shared strict/frozen models for the canonical System Model."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SystemBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        frozen=True,
    )


class NamedSystemModel(SystemBaseModel):
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must be non-empty")
        if "." in value or "/" in value:
            raise ValueError("name cannot contain '.' or '/'")
        return value


Metadata = Mapping[str, Any]
