"""Canonical references to immutable and historical Nodrix records.

Logical domain entities use EntityRef.
Immutable entity revisions use RevisionRef.
Historical execution records such as plans, executions, and runs use RecordRef.

Keeping these concepts separate prevents runtime history from pretending to be
a logical system entity while still allowing all of them to participate in the
canonical relation graph.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TypeAlias

from .identity import EntityRef, RevisionRef


_RECORD_KIND_RE = re.compile(r"^[a-z][a-z0-9._-]*$")
_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


@dataclass(frozen=True, slots=True)
class RecordRef:
    """Reference to one historical or resolved Nodrix record.

    Examples:

        nodrix://record/plan/plan-001
        nodrix://record/execution/execution-001
        nodrix://record/run/run-001

    RecordRef is intentionally different from EntityRef.  A Run is a historical
    event record, not the logical system or component that was executed.
    """

    kind: str
    record_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str):
            raise TypeError("record kind must be a string")

        kind = self.kind.strip().lower()
        if not kind:
            raise ValueError("record kind must be non-empty")

        if not _RECORD_KIND_RE.fullmatch(kind):
            raise ValueError(
                "record kind must start with a letter and contain only "
                "lowercase letters, digits, '.', '_' or '-'"
            )

        if not isinstance(self.record_id, str):
            raise TypeError("record_id must be a string")

        record_id = self.record_id.strip()
        if not record_id:
            raise ValueError("record_id must be non-empty")

        if not _RECORD_ID_RE.fullmatch(record_id):
            raise ValueError(
                "record_id must start with an alphanumeric character and "
                "contain only letters, digits, '.', '_', '-' or ':'"
            )

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "record_id", record_id)

    @property
    def canonical(self) -> str:
        return f"nodrix://record/{self.kind}/{self.record_id}"

    def __str__(self) -> str:
        return self.canonical

    @classmethod
    def parse(cls, value: str) -> "RecordRef":
        if not isinstance(value, str):
            raise TypeError("record reference must be a string")

        prefix = "nodrix://record/"
        if not value.startswith(prefix):
            raise ValueError(
                f"record reference must start with {prefix!r}"
            )

        body = value[len(prefix):]
        kind, separator, record_id = body.partition("/")

        if not separator or not kind or not record_id:
            raise ValueError(
                "record reference must contain kind and record id"
            )

        if "/" in record_id:
            raise ValueError(
                "record reference contains unexpected path segments"
            )

        return cls(
            kind=kind,
            record_id=record_id,
        )


CanonicalRef: TypeAlias = EntityRef | RevisionRef | RecordRef


def parse_canonical_ref(value: str) -> CanonicalRef:
    """Parse any canonical Nodrix reference."""

    if not isinstance(value, str):
        raise TypeError("canonical reference must be a string")

    if value.startswith("nodrix://record/"):
        return RecordRef.parse(value)

    if "@" in value:
        return RevisionRef.parse(value)

    return EntityRef.parse(value)


__all__ = [
    "CanonicalRef",
    "RecordRef",
    "parse_canonical_ref",
]
