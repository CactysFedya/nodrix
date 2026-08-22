"""Canonical resolved node execution mechanics.

System Definitions describe architecture.  Execution-specific mechanics are
supplied through SystemExecutionContext and resolved by the planner before a
backend starts.

This module defines the canonical typed representation used by that resolution.
It deliberately does not depend on PipelineManifest, NodeConfig, a backend, or
runtime implementation classes.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Literal, Mapping

from pydantic import Field, model_validator

from ._base import SystemBaseModel


SynchronizationPolicy = Literal[
    "exact_sequence",
    "approximate_timestamp",
    "latest_available",
    "zip",
]

IsolationMode = Literal[
    "in_process",
    "process",
]

FailurePolicy = Literal[
    "stop_execution",
    "restart_node",
    "skip_message",
    "disable_branch",
    "isolate_branch",
    "fallback_node",
]

HealthTimeoutPolicy = Literal[
    "report",
    "restart_node",
    "stop_execution",
]


class NodeExecutionResolutionError(ValueError):
    """Execution-context node defaults cannot be resolved canonically."""

    def __init__(
        self,
        path: str,
        message: str,
    ) -> None:
        self.path = path
        self.message = message

        prefix = (
            path
            if path
            else "node_defaults"
        )

        super().__init__(
            f"{prefix}: {message}"
        )


class ResolvedNodeSynchronization(
    SystemBaseModel
):
    policy: SynchronizationPolicy = (
        "exact_sequence"
    )

    tolerance_ns: int = Field(
        default=20_000_000,
        ge=0,
    )

    trigger_port: str | None = None

    optional_inputs: tuple[
        str,
        ...,
    ] = ()


class ResolvedNodeExecutionPlacement(
    SystemBaseModel
):
    isolation: IsolationMode = "in_process"

    cpu_affinity: tuple[
        int,
        ...,
    ] = ()

    device: str = Field(
        default="auto",
        min_length=1,
    )


class ResolvedNodeFailurePolicy(
    SystemBaseModel
):
    policy: FailurePolicy = "stop_execution"

    max_restarts: int = Field(
        default=3,
        ge=0,
        le=1000,
    )

    backoff_ms: int = Field(
        default=250,
        ge=0,
        le=600_000,
    )

    fallback_uses: str | None = None

    @model_validator(
        mode="after"
    )
    def validate_fallback(
        self,
    ) -> "ResolvedNodeFailurePolicy":
        if (
            self.policy == "fallback_node"
            and not self.fallback_uses
        ):
            raise ValueError(
                "fallback_node requires "
                "fallback_uses"
            )

        return self


class ResolvedNodeHealthPolicy(
    SystemBaseModel
):
    timeout_ns: int = Field(
        default=0,
        ge=0,
    )

    on_timeout: HealthTimeoutPolicy = "report"


class ResolvedNodeResourceLimits(
    SystemBaseModel
):
    memory_limit_mb: int | None = Field(
        default=None,
        ge=16,
    )

    cpu_limit: float | None = Field(
        default=None,
        gt=0,
    )

    max_message_bytes: int = Field(
        default=256 * 1024 * 1024,
        ge=1024,
    )


class ResolvedNodeMemoryPolicy(
    SystemBaseModel
):
    inputs: Mapping[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    outputs: Mapping[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )


class ResolvedNodeExecutionPolicy(
    SystemBaseModel
):
    """Fully explicit mechanics required before direct node execution."""

    synchronization: (
        ResolvedNodeSynchronization
    ) = Field(
        default_factory=(
            ResolvedNodeSynchronization
        )
    )

    execution: (
        ResolvedNodeExecutionPlacement
    ) = Field(
        default_factory=(
            ResolvedNodeExecutionPlacement
        )
    )

    failure: (
        ResolvedNodeFailurePolicy
    ) = Field(
        default_factory=(
            ResolvedNodeFailurePolicy
        )
    )

    health: (
        ResolvedNodeHealthPolicy
    ) = Field(
        default_factory=(
            ResolvedNodeHealthPolicy
        )
    )

    limits: (
        ResolvedNodeResourceLimits
    ) = Field(
        default_factory=(
            ResolvedNodeResourceLimits
        )
    )

    memory: (
        ResolvedNodeMemoryPolicy
    ) = Field(
        default_factory=(
            ResolvedNodeMemoryPolicy
        )
    )


_ALLOWED_DEFAULT_KEYS = frozenset(
    {
        "parameters",
        "synchronization",
        "execution",
        "failure",
        "health",
        "resources",
        "memory",
    }
)

_ALLOWED_SYNCHRONIZATION_KEYS = frozenset(
    {
        "policy",
        "tolerance_ms",
        "trigger_port",
        "optional_inputs",
    }
)

_ALLOWED_EXECUTION_KEYS = frozenset(
    {
        "isolation",
        "cpu_affinity",
        "device",
    }
)

_ALLOWED_FAILURE_KEYS = frozenset(
    {
        "policy",
        "max_restarts",
        "backoff_ms",
        "fallback_uses",
    }
)

_ALLOWED_HEALTH_KEYS = frozenset(
    {
        "timeout_ms",
        "on_timeout",
    }
)

_ALLOWED_RESOURCE_KEYS = frozenset(
    {
        "memory_limit_mb",
        "cpu_limit",
        "max_message_bytes",
    }
)

_ALLOWED_MEMORY_KEYS = frozenset(
    {
        "inputs",
        "outputs",
    }
)


def _mapping(
    value: Any,
    *,
    path: str,
) -> Mapping[str, Any]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise NodeExecutionResolutionError(
            path,
            "must be a mapping",
        )

    return value


def _section(
    defaults: Mapping[str, Any],
    name: str,
    *,
    allowed: frozenset[str],
) -> Mapping[str, Any]:
    value = defaults.get(
        name,
        {},
    )

    mapping = _mapping(
        value,
        path=name,
    )

    unknown = sorted(
        set(mapping)
        - allowed
    )

    if unknown:
        raise NodeExecutionResolutionError(
            name,
            "unsupported fields: "
            + ", ".join(unknown),
        )

    return mapping


def _milliseconds_to_ns(
    value: Any,
    *,
    path: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(
            value,
            (
                int,
                float,
            ),
        )
    ):
        raise NodeExecutionResolutionError(
            path,
            "must be a non-negative real number",
        )

    numeric = float(value)

    if (
        not math.isfinite(numeric)
        or numeric < 0.0
    ):
        raise NodeExecutionResolutionError(
            path,
            "must be a finite non-negative "
            "real number",
        )

    return int(
        numeric
        * 1_000_000
    )


def _failure_policy(
    value: Any,
) -> Any:
    aliases = {
        "restart": "restart_node",
        "stop_pipeline": "stop_execution",
    }

    return aliases.get(
        value,
        value,
    )


def _health_policy(
    value: Any,
) -> Any:
    aliases = {
        "restart": "restart_node",
        "stop_pipeline": "stop_execution",
    }

    return aliases.get(
        value,
        value,
    )


def _deep_merge(
    defaults: Mapping[str, Any],
    explicit: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge defaults below explicit values without sharing mutable state."""

    result = deepcopy(
        dict(defaults)
    )

    for key, value in explicit.items():
        current = result.get(
            key
        )

        if (
            isinstance(
                current,
                Mapping,
            )
            and isinstance(
                value,
                Mapping,
            )
        ):
            result[key] = _deep_merge(
                current,
                value,
            )
        else:
            result[key] = deepcopy(
                value
            )

    return result


