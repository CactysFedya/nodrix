"""Canonical append-only Metric journal for Nodrix Runs.

Canonical Metrics are deliberately separate from the legacy runtime telemetry
snapshot stream written by ``nodrix.metrics.MetricsRecorder``.

Legacy runtime telemetry:
    <legacy-run>/metrics.jsonl

Canonical typed Run Metrics:
    <canonical-run>/metrics/records.jsonl

The nested MetricRecord remains Run-neutral.  RunMetricRecord adds only
persistent Run identity, ordering and journal recording time.

Metrics are optional observability.  Absence of this journal is valid and does
not make a Run incomplete.

This module deliberately does not define retention, quotas, drop policy,
aggregation, Prometheus export or SDK publication.  Those belong to outer
observability layers.
"""

from __future__ import annotations

from .metric_publisher import (
    MetricPublishResult,
)

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from .model import (
    MetricDescriptor,
    MetricRecord,
)
from .run_metric_policy import (
    RunMetricPolicy,
)
from .run_session import RunSession


RUN_METRIC_RECORD_API_VERSION = (
    "nodrix.run-metric-record/v1"
)
RUN_METRIC_RECORD_KIND = "RunMetricRecord"

RUN_METRIC_STATUS_API_VERSION = (
    "nodrix.run-metric-status/v1"
)
RUN_METRIC_STATUS_KIND = "RunMetricStatus"


class RunMetricJournalError(RuntimeError):
    """Base error for persistent canonical Run Metric journals."""


class RunMetricJournalCorruptionError(
    RunMetricJournalError
):
    """Raised when existing Run Metric history violates its contract."""


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

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must be non-empty"
        )

    return normalized


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
        _timestamp(
            value,
            field_name="timestamp",
        )
        .isoformat(
            timespec="microseconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


def _timestamp_from_text(
    value: object,
    *,
    field_name: str,
) -> datetime:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            f"{field_name} must be a string"
        )

    text = value.strip()

    if not text:
        raise ValueError(
            f"{field_name} must be non-empty"
        )

    try:
        parsed = datetime.fromisoformat(
            (
                text[:-1]
                + "+00:00"
                if text.endswith("Z")
                else text
            )
        )
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc

    return _timestamp(
        parsed,
        field_name=field_name,
    )


def _positive_sequence(
    value: object,
) -> int:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
    ):
        raise TypeError(
            "Run Metric sequence must be an integer"
        )

    if value < 1:
        raise ValueError(
            "Run Metric sequence must be positive"
        )

    return value


def _exact_fields(
    document: Mapping[str, Any],
    *,
    expected: set[str],
    label: str,
) -> None:
    actual = set(
        document
    )

    if actual != expected:
        missing = sorted(
            expected - actual
        )
        extra = sorted(
            actual - expected
        )

        raise ValueError(
            f"{label} has invalid fields; "
            f"missing={missing}, extra={extra}"
        )


def _metric_document(
    metric: MetricRecord,
) -> dict[str, Any]:
    if not isinstance(
        metric,
        MetricRecord,
    ):
        raise TypeError(
            "metric must be a MetricRecord"
        )

    descriptor = (
        metric.descriptor
    )

    return {
        "descriptor": {
            "descriptorId": (
                descriptor.descriptor_id
            ),
            "name": descriptor.name,
            "valueType": (
                descriptor.value_type.value
            ),
            "unit": descriptor.unit,
            "description": (
                descriptor.description
            ),
        },
        "value": metric.value,
        "observedAt": _timestamp_text(
            metric.observed_at
        ),
        "source": metric.source,
        "attributes": dict(
            metric.attributes
        ),
    }


