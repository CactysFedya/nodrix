"""Atomic live status snapshots for persistent Nodrix Runs.

``status.json`` is mutable operational state.

It is deliberately different from ``events.jsonl``:

- events are append-only historical evidence;
- status is one replaceable snapshot optimized for fast reads;
- status corruption/loss must never rewrite historical events;
- execution-domain-specific details remain nested data rather than becoming
  part of the Run storage contract.

The status file is written through a temporary file in the same directory and
atomically replaced with ``os.replace``.  Readers therefore observe either the
previous complete snapshot or the new complete snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
from threading import RLock
import tempfile
from typing import Any, Mapping

from nodrix.model import ExecutionState
from nodrix.run_session import RunSession


RUN_STATUS_API_VERSION = "nodrix.run-status/v1"
RUN_STATUS_KIND = "RunStatus"


class RunStatusError(RuntimeError):
    """Base error for persistent Run status snapshots."""


class RunStatusCorruptionError(
    RunStatusError
):
    """Raised when an existing status.json violates the Run status contract."""


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _timestamp(
    value: datetime,
    *,
    field_name: str,
) -> datetime:
    if not isinstance(
        value,
        datetime,
    ):
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

    return value.astimezone(
        timezone.utc
    )


def _timestamp_text(
    value: datetime,
) -> str:
    return (
        value.isoformat(
            timespec="microseconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


def _reject_json_constant(
    value: str,
) -> None:
    raise json.JSONDecodeError(
        "non-standard JSON numeric constant "
        f"{value!r}",
        value,
        0,
    )


def _parse_persisted_timestamp(
    value: object,
    *,
    field_name: str,
) -> datetime:
    if not isinstance(
        value,
        str,
    ):
        raise RunStatusCorruptionError(
            f"{field_name} must be a string"
        )

    candidate = (
        value[:-1] + "+00:00"
        if value.endswith("Z")
        else value
    )

    try:
        result = datetime.fromisoformat(
            candidate
        )
    except ValueError as exc:
        raise RunStatusCorruptionError(
            f"{field_name} is invalid"
        ) from exc

    if (
        result.tzinfo is None
        or result.utcoffset() is None
    ):
        raise RunStatusCorruptionError(
            f"{field_name} must be timezone-aware"
        )

    return result


def _json_value(
    value: Any,
) -> Any:
    """Normalize status details to deterministic JSON-compatible data."""

    if isinstance(
        value,
        Enum,
    ):
        return value.value

    if isinstance(
        value,
        datetime,
    ):
        return _timestamp_text(
            _timestamp(
                value,
                field_name="status datetime",
            )
        )

    if isinstance(
        value,
        Path,
    ):
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

    if isinstance(
        value,
        float,
    ):
        if not math.isfinite(
            value
        ):
            raise ValueError(
                "status details cannot contain "
                "non-finite floats"
            )

        return value

    if isinstance(
        value,
        Mapping,
    ):
        result: dict[
            str,
            Any,
        ] = {}

        for key, item in value.items():
            if not isinstance(
                key,
                str,
            ):
                raise TypeError(
                    "status detail keys must be strings"
                )

            result[key] = (
                _json_value(
                    item
                )
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
            _json_value(
                item
            )
            for item in value
        ]

    raise TypeError(
        "status details contain unsupported "
        f"value {type(value).__name__}"
    )


def _required_text(
    value: str,
    *,
    field_name: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            f"{field_name} must be a string"
        )

    normalized = (
        value.strip()
    )

    if not normalized:
        raise ValueError(
            f"{field_name} must be non-empty"
        )

    return normalized


def _optional_text(
    value: str | None,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    return _required_text(
        value,
        field_name=field_name,
    )


def _validate_existing_document(
    document: Any,
    *,
    session: RunSession,
) -> int:
    if not isinstance(
        document,
        dict,
    ):
        raise RunStatusCorruptionError(
            "status.json must contain a JSON object"
        )

    if (
        document.get(
            "apiVersion"
        )
        != RUN_STATUS_API_VERSION
    ):
        raise RunStatusCorruptionError(
            "unsupported status.json apiVersion"
        )

    if (
        document.get("kind")
        != RUN_STATUS_KIND
    ):
        raise RunStatusCorruptionError(
            "invalid status.json kind"
        )

    if (
        document.get("runId")
        != session.run_id
    ):
        raise RunStatusCorruptionError(
            "status.json belongs to a different Run"
        )

    if (
        document.get("planId")
        != session.plan_id
    ):
        raise RunStatusCorruptionError(
            "status.json belongs to a different Plan"
        )

    generation = document.get(
        "generation"
    )

    if (
        not isinstance(
            generation,
            int,
        )
        or isinstance(
            generation,
            bool,
        )
        or generation < 1
    ):
        raise RunStatusCorruptionError(
            "status.json generation must be "
            "a positive integer"
        )

    state_value = document.get(
        "state"
    )

    try:
        state = (
            ExecutionState.parse(
                state_value
            )
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise RunStatusCorruptionError(
            "status.json contains an invalid state"
        ) from exc

    if (
        document.get("terminal")
        is not state.terminal
    ):
        raise RunStatusCorruptionError(
            "status.json terminal flag does not "
            "match state"
        )

    if (
        document.get("successful")
        is not state.successful
    ):
        raise RunStatusCorruptionError(
            "status.json successful flag does not "
            "match state"
        )

    execution_id = document.get(
        "executionId"
    )

    if (
        execution_id is not None
        and (
            not isinstance(
                execution_id,
                str,
            )
            or not execution_id.strip()
        )
    ):
        raise RunStatusCorruptionError(
            "status.json executionId must be "
            "a non-empty string or null"
        )

    updated_at = document.get(
        "updatedAt"
    )

    if (
        not isinstance(
            updated_at,
            str,
        )
        or not updated_at.strip()
    ):
        raise RunStatusCorruptionError(
            "status.json updatedAt must be "
            "a non-empty string"
        )

    message = document.get(
        "message"
    )

    if (
        message is not None
        and (
            not isinstance(
                message,
                str,
            )
            or not message.strip()
        )
    ):
        raise RunStatusCorruptionError(
            "status.json message must be "
            "a non-empty string or null"
        )

    details = document.get(
        "details"
    )

    if not isinstance(
        details,
        dict,
    ):
        raise RunStatusCorruptionError(
            "status.json details must be an object"
        )

    return generation


class RunStatusStore:
    """Atomic mutable status storage for one persistent Run."""

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

        self._session = (
            session
        )
        self._lock = RLock()

        self._last_document = (
            self._read_document()
        )

        if self._last_document is None:
            self._next_generation = 1
        else:
            self._next_generation = (
                _validate_existing_document(
                    self._last_document,
                    session=self._session,
                )
                + 1
            )

    @property
    def run_id(self) -> str:
        return (
            self._session.run_id
        )

    @property
    def path(self) -> Path:
        return (
            self._session.directory
            / "status.json"
        )

    @property
    def next_generation(
        self,
    ) -> int:
        return (
            self._next_generation
        )

    def _read_document(
        self,
    ) -> dict[str, Any] | None:
        if not self.path.exists():
            return None

        if not self.path.is_file():
            raise RunStatusCorruptionError(
                "status.json exists but is not a file"
            )

        try:
            with self.path.open(
                "r",
                encoding="utf-8",
            ) as stream:
                document = json.load(stream, parse_constant=_reject_json_constant)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RunStatusCorruptionError(
                "status.json contains invalid JSON"
            ) from exc

        _validate_existing_document(
            document,
            session=self._session,
        )

        _parse_persisted_timestamp(
            document.get("updatedAt"),
            field_name=(
                "status.json updatedAt"
            ),
        )

        return document

    def read(
        self,
    ) -> dict[str, Any] | None:
        """Return the current complete status snapshot."""

        return self._read_document()

    def write_if_changed(
        self,
        *,
        state: ExecutionState | str,
        execution_id: str | None = None,
        message: str | None = None,
        details: Mapping[str, Any] | None = None,
        updated_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Write only when the observable status actually changed.

        ``updatedAt`` therefore represents the latest persisted semantic
        status change rather than the latest polling time.  This avoids
        unnecessary filesystem writes on low-resource targets.
        """

        canonical_state = (
            ExecutionState.parse(
                state
            )
        )

        canonical_execution_id = (
            _optional_text(
                execution_id,
                field_name="execution_id",
            )
        )

        canonical_message = (
            _optional_text(
                message,
                field_name="message",
            )
        )

        if details is None:
            canonical_details: dict[
                str,
                Any,
            ] = {}
        else:
            if not isinstance(
                details,
                Mapping,
            ):
                raise TypeError(
                    "details must be a mapping or None"
                )

            canonical_details = (
                _json_value(
                    details
                )
            )

        with self._lock:
            current = (
                self._last_document
            )

            if (
                current is not None
                and current.get(
                    "executionId"
                )
                == canonical_execution_id
                and current.get(
                    "state"
                )
                == canonical_state.value
                and current.get(
                    "message"
                )
                == canonical_message
                and current.get(
                    "details"
                )
                == canonical_details
            ):
                # Return an independent JSON value so callers cannot mutate
                # the in-memory comparison snapshot.
                return json.loads(
                    json.dumps(
                        current,
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                )

            return self.write(
                state=canonical_state,
                execution_id=(
                    canonical_execution_id
                ),
                message=(
                    canonical_message
                ),
                details=(
                    canonical_details
                ),
                updated_at=updated_at,
            )

    def write(
        self,
        *,
        state: ExecutionState | str,
        execution_id: str | None = None,
        message: str | None = None,
        details: Mapping[str, Any] | None = None,
        updated_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically replace status.json with one new snapshot."""

        canonical_state = (
            ExecutionState.parse(
                state
            )
        )

        canonical_execution_id = (
            _optional_text(
                execution_id,
                field_name="execution_id",
            )
        )

        canonical_message = (
            _optional_text(
                message,
                field_name="message",
            )
        )

        if details is None:
            canonical_details: dict[
                str,
                Any,
            ] = {}
        else:
            if not isinstance(
                details,
                Mapping,
            ):
                raise TypeError(
                    "details must be a mapping or None"
                )

            canonical_details = (
                _json_value(
                    details
                )
            )

        timestamp = _timestamp(
            (
                _utc_now()
                if updated_at is None
                else updated_at
            ),
            field_name="updated_at",
        )

        with self._lock:
            generation = (
                self._next_generation
            )

            document = {
                "apiVersion": (
                    RUN_STATUS_API_VERSION
                ),
                "kind": (
                    RUN_STATUS_KIND
                ),
                "runId": (
                    self._session.run_id
                ),
                "planId": (
                    self._session.plan_id
                ),
                "generation": generation,
                "updatedAt": (
                    _timestamp_text(
                        timestamp
                    )
                ),
                "executionId": (
                    canonical_execution_id
                ),
                "state": (
                    canonical_state.value
                ),
                "terminal": (
                    canonical_state.terminal
                ),
                "successful": (
                    canonical_state.successful
                ),
                "message": (
                    canonical_message
                ),
                "details": (
                    canonical_details
                ),
            }

            # Validate serialization before allocating a temporary file.
            encoded = (
                json.dumps(
                    document,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            )

            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            temporary_path: Path | None = None

            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=".status.",
                    suffix=".tmp",
                    delete=False,
                ) as stream:
                    temporary_path = Path(
                        stream.name
                    )

                    stream.write(
                        encoded
                    )

                    # Closing the temporary file before os.replace is enough
                    # for atomic reader semantics.  status.json is
                    # reconstructible live state; unlike events.jsonl, it does
                    # not pay an fsync cost on every update.

                os.replace(
                    temporary_path,
                    self.path,
                )
            except Exception:
                if (
                    temporary_path
                    is not None
                ):
                    try:
                        temporary_path.unlink(
                            missing_ok=True
                        )
                    except OSError:
                        pass

                raise

            self._next_generation += 1

            # Keep a private immutable-by-convention copy for cheap
            # write_if_changed comparisons without rereading the filesystem.
            self._last_document = (
                json.loads(
                    encoded
                )
            )

            return document


__all__ = [
    "RUN_STATUS_API_VERSION",
    "RUN_STATUS_KIND",
    "RunStatusCorruptionError",
    "RunStatusError",
    "RunStatusStore",
]
