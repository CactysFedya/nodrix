"""Canonical resolved runtime mechanics for System execution.

SystemExecutionContext.runtime is the canonical carrier of execution-time
runtime policy. This module interprets only the explicitly versioned
``runtime.mechanics`` subtree required by the direct runtime engine.

It intentionally does not:

* import legacy PipelineManifest or RuntimeConfig models;
* interpret legacy ``runtime.memory`` fields;
* invent process-memory or telemetry defaults;
* depend on a backend implementation;
* perform node, graph, queue, or lifecycle materialization.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .execution_context import (
    SystemExecutionContext,
)


class RuntimeMechanicsResolutionError(
    ValueError
):
    """Canonical runtime mechanics are malformed."""

    def __init__(
        self,
        path: str,
        message: str,
    ) -> None:
        self.path = path
        self.message = message

        super().__init__(
            f"{path}: {message}"
        )


@dataclass(
    frozen=True,
    slots=True,
)
class ResolvedRuntimePoolMechanics:
    """One explicitly configured bounded shared-memory pool."""

    block_size: int
    capacity: int
    threshold: int


@dataclass(
    frozen=True,
    slots=True,
)
class ResolvedProcessRuntimeMechanics:
    """Explicit process-isolation engine mechanics."""

    input_pool: ResolvedRuntimePoolMechanics
    output_pool: ResolvedRuntimePoolMechanics


@dataclass(
    frozen=True,
    slots=True,
)
class ResolvedRuntimeMechanics:
    """Runtime mechanics resolved without hidden defaults."""

    telemetry_sample_capacity: (
        int
        | None
    ) = None

    process: (
        ResolvedProcessRuntimeMechanics
        | None
    ) = None


def _mapping(
    value: Any,
    *,
    path: str,
) -> Mapping[str, Any]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise RuntimeMechanicsResolutionError(
            path,
            "must be a mapping",
        )

    return value


def _reject_unknown(
    value: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    path: str,
) -> None:
    unknown = sorted(
        str(key)
        for key in value
        if key not in allowed
    )

    if unknown:
        raise RuntimeMechanicsResolutionError(
            path,
            (
                "unsupported fields: "
                + ", ".join(
                    unknown
                )
            ),
        )


def _required_int(
    value: Mapping[str, Any],
    key: str,
    *,
    path: str,
    minimum: int,
) -> int:
    field_path = (
        f"{path}.{key}"
    )

    if key not in value:
        raise RuntimeMechanicsResolutionError(
            field_path,
            "is required",
        )

    raw = value[key]

    if (
        isinstance(raw, bool)
        or not isinstance(raw, int)
    ):
        raise RuntimeMechanicsResolutionError(
            field_path,
            "must be an integer",
        )

    if raw < minimum:
        raise RuntimeMechanicsResolutionError(
            field_path,
            (
                "must be greater than or "
                f"equal to {minimum}"
            ),
        )

    return raw


def _resolve_pool(
    value: Any,
    *,
    path: str,
) -> ResolvedRuntimePoolMechanics:
    mapping = _mapping(
        value,
        path=path,
    )

    _reject_unknown(
        mapping,
        allowed=frozenset(
            {
                "block_size",
                "capacity",
                "threshold",
            }
        ),
        path=path,
    )

    return ResolvedRuntimePoolMechanics(
        block_size=_required_int(
            mapping,
            "block_size",
            path=path,
            minimum=4096,
        ),
        capacity=_required_int(
            mapping,
            "capacity",
            path=path,
            minimum=1,
        ),
        threshold=_required_int(
            mapping,
            "threshold",
            path=path,
            minimum=0,
        ),
    )


def resolve_runtime_mechanics(
    context: (
        SystemExecutionContext
        | None
    ),
) -> ResolvedRuntimeMechanics:
    """Resolve explicit canonical runtime mechanics without defaults."""

    if context is None:
        return ResolvedRuntimeMechanics()

    raw = context.runtime.get(
        "mechanics"
    )

    if raw is None:
        return ResolvedRuntimeMechanics()

    mechanics = _mapping(
        raw,
        path="runtime.mechanics",
    )

    _reject_unknown(
        mechanics,
        allowed=frozenset(
            {
                "telemetry",
                "process",
            }
        ),
        path="runtime.mechanics",
    )

    telemetry_sample_capacity = None

    if "telemetry" in mechanics:
        telemetry = _mapping(
            mechanics["telemetry"],
            path=(
                "runtime.mechanics.telemetry"
            ),
        )

        _reject_unknown(
            telemetry,
            allowed=frozenset(
                {
                    "sample_capacity",
                }
            ),
            path=(
                "runtime.mechanics.telemetry"
            ),
        )

        if "sample_capacity" in telemetry:
            telemetry_sample_capacity = (
                _required_int(
                    telemetry,
                    "sample_capacity",
                    path=(
                        "runtime.mechanics.telemetry"
                    ),
                    minimum=1,
                )
            )

    process = None

    if "process" in mechanics:
        process_mapping = _mapping(
            mechanics["process"],
            path=(
                "runtime.mechanics.process"
            ),
        )

        _reject_unknown(
            process_mapping,
            allowed=frozenset(
                {
                    "input_pool",
                    "output_pool",
                }
            ),
            path=(
                "runtime.mechanics.process"
            ),
        )

        if "input_pool" not in process_mapping:
            raise RuntimeMechanicsResolutionError(
                (
                    "runtime.mechanics.process"
                    ".input_pool"
                ),
                "is required",
            )

        if "output_pool" not in process_mapping:
            raise RuntimeMechanicsResolutionError(
                (
                    "runtime.mechanics.process"
                    ".output_pool"
                ),
                "is required",
            )

        process = (
            ResolvedProcessRuntimeMechanics(
                input_pool=_resolve_pool(
                    process_mapping[
                        "input_pool"
                    ],
                    path=(
                        "runtime.mechanics.process"
                        ".input_pool"
                    ),
                ),
                output_pool=_resolve_pool(
                    process_mapping[
                        "output_pool"
                    ],
                    path=(
                        "runtime.mechanics.process"
                        ".output_pool"
                    ),
                ),
            )
        )

    return ResolvedRuntimeMechanics(
        telemetry_sample_capacity=(
            telemetry_sample_capacity
        ),
        process=process,
    )


__all__ = [
    "ResolvedProcessRuntimeMechanics",
    "ResolvedRuntimeMechanics",
    "ResolvedRuntimePoolMechanics",
    "RuntimeMechanicsResolutionError",
    "resolve_runtime_mechanics",
]
