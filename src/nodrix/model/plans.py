"""Canonical planning envelope shared across Nodrix execution domains.

A PlanRecord connects one canonical Operation to one resolved implementation
plan.

The actual plan remains domain-specific.  For example, its payload may be a
SystemExecutionPlan or a WorkflowPlanResult.  The canonical model does not
force those different structures into one giant plan type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType
import re
from typing import Any, Mapping

from .identity import EntityRef, RevisionRef
from .operations import Operation


_PLAN_KIND_RE = re.compile(r"^[a-z][a-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class PlanKind:
    """Stable extensible name identifying a domain-specific plan type."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("plan kind must be a string")

        normalized = self.value.strip().lower()
        if not normalized:
            raise ValueError("plan kind must be non-empty")

        if not _PLAN_KIND_RE.fullmatch(normalized):
            raise ValueError(
                "plan kind must start with a letter and contain only "
                "lowercase letters, digits, '.', '_' or '-'"
            )

        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(cls, value: str | "PlanKind") -> "PlanKind":
        if isinstance(value, cls):
            return value
        return cls(value)


SYSTEM_EXECUTION = PlanKind("system-execution")
WORKFLOW = PlanKind("workflow")
BENCHMARK_PLAN = PlanKind("benchmark")
OPTIMIZATION_PLAN = PlanKind("optimization")

PLAN_IDENTITY_SCHEMA = "nodrix.plan-identity/v1"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _identity_value(
    value: Any,
    *,
    path: str,
) -> Any:
    """Normalize one canonical identity value to stable JSON data."""

    if value is None or isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ):
        return value

    if isinstance(
        value,
        (
            EntityRef,
            RevisionRef,
        ),
    ):
        return value.canonical

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}

        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"{path} keys must be strings"
                )

            result[key] = _identity_value(
                item,
                path=f"{path}.{key}",
            )

        return result

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return [
            _identity_value(
                item,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(value)
        ]

    raise TypeError(
        f"{path} contains unsupported canonical "
        f"identity value {type(value).__name__}"
    )


def canonical_plan_id(
    *,
    kind: PlanKind | str,
    operation: Operation,
    subject_revision: RevisionRef,
    payload_sha256: str,
) -> str:
    """Return the stable identity of one complete canonical PlanRecord.

    The domain payload digest identifies exact domain semantics.  This helper
    additionally binds those semantics to the canonical Operation and resolved
    subject revision, producing the historical PlanRecord identity.
    """

    canonical_kind = PlanKind.parse(
        kind
    )

    if not isinstance(operation, Operation):
        raise TypeError(
            "operation must be an Operation"
        )

    if not isinstance(
        subject_revision,
        RevisionRef,
    ):
        raise TypeError(
            "subject_revision must be a RevisionRef"
        )

    if (
        subject_revision.entity
        != operation.subject
    ):
        raise ValueError(
            "subject_revision must reference "
            "the operation subject"
        )

    if (
        operation.subject_revision
        is not None
        and operation.subject_revision
        != subject_revision
    ):
        raise ValueError(
            "subject_revision must match the revision "
            "pinned by the operation"
        )

    if not isinstance(
        payload_sha256,
        str,
    ):
        raise TypeError(
            "payload_sha256 must be a string"
        )

    normalized_digest = (
        payload_sha256
        .strip()
        .lower()
    )

    if not _SHA256_RE.fullmatch(
        normalized_digest
    ):
        raise ValueError(
            "payload_sha256 must contain exactly "
            "64 hexadecimal characters"
        )

    document = {
        "schema": PLAN_IDENTITY_SCHEMA,
        "kind": canonical_kind.value,
        "operation": {
            "kind": operation.kind_name,
            "subject": (
                operation.subject.canonical
            ),
            "subject_revision": (
                operation.subject_revision.canonical
                if operation.subject_revision
                is not None
                else None
            ),
            "parameters": _identity_value(
                operation.parameters,
                path="operation.parameters",
            ),
        },
        "subject_revision": (
            subject_revision.canonical
        ),
        "payload_sha256": (
            normalized_digest
        ),
    }

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    digest = hashlib.sha256(
        encoded
    ).hexdigest()

    return f"plan-{digest}"


def _plan_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("plan_id must be a string")

    normalized = value.strip()
    if not normalized:
        raise ValueError("plan_id must be non-empty")

    return normalized


@dataclass(frozen=True, slots=True)
class PlanRecord:
    """Canonical envelope around one resolved domain-specific plan.

    Planning resolves the logical operation against a concrete revision of its
    subject.  Therefore ``subject_revision`` is mandatory here even though it
    is optional on Operation.

    ``payload`` remains owned by the planning domain.  The canonical layer only
    preserves its association with the Operation and resolved subject revision.
    """

    plan_id: str
    kind: PlanKind | str
    operation: Operation
    subject_revision: RevisionRef
    payload: Any = field(repr=False, compare=False)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "plan_id",
            _plan_id(self.plan_id),
        )
        object.__setattr__(
            self,
            "kind",
            PlanKind.parse(self.kind),
        )

        if not isinstance(self.operation, Operation):
            raise TypeError("operation must be an Operation")

        if not isinstance(self.subject_revision, RevisionRef):
            raise TypeError(
                "subject_revision must be a RevisionRef"
            )

        if self.subject_revision.entity != self.operation.subject:
            raise ValueError(
                "subject_revision must reference the operation subject"
            )

        operation_revision = self.operation.subject_revision
        if (
            operation_revision is not None
            and operation_revision != self.subject_revision
        ):
            raise ValueError(
                "plan subject revision must match the revision pinned "
                "by the operation"
            )

        if not isinstance(self.metadata, Mapping):
            raise TypeError("plan metadata must be a mapping")

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    @property
    def kind_name(self) -> str:
        return str(self.kind)

    @property
    def subject(self) -> EntityRef:
        return self.operation.subject


__all__ = [
    "BENCHMARK_PLAN",
    "OPTIMIZATION_PLAN",
    "PLAN_IDENTITY_SCHEMA",
    "PlanKind",
    "PlanRecord",
    "SYSTEM_EXECUTION",
    "WORKFLOW",
    "canonical_plan_id",
]
