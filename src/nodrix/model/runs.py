"""Canonical immutable Run records.

A RunRecord is the durable historical record of one completed ExecutionRecord.

It deliberately does not own domain-specific artifacts, datasets, logs, or
metrics schemas.  Those are attached through canonical records and relations
in later layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .executions import ExecutionRecord


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")

    return normalized


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Durable record of one finished execution.

    A RunRecord can only be created from a terminal ExecutionRecord.  The
    execution must also contain both start and finish timestamps so the Run is
    a complete historical record rather than a live runtime snapshot.

    ``summary`` stores small operation-independent result information.
    Domain-specific outputs such as datasets and artifacts are represented by
    their own canonical records and linked to this Run later.
    """

    run_id: str
    execution: ExecutionRecord
    summary: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "run_id",
            _required_text(
                self.run_id,
                field_name="run_id",
            ),
        )

        if not isinstance(self.execution, ExecutionRecord):
            raise TypeError(
                "execution must be an ExecutionRecord"
            )

        if not self.execution.terminal:
            raise ValueError(
                "RunRecord requires a terminal ExecutionRecord"
            )

        if self.execution.started_at is None:
            raise ValueError(
                "RunRecord requires execution.started_at"
            )

        if self.execution.finished_at is None:
            raise ValueError(
                "RunRecord requires execution.finished_at"
            )

        if not isinstance(self.summary, Mapping):
            raise TypeError("run summary must be a mapping")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("run metadata must be a mapping")

        object.__setattr__(
            self,
            "summary",
            MappingProxyType(dict(self.summary)),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    @property
    def operation(self):
        return self.execution.operation

    @property
    def plan(self):
        return self.execution.plan

    @property
    def subject(self):
        return self.execution.subject

    @property
    def subject_revision(self):
        return self.execution.subject_revision

    @property
    def execution_id(self) -> str:
        return self.execution.execution_id

    @property
    def state(self):
        return self.execution.state

    @property
    def successful(self) -> bool:
        return self.execution.successful

    @property
    def started_at(self):
        return self.execution.started_at

    @property
    def finished_at(self):
        return self.execution.finished_at


__all__ = [
    "RunRecord",
]
