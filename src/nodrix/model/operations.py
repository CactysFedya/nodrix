"""Canonical operation model shared across Nodrix engineering domains.

An Operation describes intent: what action should be performed and which
canonical entity is its subject.

It deliberately does not describe workflow steps, backend mechanics, execution
state, or the resulting Run.  Those belong to later layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
import re
from typing import Any, Mapping

from .identity import EntityRef, RevisionRef


_OPERATION_KIND_RE = re.compile(r"^[a-z][a-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class OperationKind:
    """Stable name of an operation kind.

    Operation kinds are intentionally extensible rather than represented by a
    closed Enum.  Nodrix provides conventional built-in names such as ``run``,
    ``build`` and ``benchmark``, while packages may introduce namespaced kinds
    later without changing the canonical model.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("operation kind must be a string")

        normalized = self.value.strip().lower()
        if not normalized:
            raise ValueError("operation kind must be non-empty")

        if not _OPERATION_KIND_RE.fullmatch(normalized):
            raise ValueError(
                "operation kind must start with a letter and contain only "
                "lowercase letters, digits, '.', '_' or '-'"
            )

        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(cls, value: str | "OperationKind") -> "OperationKind":
        if isinstance(value, cls):
            return value
        return cls(value)


BUILD = OperationKind("build")
TEST = OperationKind("test")
VALIDATE = OperationKind("validate")
RUN = OperationKind("run")
PROFILE = OperationKind("profile")
BENCHMARK = OperationKind("benchmark")
DIAGNOSE = OperationKind("diagnose")
CALIBRATE = OperationKind("calibrate")
EXPORT = OperationKind("export")
PACKAGE = OperationKind("package")
CLEANUP = OperationKind("cleanup")


@dataclass(frozen=True, slots=True)
class Operation:
    """One requested action over a canonical Nodrix entity.

    ``subject`` identifies the logical entity.

    ``subject_revision`` optionally pins the operation to one immutable revision
    of that same entity.  When omitted, revision resolution belongs to planning.

    ``parameters`` contain operation-specific intent only.  Resolved commands,
    process handles, backend state, and execution results must not be stored
    here.
    """

    kind: OperationKind | str
    subject: EntityRef
    subject_revision: RevisionRef | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = OperationKind.parse(self.kind)
        object.__setattr__(self, "kind", kind)

        if not isinstance(self.subject, EntityRef):
            raise TypeError("operation subject must be an EntityRef")

        revision = self.subject_revision
        if revision is not None:
            if not isinstance(revision, RevisionRef):
                raise TypeError(
                    "subject_revision must be a RevisionRef or None"
                )
            if revision.entity != self.subject:
                raise ValueError(
                    "subject_revision must reference the operation subject"
                )

        if not isinstance(self.parameters, Mapping):
            raise TypeError("operation parameters must be a mapping")

        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )

    @property
    def kind_name(self) -> str:
        return str(self.kind)


__all__ = [
    "BENCHMARK",
    "BUILD",
    "CALIBRATE",
    "CLEANUP",
    "DIAGNOSE",
    "EXPORT",
    "Operation",
    "OperationKind",
    "PACKAGE",
    "PROFILE",
    "RUN",
    "TEST",
    "VALIDATE",
]