def resolve_node_execution_defaults(
    defaults: Mapping[str, Any] | None,
) -> tuple[
    dict[str, Any],
    ResolvedNodeExecutionPolicy,
]:
    """Resolve one ``node_defaults[uses]`` entry.

    The returned parameters are defaults only.  The planner must merge explicit
    NodeInstance parameters above them and System parameter bindings above that
    result.

    Legacy Pipeline policy spellings accepted by existing profiles are
    normalized here and never become canonical plan values.
    """

    if defaults is None:
        return (
            {},
            ResolvedNodeExecutionPolicy(),
        )

    defaults = _mapping(
        defaults,
        path="node_defaults",
    )

    unknown = sorted(
        set(defaults)
        - _ALLOWED_DEFAULT_KEYS
    )

    if unknown:
        raise NodeExecutionResolutionError(
            "node_defaults",
            "unsupported fields: "
            + ", ".join(unknown),
        )

    parameters = deepcopy(
        dict(
            _mapping(
                defaults.get(
                    "parameters",
                    {},
                ),
                path="parameters",
            )
        )
    )

    synchronization = _section(
        defaults,
        "synchronization",
        allowed=(
            _ALLOWED_SYNCHRONIZATION_KEYS
        ),
    )

    execution = _section(
        defaults,
        "execution",
        allowed=_ALLOWED_EXECUTION_KEYS,
    )

    failure = _section(
        defaults,
        "failure",
        allowed=_ALLOWED_FAILURE_KEYS,
    )

    health = _section(
        defaults,
        "health",
        allowed=_ALLOWED_HEALTH_KEYS,
    )

    resources = _section(
        defaults,
        "resources",
        allowed=_ALLOWED_RESOURCE_KEYS,
    )

    memory = _section(
        defaults,
        "memory",
        allowed=_ALLOWED_MEMORY_KEYS,
    )

    synchronization_payload = dict(
        synchronization
    )

    if (
        "tolerance_ms"
        in synchronization_payload
    ):
        synchronization_payload[
            "tolerance_ns"
        ] = _milliseconds_to_ns(
            synchronization_payload.pop(
                "tolerance_ms"
            ),
            path=(
                "synchronization."
                "tolerance_ms"
            ),
        )

    failure_payload = dict(
        failure
    )

    if "policy" in failure_payload:
        failure_payload[
            "policy"
        ] = _failure_policy(
            failure_payload[
                "policy"
            ]
        )

    health_payload = dict(
        health
    )

    if (
        "timeout_ms"
        in health_payload
    ):
        health_payload[
            "timeout_ns"
        ] = _milliseconds_to_ns(
            health_payload.pop(
                "timeout_ms"
            ),
            path="health.timeout_ms",
        )

    if (
        "on_timeout"
        in health_payload
    ):
        health_payload[
            "on_timeout"
        ] = _health_policy(
            health_payload[
                "on_timeout"
            ]
        )

    policy = (
        ResolvedNodeExecutionPolicy(
            synchronization=(
                ResolvedNodeSynchronization(
                    **synchronization_payload
                )
            ),
            execution=(
                ResolvedNodeExecutionPlacement(
                    **dict(execution)
                )
            ),
            failure=(
                ResolvedNodeFailurePolicy(
                    **failure_payload
                )
            ),
            health=(
                ResolvedNodeHealthPolicy(
                    **health_payload
                )
            ),
            limits=(
                ResolvedNodeResourceLimits(
                    **dict(resources)
                )
            ),
            memory=(
                ResolvedNodeMemoryPolicy(
                    **dict(memory)
                )
            ),
        )
    )

    return (
        parameters,
        policy,
    )


def merge_node_parameters(
    defaults: Mapping[str, Any],
    explicit: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge execution-context parameter defaults under NodeInstance values."""

    return _deep_merge(
        defaults,
        explicit,
    )


__all__ = [
    "NodeExecutionResolutionError",
    "ResolvedNodeExecutionPlacement",
    "ResolvedNodeExecutionPolicy",
    "ResolvedNodeFailurePolicy",
    "ResolvedNodeHealthPolicy",
    "ResolvedNodeMemoryPolicy",
    "ResolvedNodeResourceLimits",
    "ResolvedNodeSynchronization",
    "merge_node_parameters",
    "resolve_node_execution_defaults",
]
