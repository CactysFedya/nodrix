"""Bounded best-effort diagnostic logs for persistent Nodrix Runs.

Logs are deliberately distinct from Events.

Events represent durable control-plane facts required to reconstruct a Run
lifecycle. Logs are optional diagnostic information and therefore must never
control execution merely because log storage is unavailable or full.

Design goals:

- disabled by default;
- structured JSONL;
- category hierarchy;
- severity filtering;
- category filtering;
- shared redaction;
- bounded total/category/record sizes;
- explicit drop/stop-capture overflow behavior;
- no fsync on every log record;
- filesystem failures become counters, not execution failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping

from nodrix.redaction import (
    RedactionPolicy,
)
from nodrix.run_session import (
    RunSession,
)


RUN_LOG_RECORD_API_VERSION = (
    "nodrix.run-log-record/v1"
)

RUN_LOG_RECORD_KIND = "RunLogRecord"


_LEVELS = {
    "trace": 10,
    "debug": 20,
    "info": 30,
    "warning": 40,
    "error": 50,
    "critical": 60,
}

_CATEGORY_SEGMENT_RE = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}$"
)

_OVERFLOW_POLICIES = {
    "drop",
    "stop_capture",
}


def _level(
    value: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            "log level must be a string"
        )

    normalized = (
        value.strip().lower()
    )

    if normalized not in _LEVELS:
        raise ValueError(
            "unsupported log level "
            f"{value!r}; expected one of: "
            + ", ".join(_LEVELS)
        )

    return normalized


def _category(
    value: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            "log category must be a string"
        )

    normalized = (
        value.strip().lower()
    )

    if not normalized:
        raise ValueError(
            "log category must be non-empty"
        )

    parts = normalized.split(".")

    if any(
        not _CATEGORY_SEGMENT_RE.fullmatch(
            part
        )
        for part in parts
    ):
        raise ValueError(
            "log category must contain dot-separated "
            "lowercase identifier segments"
        )

    return normalized


def _timestamp_text(
    value: datetime,
) -> str:
    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(
            "recorded_at must be a datetime"
        )

    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            "recorded_at must be timezone-aware"
        )

    return (
        value
        .astimezone(timezone.utc)
        .isoformat(
            timespec="microseconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


@dataclass(frozen=True, slots=True)
class RunLogPolicy:
    """Bounded diagnostic logging policy for one Run."""

    enabled: bool = False
    min_level: str = "warning"
    categories: tuple[str, ...] = ()
    max_bytes: int = 4 * 1024 * 1024
    max_category_bytes: int = 1024 * 1024
    max_record_bytes: int = 64 * 1024
    overflow: str = "drop"
    redaction: RedactionPolicy = field(
        default_factory=RedactionPolicy
    )

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.enabled,
            bool,
        ):
            raise TypeError(
                "log enabled must be a bool"
            )

        canonical_level = _level(
            self.min_level
        )

        categories: list[str] = []

        for value in self.categories:
            canonical = _category(
                value
            )

            if canonical not in categories:
                categories.append(
                    canonical
                )

        categories.sort()

        for field_name in (
            "max_bytes",
            "max_category_bytes",
            "max_record_bytes",
        ):
            value = getattr(
                self,
                field_name,
            )

            if (
                not isinstance(
                    value,
                    int,
                )
                or isinstance(
                    value,
                    bool,
                )
                or value <= 0
            ):
                raise ValueError(
                    f"{field_name} must be "
                    "a positive integer"
                )

        if (
            self.max_category_bytes
            > self.max_bytes
        ):
            raise ValueError(
                "max_category_bytes cannot "
                "exceed max_bytes"
            )

        if (
            self.max_record_bytes
            > self.max_category_bytes
        ):
            raise ValueError(
                "max_record_bytes cannot exceed "
                "max_category_bytes"
            )

        if not isinstance(
            self.overflow,
            str,
        ):
            raise TypeError(
                "log overflow policy must be a string"
            )

        overflow = (
            self.overflow
            .strip()
            .lower()
        )

        if (
            overflow
            not in _OVERFLOW_POLICIES
        ):
            raise ValueError(
                "unsupported log overflow policy "
                f"{self.overflow!r}"
            )

        if not isinstance(
            self.redaction,
            RedactionPolicy,
        ):
            raise TypeError(
                "redaction must be a RedactionPolicy"
            )

        object.__setattr__(
            self,
            "min_level",
            canonical_level,
        )

        object.__setattr__(
            self,
            "categories",
            tuple(categories),
        )

        object.__setattr__(
            self,
            "overflow",
            overflow,
        )


class RunLogStore:
    """Best-effort bounded structured logging for one persistent Run."""

    def __init__(
        self,
        session: RunSession,
        *,
        policy: RunLogPolicy | None = None,
    ) -> None:
        if not isinstance(
            session,
            RunSession,
        ):
            raise TypeError(
                "session must be a RunSession"
            )

        if policy is None:
            policy = RunLogPolicy()

        if not isinstance(
            policy,
            RunLogPolicy,
        ):
            raise TypeError(
                "policy must be a RunLogPolicy or None"
            )

        self._session = session
        self._policy = policy
        self._lock = RLock()

        self._records_written = 0
        self._bytes_written = 0

        self._records_filtered = 0

        self._records_dropped = 0
        self._bytes_dropped = 0

        self._persistence_errors: list[str] = []

        self._capture_stopped = False

        self._category_bytes: dict[
            str,
            int,
        ] = {}

        self._recover_existing_usage()

    @property
    def run_id(self) -> str:
        return self._session.run_id

    @property
    def plan_id(self) -> str:
        return self._session.plan_id

    @property
    def policy(self) -> RunLogPolicy:
        return self._policy

    @property
    def root(self) -> Path:
        return (
            self._session.directory
            / "logs"
        )

    def path(
        self,
        category: str,
    ) -> Path:
        canonical = _category(
            category
        )

        parts = canonical.split(".")

        return (
            self.root
            .joinpath(
                *parts[:-1]
            )
            / (
                parts[-1]
                + ".jsonl"
            )
        )

    def _recover_existing_usage(
        self,
    ) -> None:
        if not self.root.exists():
            return

        for path in self.root.rglob(
            "*.jsonl"
        ):
            if not path.is_file():
                continue

            try:
                size = (
                    path.stat().st_size
                )
            except OSError:
                continue

            relative = (
                path.relative_to(
                    self.root
                )
            )

            category_parts = list(
                relative.parts
            )

            category_parts[-1] = (
                Path(
                    category_parts[-1]
                ).stem
            )

            category = ".".join(
                category_parts
            )

            try:
                canonical = _category(
                    category
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            self._category_bytes[
                canonical
            ] = (
                self._category_bytes.get(
                    canonical,
                    0,
                )
                + size
            )

            self._bytes_written += (
                size
            )

    def _category_enabled(
        self,
        category: str,
    ) -> bool:
        allowed = (
            self._policy.categories
        )

        if not allowed:
            return True

        return any(
            (
                category == prefix
                or category.startswith(
                    prefix + "."
                )
            )
            for prefix in allowed
        )

    def _record_drop(
        self,
        byte_count: int,
    ) -> None:
        self._records_dropped += 1
        self._bytes_dropped += (
            byte_count
        )

        if (
            self._policy.overflow
            == "stop_capture"
        ):
            self._capture_stopped = (
                True
            )

    def _record_persistence_error(
        self,
        exc: OSError,
    ) -> None:
        error = (
            f"{type(exc).__name__}: {exc}"
        )

        if (
            not self._persistence_errors
            or self._persistence_errors[-1]
            != error
        ):
            self._persistence_errors.append(
                error
            )

    def _append(
        self,
        path: Path,
        encoded: bytes,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        descriptor = os.open(
            path,
            (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_APPEND
            ),
            0o600,
        )

        try:
            written = os.write(
                descriptor,
                encoded,
            )
        finally:
            os.close(
                descriptor
            )

        if written != len(
            encoded
        ):
            raise OSError(
                "short Run log write"
            )

    def write(
        self,
        category: str,
        level: str,
        message: str,
        *,
        fields: Mapping[str, Any] | None = None,
        recorded_at: datetime | None = None,
    ) -> bool:
        """Write one diagnostic record.

        Returns ``True`` only when the record reached log storage.

        Policy filtering, quota overflow, stopped capture and filesystem
        failures return ``False``.  Those conditions never control execution.
        """

        canonical_category = (
            _category(
                category
            )
        )

        canonical_level = _level(
            level
        )

        if not isinstance(
            message,
            str,
        ):
            raise TypeError(
                "log message must be a string"
            )

        if (
            fields is not None
            and not isinstance(
                fields,
                Mapping,
            )
        ):
            raise TypeError(
                "log fields must be a mapping or None"
            )

        timestamp = (
            datetime.now(
                timezone.utc
            )
            if recorded_at is None
            else recorded_at
        )

        timestamp_text = (
            _timestamp_text(
                timestamp
            )
        )

        with self._lock:
            if not self._policy.enabled:
                self._records_filtered += 1
                return False

            if self._capture_stopped:
                self._records_dropped += 1
                return False

            if (
                _LEVELS[
                    canonical_level
                ]
                < _LEVELS[
                    self._policy.min_level
                ]
            ):
                self._records_filtered += 1
                return False

            if not self._category_enabled(
                canonical_category
            ):
                self._records_filtered += 1
                return False

            redacted_message = (
                self._policy
                .redaction
                .redact_text(
                    message
                )
            )

            redacted_fields = (
                {}
                if fields is None
                else (
                    self._policy
                    .redaction
                    .redact(
                        fields
                    )
                )
            )

            if not isinstance(
                redacted_fields,
                Mapping,
            ):
                raise TypeError(
                    "redacted log fields must "
                    "be a mapping"
                )

            document = {
                "apiVersion": (
                    RUN_LOG_RECORD_API_VERSION
                ),
                "kind": (
                    RUN_LOG_RECORD_KIND
                ),
                "runId": self.run_id,
                "planId": self.plan_id,
                "recordedAt": (
                    timestamp_text
                ),
                "category": (
                    canonical_category
                ),
                "level": (
                    canonical_level
                ),
                "message": (
                    redacted_message
                ),
                "fields": dict(
                    redacted_fields
                ),
            }

            try:
                encoded = (
                    json.dumps(
                        document,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(
                            ",",
                            ":",
                        ),
                        allow_nan=False,
                    )
                    + "\n"
                ).encode(
                    "utf-8"
                )
            except (
                TypeError,
                ValueError,
            ) as exc:
                raise ValueError(
                    "log record must contain "
                    "finite JSON-compatible values"
                ) from exc

            byte_count = len(
                encoded
            )

            category_bytes = (
                self._category_bytes.get(
                    canonical_category,
                    0,
                )
            )

            if (
                byte_count
                > self._policy.max_record_bytes
                or (
                    self._bytes_written
                    + byte_count
                    > self._policy.max_bytes
                )
                or (
                    category_bytes
                    + byte_count
                    > self._policy.max_category_bytes
                )
            ):
                self._record_drop(
                    byte_count
                )
                return False

            path = self.path(
                canonical_category
            )

            try:
                self._append(
                    path,
                    encoded,
                )
            except OSError as exc:
                self._record_persistence_error(
                    exc
                )
                self._records_dropped += 1
                self._bytes_dropped += (
                    byte_count
                )
                return False

            self._records_written += 1
            self._bytes_written += (
                byte_count
            )

            self._category_bytes[
                canonical_category
            ] = (
                category_bytes
                + byte_count
            )

            return True

    def stats(
        self,
    ) -> dict[str, Any]:
        """Return current in-memory diagnostic logging counters."""

        with self._lock:
            return {
                "enabled": (
                    self._policy.enabled
                ),
                "recordsWritten": (
                    self._records_written
                ),
                "bytesWritten": (
                    self._bytes_written
                ),
                "recordsFiltered": (
                    self._records_filtered
                ),
                "recordsDropped": (
                    self._records_dropped
                ),
                "bytesDropped": (
                    self._bytes_dropped
                ),
                "captureStopped": (
                    self._capture_stopped
                ),
                "categoryBytes": dict(
                    sorted(
                        self._category_bytes.items()
                    )
                ),
                "persistenceErrors": tuple(
                    self._persistence_errors
                ),
            }


__all__ = [
    "RUN_LOG_RECORD_API_VERSION",
    "RUN_LOG_RECORD_KIND",
    "RunLogPolicy",
    "RunLogStore",
]