def _metric_from_document(
    value: object,
) -> MetricRecord:
    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            "metric must be a JSON object"
        )

    document = dict(
        value
    )

    _exact_fields(
        document,
        expected={
            "descriptor",
            "value",
            "observedAt",
            "source",
            "attributes",
        },
        label="metric",
    )

    raw_descriptor = document[
        "descriptor"
    ]

    if not isinstance(
        raw_descriptor,
        Mapping,
    ):
        raise TypeError(
            "metric.descriptor must be a JSON object"
        )

    descriptor_document = dict(
        raw_descriptor
    )

    _exact_fields(
        descriptor_document,
        expected={
            "descriptorId",
            "name",
            "valueType",
            "unit",
            "description",
        },
        label="metric.descriptor",
    )

    descriptor = MetricDescriptor(
        name=descriptor_document[
            "name"
        ],
        value_type=descriptor_document[
            "valueType"
        ],
        unit=descriptor_document[
            "unit"
        ],
        description=descriptor_document[
            "description"
        ],
    )

    descriptor_id = (
        descriptor_document[
            "descriptorId"
        ]
    )

    if not isinstance(
        descriptor_id,
        str,
    ):
        raise TypeError(
            "metric.descriptor.descriptorId "
            "must be a string"
        )

    if (
        descriptor_id
        != descriptor.descriptor_id
    ):
        raise ValueError(
            "metric descriptorId does not match "
            "the canonical descriptor identity"
        )

    attributes = document[
        "attributes"
    ]

    if not isinstance(
        attributes,
        Mapping,
    ):
        raise TypeError(
            "metric.attributes must be a JSON object"
        )

    source = document[
        "source"
    ]

    if (
        source is not None
        and not isinstance(
            source,
            str,
        )
    ):
        raise TypeError(
            "metric.source must be a string or null"
        )

    return MetricRecord(
        descriptor=descriptor,
        value=document[
            "value"
        ],
        observed_at=_timestamp_from_text(
            document[
                "observedAt"
            ],
            field_name=(
                "metric.observedAt"
            ),
        ),
        source=source,
        attributes=dict(
            attributes
        ),
    )


@dataclass(
    frozen=True,
    slots=True,
)
class RunMetricRecord:
    """Immutable persistent envelope for one Run-bound Metric observation."""

    run_id: str
    sequence: int
    recorded_at: datetime
    metric: MetricRecord

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "run_id",
            _required_text(
                self.run_id,
                field_name="run_id",
            ),
        )

        object.__setattr__(
            self,
            "sequence",
            _positive_sequence(
                self.sequence
            ),
        )

        object.__setattr__(
            self,
            "recorded_at",
            _timestamp(
                self.recorded_at,
                field_name="recorded_at",
            ),
        )

        if not isinstance(
            self.metric,
            MetricRecord,
        ):
            raise TypeError(
                "metric must be a MetricRecord"
            )

    def to_document(
        self,
    ) -> dict[str, Any]:
        """Return the strict versioned JSON representation."""

        return {
            "apiVersion": (
                RUN_METRIC_RECORD_API_VERSION
            ),
            "kind": (
                RUN_METRIC_RECORD_KIND
            ),
            "runId": self.run_id,
            "sequence": self.sequence,
            "recordedAt": (
                _timestamp_text(
                    self.recorded_at
                )
            ),
            "metric": (
                _metric_document(
                    self.metric
                )
            ),
        }

    @classmethod
    def from_document(
        cls,
        value: object,
    ) -> "RunMetricRecord":
        """Validate and reconstruct one persistent Run Metric record."""

        if not isinstance(
            value,
            Mapping,
        ):
            raise TypeError(
                "Run Metric record must be a JSON object"
            )

        document = dict(
            value
        )

        _exact_fields(
            document,
            expected={
                "apiVersion",
                "kind",
                "runId",
                "sequence",
                "recordedAt",
                "metric",
            },
            label="Run Metric record",
        )

        if (
            document[
                "apiVersion"
            ]
            != RUN_METRIC_RECORD_API_VERSION
        ):
            raise ValueError(
                "unsupported Run Metric record apiVersion"
            )

        if (
            document[
                "kind"
            ]
            != RUN_METRIC_RECORD_KIND
        ):
            raise ValueError(
                "invalid Run Metric record kind"
            )

        return cls(
            run_id=document[
                "runId"
            ],
            sequence=document[
                "sequence"
            ],
            recorded_at=_timestamp_from_text(
                document[
                    "recordedAt"
                ],
                field_name="recordedAt",
            ),
            metric=_metric_from_document(
                document[
                    "metric"
                ]
            ),
        )


