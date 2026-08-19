"""Append-only persistent event journal for Nodrix Runs.

The journal is execution-domain neutral.

Each line wraps one already-versioned domain event with Run identity and a
strictly increasing sequence number:

    RunEventRecord
        -> runId
        -> sequence
        -> recordedAt
        -> event

The nested event remains owned by its execution domain.  For example, System
execution currently uses ``nodrix.execution.event/v1``.  Workflow, benchmark,
test and future custom domains may use their own versioned event contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from nodrix.run_session import RunSession


RUN_EVENT_RECORD_API_VERSION = (
    "nodrix.run-event-record/v1"
)
RUN_EVENT_RECORD_KIND = "RunEventRecord"


class RunEventJournalError(RuntimeError):
    """Base error for persistent Run event journals."""


class RunEventJournalCorruptionError(
    RunEventJournalError
):
    """Raised when an existing journal violates the Run event contract."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(
    value: datetime,
    *,
    field_name: str,
) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field_name} must be a datetime"
        )

    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )

    return value.astimezone(timezone.utc)


def _timestamp_text(
    value: datetime,
) -> str:
    return (
        value.isoformat(
            timespec="microseconds"
        )
        .replace("+00:00", "Z")
    )


def _versioned_event(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(
            "event must be a mapping"
        )

    document = dict(value)

    api_version = document.get(
        "apiVersion"
    )
    kind = document.get(
        "kind"
    )

    if (
        not isinstance(api_version, str)
        or not api_version.strip()
    ):
        raise ValueError(
            "event.apiVersion must be a non-empty string"
        )

    if (
        not isinstance(kind, str)
        or not kind.strip()
    ):
        raise ValueError(
            "event.kind must be a non-empty string"
        )

    # Validate the complete nested payload before any filesystem write.
    try:
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "event must contain only finite "
            "JSON-compatible values"
        ) from exc

    return document


class RunEventJournal:
    """Single-writer append-only JSONL journal for one Run.

    The journal is intentionally small and synchronous.  It is designed for
    lifecycle/control-plane events, not high-frequency telemetry or logs.

    Every successful append is flushed and fsynced before the sequence advances.
    This favors durable recovery semantics.  A future observability policy may
    provide other durability modes for non-critical telemetry without changing
    this core event contract.
    """

    def __init__(
        self,
        session: RunSession,
    ) -> None:
        if not isinstance(
            session,
            RunSession,
        ):
            raise TypeError(
                "session must be a RunSession"
            )

        self._session = session
        self._lock = Lock()
        self._next_sequence = (
            self._recover_next_sequence()
        )

    @property
    def run_id(self) -> str:
        return self._session.run_id

    @property
    def path(self) -> Path:
        return (
            self._session.directory
            / "events.jsonl"
        )

    @property
    def next_sequence(self) -> int:
        return self._next_sequence

    def _recover_next_sequence(
        self,
    ) -> int:
        path = self.path

        if not path.exists():
            return 1

        if not path.is_file():
            raise RunEventJournalCorruptionError(
                "events.jsonl exists but is not a file"
            )

        expected = 1

        with path.open(
            "rb",
        ) as stream:
            while True:
                raw = stream.readline()

                if not raw:
                    break

                if not raw.endswith(
                    b"\n"
                ):
                    raise RunEventJournalCorruptionError(
                        "events.jsonl contains an incomplete "
                        "final record"
                    )

                try:
                    document = json.loads(
                        raw.decode("utf-8")
                    )
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ) as exc:
                    raise RunEventJournalCorruptionError(
                        "events.jsonl contains an invalid "
                        "JSON record"
                    ) from exc

                if not isinstance(
                    document,
                    dict,
                ):
                    raise RunEventJournalCorruptionError(
                        "Run event record must be a JSON object"
                    )

                if (
                    document.get("apiVersion")
                    != RUN_EVENT_RECORD_API_VERSION
                ):
                    raise RunEventJournalCorruptionError(
                        "unsupported Run event record apiVersion"
                    )

                if (
                    document.get("kind")
                    != RUN_EVENT_RECORD_KIND
                ):
                    raise RunEventJournalCorruptionError(
                        "invalid Run event record kind"
                    )

                if (
                    document.get("runId")
                    != self.run_id
                ):
                    raise RunEventJournalCorruptionError(
                        "Run event record belongs to a "
                        "different Run"
                    )

                if (
                    document.get("sequence")
                    != expected
                ):
                    raise RunEventJournalCorruptionError(
                        "Run event sequence is not contiguous"
                    )

                event = document.get(
                    "event"
                )

                if not isinstance(
                    event,
                    dict,
                ):
                    raise RunEventJournalCorruptionError(
                        "Run event record has no event object"
                    )

                try:
                    _versioned_event(
                        event
                    )
                except (
                    TypeError,
                    ValueError,
                ) as exc:
                    raise RunEventJournalCorruptionError(
                        "Run event record contains an invalid "
                        "versioned domain event"
                    ) from exc

                expected += 1

        return expected

    def append(
        self,
        event: Mapping[str, Any],
        *,
        recorded_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Durably append one versioned domain event."""

        nested_event = _versioned_event(
            event
        )

        timestamp = _timestamp(
            (
                _utc_now()
                if recorded_at is None
                else recorded_at
            ),
            field_name="recorded_at",
        )

        with self._lock:
            sequence = (
                self._next_sequence
            )

            record = {
                "apiVersion": (
                    RUN_EVENT_RECORD_API_VERSION
                ),
                "kind": (
                    RUN_EVENT_RECORD_KIND
                ),
                "runId": self.run_id,
                "sequence": sequence,
                "recordedAt": (
                    _timestamp_text(
                        timestamp
                    )
                ),
                "event": nested_event,
            }

            encoded = (
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")

            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with self.path.open(
                "ab",
                buffering=0,
            ) as stream:
                stream.write(
                    encoded
                )
                os.fsync(
                    stream.fileno()
                )

            self._next_sequence += 1

            return record

    def read_all(
        self,
    ) -> tuple[dict[str, Any], ...]:
        """Read and validate all persisted event records."""

        if not self.path.exists():
            return ()

        # Re-run the structural recovery check before exposing historical data.
        self._recover_next_sequence()

        records: list[
            dict[str, Any]
        ] = []

        with self.path.open(
            "r",
            encoding="utf-8",
        ) as stream:
            for line in stream:
                records.append(
                    json.loads(line)
                )

        return tuple(records)


__all__ = [
    "RUN_EVENT_RECORD_API_VERSION",
    "RUN_EVENT_RECORD_KIND",
    "RunEventJournal",
    "RunEventJournalCorruptionError",
    "RunEventJournalError",
]
