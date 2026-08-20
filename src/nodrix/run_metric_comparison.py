"""Streaming-friendly comparison of canonical typed Run Metrics.

Metric observations are grouped strictly by canonical descriptor identity.
The current canonical Metric model supports integer and float values, so
summaries can be computed in O(1) memory per descriptor without retaining
samples for percentile calculation.

Known storage loss is always exposed explicitly.  ``complete`` means that the
persistent Metric journal reports no dropped observations; it does not mean
that Metrics were enabled or that every possible application measurement was
published.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from .model import (
    MetricDescriptor,
)
from .run_bundle import (
    CanonicalRunBundle,
)
from .run_metrics import (
    RunMetricJournal,
    RunMetricRecord,
)


MetricNumber = int | float


def _number(
    value: object,
) -> MetricNumber:
    if isinstance(
        value,
        bool,
    ) or not isinstance(
        value,
        (int, float),
    ):
        raise TypeError(
            "canonical Metric value must be numeric"
        )

    if (
        isinstance(value, float)
        and not isfinite(value)
    ):
        raise ValueError(
            "canonical Metric value must be finite"
        )

    return value


def _percent_delta(
    first: float,
    second: float,
) -> float | None:
    if first == 0.0:
        return None

    return (
        (second - first)
        / abs(first)
        * 100.0
    )


@dataclass(
    frozen=True,
    slots=True,
)
class MetricSeriesSummary:
    """Bounded numeric summary of observations for one descriptor."""

    count: int
    minimum: MetricNumber
    maximum: MetricNumber
    mean: float
    last: MetricNumber

    def __post_init__(
        self,
    ) -> None:
        if (
            isinstance(self.count, bool)
            or not isinstance(
                self.count,
                int,
            )
            or self.count < 1
        ):
            raise ValueError(
                "count must be a positive integer"
            )

        for field_name in (
            "minimum",
            "maximum",
            "last",
        ):
            _number(
                getattr(
                    self,
                    field_name,
                )
            )

        if (
            isinstance(self.mean, bool)
            or not isinstance(
                self.mean,
                (int, float),
            )
            or not isfinite(
                float(self.mean)
            )
        ):
            raise ValueError(
                "mean must be finite"
            )

        object.__setattr__(
            self,
            "mean",
            float(self.mean),
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "count": self.count,
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.mean,
            "last": self.last,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class RunMetricCompleteness:
    """Storage availability/loss evidence for one Run Metric journal."""

    metrics_enabled: bool | None
    stored_records: int
    dropped_records: int
    dropped_bytes: int
    complete: bool
    last_drop_reason: str | None

    def __post_init__(
        self,
    ) -> None:
        if (
            self.metrics_enabled
            is not None
            and not isinstance(
                self.metrics_enabled,
                bool,
            )
        ):
            raise TypeError(
                "metrics_enabled must be a bool or None"
            )

        for field_name in (
            "stored_records",
            "dropped_records",
            "dropped_bytes",
        ):
            value = getattr(
                self,
                field_name,
            )

            if (
                isinstance(value, bool)
                or not isinstance(
                    value,
                    int,
                )
                or value < 0
            ):
                raise ValueError(
                    f"{field_name} must be a "
                    "non-negative integer"
                )

        if not isinstance(
            self.complete,
            bool,
        ):
            raise TypeError(
                "complete must be a bool"
            )

        expected_complete = (
            self.dropped_records == 0
        )

        if (
            self.complete
            != expected_complete
        ):
            raise ValueError(
                "complete must reflect dropped_records"
            )

        if (
            self.dropped_records == 0
            and self.last_drop_reason
            is not None
        ):
            raise ValueError(
                "last_drop_reason requires dropped Metrics"
            )

        if (
            self.dropped_records > 0
            and (
                not isinstance(
                    self.last_drop_reason,
                    str,
                )
                or not self.last_drop_reason.strip()
            )
        ):
            raise ValueError(
                "dropped Metrics require last_drop_reason"
            )

    @property
    def loss_occurred(
        self,
    ) -> bool:
        return not self.complete

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "metricsEnabled": (
                self.metrics_enabled
            ),
            "storedRecords": (
                self.stored_records
            ),
            "droppedRecords": (
                self.dropped_records
            ),
            "droppedBytes": (
                self.dropped_bytes
            ),
            "complete": (
                self.complete
            ),
            "lossOccurred": (
                self.loss_occurred
            ),
            "lastDropReason": (
                self.last_drop_reason
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class MetricDescriptorComparison:
    """Comparison of one canonical descriptor across two Runs."""

    descriptor_id: str
    name: str
    value_type: str
    unit: str | None
    first: MetricSeriesSummary | None
    second: MetricSeriesSummary | None
    count_delta: int | None
    mean_delta: float | None
    mean_percent: float | None

    @property
    def comparable(
        self,
    ) -> bool:
        return (
            self.first is not None
            and self.second is not None
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "descriptorId": (
                self.descriptor_id
            ),
            "name": self.name,
            "valueType": (
                self.value_type
            ),
            "unit": self.unit,
            "comparable": (
                self.comparable
            ),
            "first": (
                None
                if self.first is None
                else self.first.to_dict()
            ),
            "second": (
                None
                if self.second is None
                else self.second.to_dict()
            ),
            "countDelta": (
                self.count_delta
            ),
            "meanDelta": (
                self.mean_delta
            ),
            "meanPercent": (
                self.mean_percent
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class RunMetricsComparison:
    """Typed Metric comparison and completeness evidence for two Runs."""

    first: RunMetricCompleteness
    second: RunMetricCompleteness
    descriptors: tuple[
        MetricDescriptorComparison,
        ...,
    ]

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.first,
            RunMetricCompleteness,
        ):
            raise TypeError(
                "first must be RunMetricCompleteness"
            )

        if not isinstance(
            self.second,
            RunMetricCompleteness,
        ):
            raise TypeError(
                "second must be RunMetricCompleteness"
            )

        if not isinstance(
            self.descriptors,
            tuple,
        ):
            raise TypeError(
                "descriptors must be a tuple"
            )

        ids = tuple(
            item.descriptor_id
            for item
            in self.descriptors
        )

        if ids != tuple(
            sorted(ids)
        ):
            raise ValueError(
                "descriptors must be sorted by descriptor_id"
            )

        if len(ids) != len(
            set(ids)
        ):
            raise ValueError(
                "descriptor identities must be unique"
            )

    @property
    def complete(
        self,
    ) -> bool:
        return (
            self.first.complete
            and self.second.complete
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "first": (
                self.first.to_dict()
            ),
            "second": (
                self.second.to_dict()
            ),
            "complete": self.complete,
            "descriptors": [
                item.to_dict()
                for item
                in self.descriptors
            ],
        }


def _metrics_enabled(
    bundle: CanonicalRunBundle,
) -> bool | None:
    if bundle.policy is None:
        return None

    return (
        bundle.policy.get(
            "metrics"
        )
        is not None
    )


def _journal_state(
    bundle: CanonicalRunBundle,
) -> tuple[
    RunMetricJournal,
    tuple[
        RunMetricRecord,
        ...,
    ],
    RunMetricCompleteness,
]:
    journal = RunMetricJournal(
        bundle.session
    )

    records = journal.read_all()

    completeness = (
        RunMetricCompleteness(
            metrics_enabled=(
                _metrics_enabled(
                    bundle
                )
            ),
            stored_records=(
                journal.stored_records
            ),
            dropped_records=(
                journal.dropped_records
            ),
            dropped_bytes=(
                journal.dropped_bytes
            ),
            complete=(
                not journal.loss_occurred
            ),
            last_drop_reason=(
                journal.last_drop_reason
            ),
        )
    )

    return (
        journal,
        records,
        completeness,
    )


def _summaries(
    records: tuple[
        RunMetricRecord,
        ...,
    ],
) -> tuple[
    dict[
        str,
        MetricDescriptor,
    ],
    dict[
        str,
        MetricSeriesSummary,
    ],
]:
    descriptors: dict[
        str,
        MetricDescriptor,
    ] = {}

    state: dict[
        str,
        dict[str, Any],
    ] = {}

    for record in records:
        metric = record.metric
        descriptor = (
            metric.descriptor
        )
        descriptor_id = (
            descriptor.descriptor_id
        )

        existing = descriptors.get(
            descriptor_id
        )

        if (
            existing is not None
            and (
                existing.name
                != descriptor.name
                or existing.value_type
                != descriptor.value_type
                or existing.unit
                != descriptor.unit
            )
        ):
            raise ValueError(
                "same descriptorId resolved to "
                "different Metric semantics"
            )

        descriptors[
            descriptor_id
        ] = descriptor

        value = _number(
            metric.value
        )

        current = state.get(
            descriptor_id
        )

        if current is None:
            state[
                descriptor_id
            ] = {
                "count": 1,
                "minimum": value,
                "maximum": value,
                "total": float(
                    value
                ),
                "last": value,
                "sequence": (
                    record.sequence
                ),
            }
            continue

        current["count"] += 1

        current["minimum"] = min(
            current["minimum"],
            value,
        )

        current["maximum"] = max(
            current["maximum"],
            value,
        )

        current["total"] += float(
            value
        )

        if (
            record.sequence
            > current[
                "sequence"
            ]
        ):
            current["last"] = value
            current[
                "sequence"
            ] = record.sequence

    summaries: dict[
        str,
        MetricSeriesSummary,
    ] = {}

    for (
        descriptor_id,
        current,
    ) in state.items():
        summaries[
            descriptor_id
        ] = MetricSeriesSummary(
            count=current["count"],
            minimum=current[
                "minimum"
            ],
            maximum=current[
                "maximum"
            ],
            mean=(
                current["total"]
                / current["count"]
            ),
            last=current["last"],
        )

    return (
        descriptors,
        summaries,
    )


def compare_run_metrics(
    first: CanonicalRunBundle,
    second: CanonicalRunBundle,
) -> RunMetricsComparison:
    """Compare canonical typed Metrics for two persisted Runs."""

    if not isinstance(
        first,
        CanonicalRunBundle,
    ):
        raise TypeError(
            "first must be a CanonicalRunBundle"
        )

    if not isinstance(
        second,
        CanonicalRunBundle,
    ):
        raise TypeError(
            "second must be a CanonicalRunBundle"
        )

    (
        _,
        first_records,
        first_completeness,
    ) = _journal_state(
        first
    )

    (
        _,
        second_records,
        second_completeness,
    ) = _journal_state(
        second
    )

    (
        first_descriptors,
        first_summaries,
    ) = _summaries(
        first_records
    )

    (
        second_descriptors,
        second_summaries,
    ) = _summaries(
        second_records
    )

    descriptor_ids = sorted(
        set(
            first_descriptors
        )
        | set(
            second_descriptors
        )
    )

    comparisons = []

    for descriptor_id in (
        descriptor_ids
    ):
        descriptor = (
            first_descriptors.get(
                descriptor_id
            )
            or second_descriptors[
                descriptor_id
            ]
        )

        first_summary = (
            first_summaries.get(
                descriptor_id
            )
        )

        second_summary = (
            second_summaries.get(
                descriptor_id
            )
        )

        if (
            first_summary is not None
            and second_summary is not None
        ):
            count_delta = (
                second_summary.count
                - first_summary.count
            )

            mean_delta = (
                second_summary.mean
                - first_summary.mean
            )

            mean_percent = (
                _percent_delta(
                    first_summary.mean,
                    second_summary.mean,
                )
            )
        else:
            count_delta = None
            mean_delta = None
            mean_percent = None

        comparisons.append(
            MetricDescriptorComparison(
                descriptor_id=(
                    descriptor_id
                ),
                name=descriptor.name,
                value_type=(
                    descriptor.value_type.value
                ),
                unit=descriptor.unit,
                first=first_summary,
                second=second_summary,
                count_delta=(
                    count_delta
                ),
                mean_delta=(
                    mean_delta
                ),
                mean_percent=(
                    mean_percent
                ),
            )
        )

    return RunMetricsComparison(
        first=first_completeness,
        second=second_completeness,
        descriptors=tuple(
            comparisons
        ),
    )


__all__ = [
    "MetricDescriptorComparison",
    "MetricSeriesSummary",
    "RunMetricCompleteness",
    "RunMetricsComparison",
    "compare_run_metrics",
]