class RunMetricJournal:
    """Append-only typed Metric journal for one canonical Run.

    The journal is optional and created lazily on first append.

    Writes are flushed to the operating system through normal file close/flush
    semantics but deliberately do not fsync each Metric sample.  Lifecycle
    Events have stronger durability requirements than potentially high-rate
    Metrics.

    Storage limits and explicit loss accounting are defined by the outer
    observability policy layer, not by this base journal contract.
    """

    def __init__(
        self,
        session: RunSession,
        *,
        policy: RunMetricPolicy | None = None,
    ) -> None:
        if not isinstance(
            session,
            RunSession,
        ):
            raise TypeError(
                "session must be a RunSession"
            )

        if policy is None:
            policy = RunMetricPolicy()

        if not isinstance(
            policy,
            RunMetricPolicy,
        ):
            raise TypeError(
                "policy must be a RunMetricPolicy or None"
            )

        self._session = session
        self._policy = policy
        self._lock = Lock()

        (
            self._next_sequence,
            _,
        ) = self._scan(
            collect=False
        )

        self._stored_records = (
            self._next_sequence - 1
        )

        self._stored_bytes = (
            self.path.stat().st_size
            if self.path.exists()
            else 0
        )

        self._dropped_records = 0
        self._dropped_bytes = 0
        self._last_drop_reason: str | None = None

        self._load_loss_status()

    @property
    def run_id(
        self,
    ) -> str:
        return self._session.run_id

    @property
    def directory(
        self,
    ) -> Path:
        return (
            self._session.directory
            / "metrics"
        )

    @property
    def path(
        self,
    ) -> Path:
        return (
            self.directory
            / "records.jsonl"
        )

    @property
    def next_sequence(
        self,
    ) -> int:
        return self._next_sequence

    @property
    def policy(
        self,
    ) -> RunMetricPolicy:
        return self._policy

    @property
    def status_path(
        self,
    ) -> Path:
        return (
            self.directory
            / "status.json"
        )

    @property
    def stored_records(
        self,
    ) -> int:
        return self._stored_records

    @property
    def stored_bytes(
        self,
    ) -> int:
        return self._stored_bytes

    @property
    def dropped_records(
        self,
    ) -> int:
        return self._dropped_records

    @property
    def dropped_bytes(
        self,
    ) -> int:
        return self._dropped_bytes

    @property
    def loss_occurred(
        self,
    ) -> bool:
        return self._dropped_records > 0

    @property
    def last_drop_reason(
        self,
    ) -> str | None:
        return self._last_drop_reason

    def _load_loss_status(
        self,
    ) -> None:
        """Recover persistent Metric-loss counters when present."""

        path = self.status_path

        if not path.exists():
            return

        if not path.is_file():
            raise RunMetricJournalCorruptionError(
                "metrics/status.json exists but is not a file"
            )

        try:
            document = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RunMetricJournalCorruptionError(
                "metrics/status.json contains invalid JSON"
            ) from exc

        if not isinstance(
            document,
            dict,
        ):
            raise RunMetricJournalCorruptionError(
                "metrics/status.json must contain a JSON object"
            )

        expected = {
            "apiVersion",
            "kind",
            "runId",
            "droppedRecords",
            "droppedBytes",
            "lossOccurred",
            "lastDropReason",
            "updatedAt",
        }

        if set(document) != expected:
            raise RunMetricJournalCorruptionError(
                "metrics/status.json has invalid fields"
            )

        if (
            document["apiVersion"]
            != RUN_METRIC_STATUS_API_VERSION
            or document["kind"]
            != RUN_METRIC_STATUS_KIND
        ):
            raise RunMetricJournalCorruptionError(
                "metrics/status.json has unsupported schema"
            )

        if (
            document["runId"]
            != self.run_id
        ):
            raise RunMetricJournalCorruptionError(
                "metrics/status.json belongs to a different Run"
            )

        dropped_records = document[
            "droppedRecords"
        ]
        dropped_bytes = document[
            "droppedBytes"
        ]

        for name, value in (
            (
                "droppedRecords",
                dropped_records,
            ),
            (
                "droppedBytes",
                dropped_bytes,
            ),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise RunMetricJournalCorruptionError(
                    f"metrics/status.json {name} "
                    "must be a non-negative integer"
                )

        if dropped_records < 1:
            raise RunMetricJournalCorruptionError(
                "metrics/status.json must describe "
                "at least one dropped Metric"
            )

        if document[
            "lossOccurred"
        ] is not True:
            raise RunMetricJournalCorruptionError(
                "metrics/status.json must declare lossOccurred=true"
            )

        reason = document[
            "lastDropReason"
        ]

        if (
            not isinstance(reason, str)
            or not reason.strip()
        ):
            raise RunMetricJournalCorruptionError(
                "metrics/status.json lastDropReason "
                "must be non-empty"
            )

        try:
            _timestamp_from_text(
                document[
                    "updatedAt"
                ],
                field_name="updatedAt",
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise RunMetricJournalCorruptionError(
                "metrics/status.json contains "
                "an invalid updatedAt"
            ) from exc

        self._dropped_records = (
            dropped_records
        )
        self._dropped_bytes = (
            dropped_bytes
        )
        self._last_drop_reason = (
            reason.strip()
        )

    def _write_loss_status(
        self,
        *,
        updated_at: datetime,
    ) -> None:
        """Atomically persist explicit Metric-loss evidence."""

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        document = {
            "apiVersion": (
                RUN_METRIC_STATUS_API_VERSION
            ),
            "kind": (
                RUN_METRIC_STATUS_KIND
            ),
            "runId": self.run_id,
            "droppedRecords": (
                self._dropped_records
            ),
            "droppedBytes": (
                self._dropped_bytes
            ),
            "lossOccurred": True,
            "lastDropReason": (
                self._last_drop_reason
            ),
            "updatedAt": (
                _timestamp_text(
                    updated_at
                )
            ),
        }

        encoded = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

        temporary = (
            self.directory
            / ".status.json.tmp"
        )

        temporary.write_text(
            encoded,
            encoding="utf-8",
        )

        os.replace(
            temporary,
            self.status_path,
        )

    def _drop(
        self,
        *,
        encoded_bytes: int,
        reason: str,
        recorded_at: datetime,
    ) -> None:
        self._dropped_records += 1
        self._dropped_bytes += (
            encoded_bytes
        )
        self._last_drop_reason = (
            reason
        )

        self._write_loss_status(
            updated_at=recorded_at
        )

    def _scan(
        self,
        *,
        collect: bool,
    ) -> tuple[
        int,
        tuple[
            RunMetricRecord,
            ...,
        ],
    ]:
        path = self.path

        if not path.exists():
            return (
                1,
                (),
            )

        if not path.is_file():
            raise (
                RunMetricJournalCorruptionError(
                    "metrics/records.jsonl exists "
                    "but is not a file"
                )
            )

        expected = 1
        records: list[
            RunMetricRecord
        ] = []

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
                    raise (
                        RunMetricJournalCorruptionError(
                            "metrics/records.jsonl "
                            "contains an incomplete "
                            "final record"
                        )
                    )

                try:
                    document = json.loads(
                        raw.decode(
                            "utf-8"
                        )
                    )
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ) as exc:
                    raise (
                        RunMetricJournalCorruptionError(
                            "metrics/records.jsonl "
                            "contains an invalid "
                            "JSON record"
                        )
                    ) from exc

                try:
                    record = (
                        RunMetricRecord
                        .from_document(
                            document
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                ) as exc:
                    raise (
                        RunMetricJournalCorruptionError(
                            "metrics/records.jsonl "
                            "contains an invalid "
                            "Run Metric record"
                        )
                    ) from exc

                if (
                    record.run_id
                    != self.run_id
                ):
                    raise (
                        RunMetricJournalCorruptionError(
                            "Run Metric record belongs "
                            "to a different Run"
                        )
                    )

                if (
                    record.sequence
                    != expected
                ):
                    raise (
                        RunMetricJournalCorruptionError(
                            "Run Metric sequence "
                            "is not contiguous"
                        )
                    )

                if collect:
                    records.append(
                        record
                    )

                expected += 1

        return (
            expected,
            tuple(
                records
            ),
        )

    def append(
        self,
        metric: MetricRecord,
        *,
        recorded_at: datetime | None = None,
    ) -> RunMetricRecord | None:
        """Append one canonical typed Metric observation.

        ``None`` means the Metric was deliberately dropped by the bounded
        observability policy.  Such loss is recorded in metrics/status.json and
        never changes canonical execution success/failure.
        """

        if not isinstance(
            metric,
            MetricRecord,
        ):
            raise TypeError(
                "metric must be a MetricRecord"
            )

        timestamp = _timestamp(
            (
                datetime.now(
                    timezone.utc
                )
                if recorded_at is None
                else recorded_at
            ),
            field_name="recorded_at",
        )

        with self._lock:
            record = RunMetricRecord(
                run_id=self.run_id,
                sequence=(
                    self._next_sequence
                ),
                recorded_at=timestamp,
                metric=metric,
            )

            document = (
                record.to_document()
            )

            encoded = (
                json.dumps(
                    document,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode(
                "utf-8"
            )

            encoded_bytes = len(
                encoded
            )

            if (
                encoded_bytes
                > self._policy.max_record_bytes
            ):
                self._drop(
                    encoded_bytes=encoded_bytes,
                    reason="record-too-large",
                    recorded_at=timestamp,
                )
                return None

            if (
                self._stored_records
                >= self._policy.max_records
            ):
                self._drop(
                    encoded_bytes=encoded_bytes,
                    reason="record-limit",
                    recorded_at=timestamp,
                )
                return None

            if (
                self._stored_bytes
                + encoded_bytes
                > self._policy.max_bytes
            ):
                self._drop(
                    encoded_bytes=encoded_bytes,
                    reason="byte-limit",
                    recorded_at=timestamp,
                )
                return None

            self.directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            with self.path.open(
                "ab",
            ) as stream:
                stream.write(
                    encoded
                )
                stream.flush()

            self._next_sequence += 1
            self._stored_records += 1
            self._stored_bytes += (
                encoded_bytes
            )

            return record

    def read_all(
        self,
    ) -> tuple[
        RunMetricRecord,
        ...,
    ]:
        """Read and validate all canonical Metric records."""

        with self._lock:
            (
                next_sequence,
                records,
            ) = self._scan(
                collect=True
            )

            # Synchronize local writer state with validated durable history.
            self._next_sequence = (
                next_sequence
            )

            return records


class RunMetricSink:
    """Adapt a canonical RunMetricJournal to the SDK MetricSink contract.

    Policy drops and Metric storage failures remain observability outcomes and
    must not change the control-plane success or failure of an Execution.
    """

    def __init__(
        self,
        journal: RunMetricJournal,
    ) -> None:
        if not isinstance(
            journal,
            RunMetricJournal,
        ):
            raise TypeError(
                "journal must be a RunMetricJournal"
            )

        self._journal = journal

    @property
    def journal(
        self,
    ) -> RunMetricJournal:
        return self._journal

    def publish(
        self,
        metric: MetricRecord,
    ) -> MetricPublishResult:
        if not isinstance(
            metric,
            MetricRecord,
        ):
            raise TypeError(
                "metric must be a MetricRecord"
            )

        try:
            record = self._journal.append(
                metric
            )
        except Exception:
            return MetricPublishResult(
                accepted=False,
                reason="storage-error",
            )

        if record is None:
            return MetricPublishResult(
                accepted=False,
                reason=(
                    self._journal.last_drop_reason
                    or "dropped"
                ),
            )

        return MetricPublishResult(
            accepted=True
        )


__all__ = [
    "RUN_METRIC_RECORD_API_VERSION",
    "RUN_METRIC_RECORD_KIND",
    "RUN_METRIC_STATUS_API_VERSION",
    "RUN_METRIC_STATUS_KIND",
    "RunMetricJournal",
    "RunMetricJournalCorruptionError",
    "RunMetricJournalError",
    "RunMetricRecord",
    "RunMetricSink",
]
