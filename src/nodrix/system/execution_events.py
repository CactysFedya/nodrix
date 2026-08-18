"""Versioned machine-readable events for canonical System execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, StrEnum
import json
import math
from pathlib import Path
from typing import Any, ClassVar, Mapping

from .backend import (
    BackendExecutionStatus,
    ExecutionObservation,
)
from .orchestration import (
    ChildSystemExecutionStatus,
    ScopeExecutionStatus,
    SystemExecutionStatus,
)


EXECUTION_EVENT_API_VERSION = (
    "nodrix.execution.event/v1"
)
EXECUTION_EVENT_KIND = "ExecutionEvent"


class ExecutionEventKind(StrEnum):
    """Lifecycle event emitted by one canonical System execution."""

    PREPARED = "prepared"
    STARTED = "started"
    SNAPSHOT = "snapshot"
    STOPPING = "stopping"
    FINISHED = "finished"
    ERROR = "error"


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _timestamp_text(value: datetime) -> str:
    return (
        value
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _json_value(value: Any) -> Any:
    """Convert backend details into deterministic JSON-compatible values."""

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(
                "datetime values must include timezone information"
            )
        return _timestamp_text(value)

    if isinstance(value, Path):
        return str(value)

    if value is None or isinstance(
        value,
        (
            bool,
            int,
            str,
        ),
    ):
        return value

    if isinstance(value, float):
        return (
            value
            if math.isfinite(value)
            else str(value)
        )

    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return [
            _json_value(item)
            for item in value
        ]

    if isinstance(
        value,
        (
            set,
            frozenset,
        ),
    ):
        return [
            _json_value(item)
            for item in sorted(
                value,
                key=str,
            )
        ]

    return str(value)


def _observation_document(
    observation: ExecutionObservation | None,
) -> dict[str, Any] | None:
    if observation is None:
        return None

    return {
        "ready": observation.ready,
        "health": observation.health.value,
        "message": observation.message,
    }


def _backend_status_document(
    status: BackendExecutionStatus,
) -> dict[str, Any]:
    return {
        "backend": status.backend,
        "executionId": status.execution_id,
        "state": status.state.value,
        "terminal": status.terminal,
        "successful": status.successful,
        "message": status.message,
        "details": _json_value(
            status.details
        ),
        "observation": (
            _observation_document(
                status.observation
            )
        ),
    }


def _scope_status_document(
    item: ScopeExecutionStatus,
) -> dict[str, Any]:
    return {
        "scope": {
            "id": item.scope.id,
            "target": item.scope.target,
            "backend": item.scope.backend,
        },
        "status": _backend_status_document(
            item.status
        ),
    }


def _child_status_document(
    item: ChildSystemExecutionStatus,
) -> dict[str, Any]:
    plan = getattr(
        item.instance,
        "plan",
        None,
    )
    definition = getattr(
        plan,
        "system",
        None,
    )

    return {
        "instance": {
            "name": item.name,
            "definition": (
                str(definition)
                if definition is not None
                else None
            ),
            "revision": item.revision,
            "ordinal": item.ordinal,
        },
        "status": (
            system_execution_status_to_canonical(
                item.status
            )
        ),
    }


def system_execution_status_to_canonical(
    status: SystemExecutionStatus,
) -> dict[str, Any]:
    """Serialize a complete hierarchical execution snapshot."""

    if not isinstance(
        status,
        SystemExecutionStatus,
    ):
        raise TypeError(
            "status must be a SystemExecutionStatus"
        )

    return {
        "executionId": status.execution_id,
        "state": status.state.value,
        "terminal": status.terminal,
        "successful": status.successful,
        "message": status.message,
        "details": _json_value(
            status.details
        ),
        "observation": (
            _observation_document(
                status.observation
            )
        ),
        "scopes": [
            _scope_status_document(item)
            for item in status.scopes
        ],
        "systems": [
            _child_status_document(item)
            for item in status.systems
        ],
    }


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    """One versioned event in the public System execution stream."""

    event: ExecutionEventKind
    system: str
    timestamp: datetime = field(
        default_factory=_utc_now
    )
    execution_id: str | None = None
    status: SystemExecutionStatus | None = None
    message: str | None = None
    details: Mapping[str, Any] = field(
        default_factory=dict
    )

    api_version: ClassVar[str] = (
        EXECUTION_EVENT_API_VERSION
    )
    kind: ClassVar[str] = (
        EXECUTION_EVENT_KIND
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.event,
            ExecutionEventKind,
        ):
            raise TypeError(
                "event must be an ExecutionEventKind"
            )

        if (
            not isinstance(self.system, str)
            or not self.system.strip()
        ):
            raise ValueError(
                "system must be a non-empty string"
            )

        if not isinstance(
            self.timestamp,
            datetime,
        ):
            raise TypeError(
                "timestamp must be a datetime"
            )

        if (
            self.timestamp.tzinfo is None
            or self.timestamp.utcoffset()
            is None
        ):
            raise ValueError(
                "timestamp must include timezone information"
            )

        if (
            self.execution_id is not None
            and (
                not isinstance(
                    self.execution_id,
                    str,
                )
                or not self.execution_id.strip()
            )
        ):
            raise ValueError(
                "execution_id must be a non-empty string or None"
            )

        if (
            self.status is not None
            and not isinstance(
                self.status,
                SystemExecutionStatus,
            )
        ):
            raise TypeError(
                "status must be a SystemExecutionStatus or None"
            )

        if (
            self.message is not None
            and (
                not isinstance(
                    self.message,
                    str,
                )
                or not self.message.strip()
            )
        ):
            raise ValueError(
                "message must be a non-empty string or None"
            )

        if not isinstance(
            self.details,
            Mapping,
        ):
            raise TypeError(
                "details must be a mapping"
            )

        object.__setattr__(
            self,
            "system",
            self.system.strip(),
        )
        object.__setattr__(
            self,
            "details",
            dict(self.details),
        )

        if (
            self.status is not None
            and self.execution_id is not None
            and (
                self.status.execution_id
                != self.execution_id
            )
        ):
            raise ValueError(
                "execution_id does not match status.execution_id"
            )

        if (
            self.event
            in {
                ExecutionEventKind.SNAPSHOT,
                ExecutionEventKind.FINISHED,
            }
            and self.status is None
        ):
            raise ValueError(
                f"{self.event.value} events require status"
            )

        if (
            self.event
            is ExecutionEventKind.FINISHED
            and self.status is not None
            and not self.status.terminal
        ):
            raise ValueError(
                "finished events require terminal status"
            )

        if (
            self.event
            in {
                ExecutionEventKind.STARTED,
                ExecutionEventKind.STOPPING,
            }
            and self.resolved_execution_id
            is None
        ):
            raise ValueError(
                f"{self.event.value} events require execution_id"
            )

    @property
    def resolved_execution_id(
        self,
    ) -> str | None:
        if self.execution_id is not None:
            return self.execution_id

        if self.status is not None:
            return self.status.execution_id

        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "event": self.event.value,
            "timestamp": _timestamp_text(
                self.timestamp
            ),
            "system": self.system,
            "executionId": (
                self.resolved_execution_id
            ),
            "message": self.message,
            "details": _json_value(
                self.details
            ),
            "status": (
                system_execution_status_to_canonical(
                    self.status
                )
                if self.status is not None
                else None
            ),
        }


def dumps_execution_event(
    event: ExecutionEvent,
) -> str:
    """Return one compact JSONL-compatible execution event."""

    if not isinstance(
        event,
        ExecutionEvent,
    ):
        raise TypeError(
            "event must be an ExecutionEvent"
        )

    return json.dumps(
        event.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
