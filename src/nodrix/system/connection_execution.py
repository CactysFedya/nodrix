"""Canonical execution policy for one planned graph Connection.

A System Connection describes topology. Runtime queue and edge-memory
mechanics are resolved separately from SystemExecutionContext.edge_defaults
while building the canonical SystemExecutionPlan.

The resolved objects in this module are backend-neutral. Direct runtimes
consume them mechanically and must not read execution-context defaults,
legacy Pipeline EdgeConfig objects, or compatibility extensions.

The base policy declared here is the canonical Nodrix System execution
contract:

* bounded queue capacity: 8;
* queue policy: block;
* edge memory domain: auto;
* implicit edge copies allowed.

Runtime-wide memory policy such as default memory domain or a global
forbid-implicit-copies switch does not belong to an individual Connection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


_CANONICAL_QUEUE_CAPACITY = 8
_CANONICAL_QUEUE_POLICY = "block"
_CANONICAL_MEMORY_DOMAIN = "auto"
_CANONICAL_ALLOW_COPY = True

_QUEUE_POLICIES = frozenset(
    {
        "block",
        "latest",
        "drop_oldest",
        "drop_newest",
    }
)


class ConnectionExecutionResolutionError(
    ValueError
):
    """Connection execution defaults cannot be resolved canonically."""

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
class ResolvedConnectionQueuePolicy:
    """Bounded queue mechanics for one Connection."""

    capacity: int = (
        _CANONICAL_QUEUE_CAPACITY
    )

    policy: str = (
        _CANONICAL_QUEUE_POLICY
    )

    def __post_init__(
        self,
    ) -> None:
        if (
            isinstance(
                self.capacity,
                bool,
            )
            or not isinstance(
                self.capacity,
                int,
            )
            or self.capacity < 1
        ):
            raise ValueError(
                "capacity must be a positive integer"
            )

        if self.policy not in _QUEUE_POLICIES:
            raise ValueError(
                "policy must be one of: "
                + ", ".join(
                    sorted(
                        _QUEUE_POLICIES
                    )
                )
            )


@dataclass(
    frozen=True,
    slots=True,
)
class ResolvedConnectionMemoryPolicy:
    """Per-edge memory-domain mechanics."""

    domain: str = (
        _CANONICAL_MEMORY_DOMAIN
    )

    allow_copy: bool = (
        _CANONICAL_ALLOW_COPY
    )

    def __post_init__(
        self,
    ) -> None:
        if (
            not isinstance(
                self.domain,
                str,
            )
            or not self.domain.strip()
        ):
            raise ValueError(
                "domain must be a non-empty string"
            )

        if not isinstance(
            self.allow_copy,
            bool,
        ):
            raise ValueError(
                "allow_copy must be a boolean"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class ResolvedConnectionExecutionPolicy:
    """Fully resolved mechanics carried by PlannedConnection."""

    queue: ResolvedConnectionQueuePolicy = (
        ResolvedConnectionQueuePolicy()
    )

    memory: ResolvedConnectionMemoryPolicy = (
        ResolvedConnectionMemoryPolicy()
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
        raise ConnectionExecutionResolutionError(
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
        raise ConnectionExecutionResolutionError(
            path,
            (
                "unsupported fields: "
                + ", ".join(
                    unknown
                )
            ),
        )


def _resolve_queue(
    raw: Any,
) -> ResolvedConnectionQueuePolicy:
    path = "edge_defaults.queue"

    value = _mapping(
        raw,
        path=path,
    )

    _reject_unknown(
        value,
        allowed=frozenset(
            {
                "capacity",
                "policy",
            }
        ),
        path=path,
    )

    capacity = value.get(
        "capacity",
        _CANONICAL_QUEUE_CAPACITY,
    )

    policy = value.get(
        "policy",
        _CANONICAL_QUEUE_POLICY,
    )

    try:
        return ResolvedConnectionQueuePolicy(
            capacity=capacity,
            policy=policy,
        )
    except ValueError as exc:
        raise ConnectionExecutionResolutionError(
            path,
            str(exc),
        ) from exc


def _resolve_memory(
    raw: Any,
) -> ResolvedConnectionMemoryPolicy:
    path = "edge_defaults.memory"

    value = _mapping(
        raw,
        path=path,
    )

    _reject_unknown(
        value,
        allowed=frozenset(
            {
                "domain",
                "allow_copy",
            }
        ),
        path=path,
    )

    domain = value.get(
        "domain",
        _CANONICAL_MEMORY_DOMAIN,
    )

    allow_copy = value.get(
        "allow_copy",
        _CANONICAL_ALLOW_COPY,
    )

    try:
        return ResolvedConnectionMemoryPolicy(
            domain=domain,
            allow_copy=allow_copy,
        )
    except ValueError as exc:
        raise ConnectionExecutionResolutionError(
            path,
            str(exc),
        ) from exc


def resolve_connection_execution_defaults(
    defaults: Mapping[str, Any] | None,
) -> ResolvedConnectionExecutionPolicy:
    """Resolve one canonical Connection policy without legacy state."""

    if defaults is None:
        defaults = {}

    value = _mapping(
        defaults,
        path="edge_defaults",
    )

    _reject_unknown(
        value,
        allowed=frozenset(
            {
                "queue",
                "memory",
            }
        ),
        path="edge_defaults",
    )

    queue = (
        ResolvedConnectionQueuePolicy()
        if "queue" not in value
        else _resolve_queue(
            value["queue"]
        )
    )

    memory = (
        ResolvedConnectionMemoryPolicy()
        if "memory" not in value
        else _resolve_memory(
            value["memory"]
        )
    )

    return ResolvedConnectionExecutionPolicy(
        queue=queue,
        memory=memory,
    )


__all__ = [
    "ConnectionExecutionResolutionError",
    "ResolvedConnectionExecutionPolicy",
    "ResolvedConnectionMemoryPolicy",
    "ResolvedConnectionQueuePolicy",
    "resolve_connection_execution_defaults",
]
