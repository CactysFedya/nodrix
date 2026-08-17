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


class SystemExecutionContextBindingError(ValueError):
    """A materialized execution context does not match its exact Plan binding."""


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


def validate_system_execution_context_binding(
    expected_sha256: str | None,
    context: SystemExecutionContext | None,
) -> None:
    """Require a materialized context to match one exact Plan binding."""

    if (
        expected_sha256 is not None
        and not isinstance(
            expected_sha256,
            str,
        )
    ):
        raise TypeError(
            "expected_sha256 must be a string or None"
        )

    if (
        context is not None
        and not isinstance(
            context,
            SystemExecutionContext,
        )
    ):
        raise TypeError(
            "context must be a SystemExecutionContext or None"
        )

    if expected_sha256 is None:
        if context is not None:
            raise SystemExecutionContextBindingError(
                "Plan does not bind an execution context, "
                "but a materialized context was supplied"
            )
        return

    if context is None:
        raise SystemExecutionContextBindingError(
            "Plan requires a materialized execution context"
        )

    actual_sha256 = system_execution_context_digest(
        context
    )

    if actual_sha256 != expected_sha256:
        raise SystemExecutionContextBindingError(
            "materialized execution context digest does not "
            "match Plan execution_context_sha256: "
            f"expected={expected_sha256}, actual={actual_sha256}"
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
    "validate_system_execution_context_binding",
    "SystemExecutionContextBindingError",
    "SystemExecutionContext",
    "system_execution_context_digest",
    "system_execution_context_document",
]
