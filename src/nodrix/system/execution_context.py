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

from pydantic import Field, field_validator

from ._base import SystemBaseModel


class SystemExecutionContextBindingError(ValueError):
    """A materialized execution context does not match its exact Plan binding."""


class SystemExecutionContextOverride(SystemBaseModel):
    """One child-specific execution-context overlay.

    Values live in the materialized execution context, not in a System
    Definition or ExecutionPlan. ``inherit=False`` starts the child from an
    empty context before applying this overlay.
    """

    inherit: bool = True
    variables: Mapping[str, str] = Field(default_factory=dict)
    sources: tuple[str, ...] = ()
    runtime: Mapping[str, Any] = Field(default_factory=dict)
    node_defaults: Mapping[str, Any] = Field(default_factory=dict)
    edge_defaults: Mapping[str, Any] = Field(default_factory=dict)
    stream_defaults: Mapping[str, Any] = Field(default_factory=dict)
    systems: Mapping[str, "SystemExecutionContextOverride"] = Field(
        default_factory=dict
    )

    @field_validator("systems")
    @classmethod
    def validate_system_names(
        cls,
        value: Mapping[str, "SystemExecutionContextOverride"],
    ) -> Mapping[str, "SystemExecutionContextOverride"]:
        for name in value:
            if not name.strip() or "." in name or "/" in name:
                raise ValueError(
                    "execution context System name must be non-empty and "
                    "cannot contain '.' or '/'"
                )
        return value


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
    systems: Mapping[str, SystemExecutionContextOverride] = Field(
        default_factory=dict
    )

    @field_validator("systems")
    @classmethod
    def validate_system_names(
        cls,
        value: Mapping[str, SystemExecutionContextOverride],
    ) -> Mapping[str, SystemExecutionContextOverride]:
        for name in value:
            if not name.strip() or "." in name or "/" in name:
                raise ValueError(
                    "execution context System name must be non-empty and "
                    "cannot contain '.' or '/'"
                )
        return value


def _deep_merge(
    base: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in overlay.items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = deepcopy(value)
    return result


def apply_system_execution_context_override(
    context: SystemExecutionContext | None,
    override: SystemExecutionContextOverride,
) -> SystemExecutionContext:
    """Apply one deterministic child overlay to a materialized context."""

    if not isinstance(override, SystemExecutionContextOverride):
        raise TypeError(
            "override must be a SystemExecutionContextOverride"
        )

    base = (
        context
        if context is not None and override.inherit
        else SystemExecutionContext()
    )
    sources = tuple(
        dict.fromkeys(
            (*base.sources, *override.sources)
        )
    )
    systems = dict(base.systems)
    systems.update(override.systems)

    return SystemExecutionContext(
        variables={
            **base.variables,
            **override.variables,
        },
        sources=sources,
        runtime=_deep_merge(base.runtime, override.runtime),
        node_defaults=_deep_merge(
            base.node_defaults,
            override.node_defaults,
        ),
        edge_defaults=_deep_merge(
            base.edge_defaults,
            override.edge_defaults,
        ),
        stream_defaults=_deep_merge(
            base.stream_defaults,
            override.stream_defaults,
        ),
        systems=systems,
    )


def child_system_execution_context(
    context: SystemExecutionContext | None,
    child: str,
) -> SystemExecutionContext | None:
    """Derive one child's context and consume only its override branch."""

    if context is None:
        return None

    child = child.strip()
    if not child:
        raise ValueError("child must be non-empty")

    inherited = context.model_copy(
        update={"systems": {}},
    )
    override = context.systems.get(child)
    if override is None:
        return inherited
    return apply_system_execution_context_override(
        inherited,
        override,
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

    document = deepcopy(
        context.model_dump(
            mode="json",
            by_alias=True,
        )
    )
    if not document.get("systems"):
        document.pop("systems", None)
    return document


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
    "apply_system_execution_context_override",
    "child_system_execution_context",
    "SystemExecutionContextBindingError",
    "SystemExecutionContext",
    "SystemExecutionContextOverride",
    "system_execution_context_digest",
    "system_execution_context_document",
]
