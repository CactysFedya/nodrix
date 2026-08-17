"""Resolved execution context for canonical System planning.

Project Context, Environment, and Profile are authoring/project concepts.
This module contains only the effective execution semantics that may affect
how one resolved System is executed.

Selection names and project provenance deliberately stay outside this model.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

from pydantic import Field

from .model import SystemBaseModel


class SystemExecutionContext(SystemBaseModel):
    """Effective execution semantics independent of project authoring names."""

    variables: Mapping[str, str] = Field(
        default_factory=dict
    )
    sources: tuple[str, ...] = ()

    runtime: Mapping[str, Any] = Field(
        default_factory=dict
    )
    node_defaults: Mapping[str, Any] = Field(
        default_factory=dict
    )
    edge_defaults: Mapping[str, Any] = Field(
        default_factory=dict
    )
    stream_defaults: Mapping[str, Any] = Field(
        default_factory=dict
    )


def system_execution_context_document(
    context: SystemExecutionContext,
) -> dict[str, Any]:
    """Return deterministic JSON-compatible execution semantics."""

    if not isinstance(
        context,
        SystemExecutionContext,
    ):
        raise TypeError(
            "context must be a SystemExecutionContext"
        )

    return deepcopy(
        context.model_dump(
            mode="json",
            by_alias=True,
        )
    )


def system_execution_context_digest(
    context: SystemExecutionContext,
) -> str:
    """Return SHA-256 of effective execution semantics."""

    encoded = json.dumps(
        system_execution_context_document(
            context
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


__all__ = [
    "SystemExecutionContext",
    "system_execution_context_digest",
    "system_execution_context_document",
]
