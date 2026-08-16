"""Canonical execution records shared across Nodrix execution domains.

ExecutionRecord describes one actual execution of a resolved PlanRecord.

It deliberately does not contain process handles, backend objects, threads,
runtime queues, workflow executors, or other live implementation objects.
Those remain owned by the executor that performs the work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .plans import PlanRecord


class ExecutionState(str, Enum):
    """Canonical lifecycle state of one execution."""

    CREATED = "created"
    PREPARED = "prepared"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(
        cls,
        value: str | "ExecutionState",
    ) -> "ExecutionState":
        if isinstance(value, cls):
            return value

        if not isinstance(value, str):
            raise TypeError("execution state must be a string")

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("execution state must be non-empty")

        try:
            return cls(normalized)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(
                f"unsupported execution state {value!r}; "
                f"expected one of: {allowed}"
            ) from exc

    @property
    def terminal(self) -> bool:
        return self in {
            self.STOPPED,
            self.COMPLETED,
            self.FAILED,
            self.CANCELLED,
        }

    @property
    def successful(self) -> bool:
        return self in {
            self.STOPPED,
            self.COMPLETED,
        }


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")

    return normalized


def _timestamp(
    value: datetime | None,
    *,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None

    if not isinstance(value, datetime):
        raise TypeError(
            f"{field_name} must be a datetime or None"
        )

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )

    return value


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Canonical snapshot of one actual PlanRecord execution.

    ``execution_id`` identifies this execution independently from the logical
    subject, Operation, and Plan.

    ``executor`` identifies the mechanism coordinating this execution, for
    example ``nodrix.system.orchestrator`` or ``nodrix.workflow``.

    Runtime-specific handles remain outside this record.
    """

    execution_id: str
    plan: PlanRecord
    executor: str
    state: ExecutionState | str = ExecutionState.CREATED
    started_at: datetime | None = None
    finished_at: datetime | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "execution_id",
            _required_text(
                self.execution_id,
                field_name="execution_id",
            ),
        )

        if not isinstance(self.plan, PlanRecord):
            raise TypeError("plan must be a PlanRecord")

        object.__setattr__(
            self,
            "executor",
            _required_text(
                self.executor,
                field_name="executor",
            ),
        )

        state = ExecutionState.parse(self.state)
        object.__setattr__(self, "state", state)

        started_at = _timestamp(
            self.started_at,
            field_name="started_at",
        )
        finished_at = _timestamp(
            self.finished_at,
            field_name="finished_at",
        )

        if finished_at is not None and started_at is None:
            raise ValueError(
                "finished_at requires started_at"
            )

        if (
            started_at is not None
            and finished_at is not None
            and finished_at < started_at
        ):
            raise ValueError(
                "finished_at cannot be earlier than started_at"
            )

        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)

        if not isinstance(self.details, Mapping):
            raise TypeError("execution details must be a mapping")

        object.__setattr__(
            self,
            "details",
            MappingProxyType(dict(self.details)),
        )

    @property
    def operation(self):
        return self.plan.operation

    @property
    def subject(self):
        return self.plan.subject

    @property
    def subject_revision(self):
        return self.plan.subject_revision

    @property
    def terminal(self) -> bool:
        return self.state.terminal

    @property
    def successful(self) -> bool:
        return self.state.successful


__all__ = [
    "ExecutionRecord",
    "ExecutionState",
]
