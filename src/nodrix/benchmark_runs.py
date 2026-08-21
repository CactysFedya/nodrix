"""Canonical Run-set bridge for Nodrix benchmark aggregation.

This module converts complete persisted canonical Runs into the pure benchmark
aggregation model.

One aggregate represents repetitions of one exact workload.  Definition and
resolved Plan differences are therefore rejected rather than silently mixed.

ExecutionPolicy is intentionally separate from workload identity.  Runs with
different effective policies remain aggregatable, but the difference is
explicitly preserved in the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Mapping

from .benchmark_aggregation import (
    BenchmarkAggregation,
    BenchmarkRunMetricObservation,
    BenchmarkRunObservation,
    aggregate_benchmark_observations,
)
from .run_bundle import (
    CanonicalRunBundle,
)
from .run_metric_comparison import (
    summarize_run_metrics,
)


class BenchmarkRunSetError(
    RuntimeError
):
    """Base error for canonical Benchmark Run-set construction."""


class BenchmarkWorkloadMismatchError(
    BenchmarkRunSetError
):
    """Measured Runs do not represent one exact workload."""


def _plain_json(
    value: Any,
) -> Any:
    if isinstance(
        value,
        Mapping,
    ):
        return {
            key: _plain_json(
                item
            )
            for key, item
            in value.items()
        }

    if isinstance(
        value,
        (tuple, list),
    ):
        return [
            _plain_json(
                item
            )
            for item
            in value
        ]

    return value


def _snapshot_content(
    document: Mapping[str, Any],
    *,
    field_name: str,
) -> dict[str, Any]:
    content = document.get(
        "content"
    )

    if not isinstance(
        content,
        Mapping,
    ):
        raise TypeError(
            f"{field_name} content must be a mapping"
        )

    result = _plain_json(
        content
    )

    if not isinstance(
        result,
        dict,
    ):
        raise TypeError(
            f"{field_name} content must be an object"
        )

    return result


def _policy_semantics(
    policy: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return effective ExecutionPolicy independent of Run envelope identity."""

    if policy is None:
        return None

    return {
        "environment": _plain_json(
            policy.get(
                "environment"
            )
        ),
        "logs": _plain_json(
            policy.get(
                "logs"
            )
        ),
        # Historical policy v1 has no metrics key and therefore naturally
        # normalizes to metrics=None, equal to disabled metrics in v2.
        "metrics": _plain_json(
            policy.get(
                "metrics"
            )
        ),
    }


def _timestamp(
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
        result = datetime.fromisoformat(
            (
                text[:-1] + "+00:00"
                if text.endswith("Z")
                else text
            )
        )
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc

    if (
        result.tzinfo is None
        or result.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )

    return result.astimezone(
        timezone.utc
    )


def _execution(
    bundle: CanonicalRunBundle,
) -> Mapping[str, Any]:
    value = bundle.run.get(
        "execution"
    )

    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            "Run execution must be a mapping"
        )

    return value


def _successful(
    bundle: CanonicalRunBundle,
) -> bool:
    value = _execution(
        bundle
    ).get(
        "successful"
    )

    if not isinstance(
        value,
        bool,
    ):
        raise TypeError(
            "Run execution.successful must be a bool"
        )

    return value


def _measured_duration_seconds(
    bundle: CanonicalRunBundle,
) -> float | None:
    """Return exact backend-measured duration from canonical Run evidence."""

    if not isinstance(
        bundle,
        CanonicalRunBundle,
    ):
        raise TypeError(
            "bundle must be a CanonicalRunBundle"
        )

    execution = _execution(
        bundle
    )

    details = execution.get(
        "details"
    )

    if details is None:
        return None

    if not isinstance(
        details,
        Mapping,
    ):
        raise BenchmarkRunSetError(
            "canonical Run execution details "
            "must be a mapping"
        )

    timing = details.get(
        "execution_timing"
    )

    if timing is None:
        return None

    if not isinstance(
        timing,
        Mapping,
    ):
        raise BenchmarkRunSetError(
            "canonical Run execution_timing "
            "must be a mapping"
        )

    if (
        timing.get(
            "source"
        )
        != "backend"
    ):
        raise BenchmarkRunSetError(
            "canonical Benchmark measured timing "
            "must come from backend evidence"
        )

    value = timing.get(
        "duration_seconds"
    )

    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            (
                int,
                float,
            ),
        )
    ):
        raise BenchmarkRunSetError(
            "canonical Run execution_timing."
            "duration_seconds must be a real number"
        )

    duration = float(
        value
    )

    if (
        not math.isfinite(
            duration
        )
        or duration < 0.0
    ):
        raise BenchmarkRunSetError(
            "canonical Run execution_timing."
            "duration_seconds must be finite "
            "and non-negative"
        )

    return duration


def _benchmark_duration_seconds(
    bundle: CanonicalRunBundle,
    *,
    require_measured_timing: bool,
) -> float:
    measured = (
        _measured_duration_seconds(
            bundle
        )
    )

    if measured is not None:
        return measured

    if require_measured_timing:
        raise BenchmarkRunSetError(
            "canonical Benchmark measured Run "
            "does not contain exact backend "
            "execution timing"
        )

    return _duration_seconds(
        bundle
    )


def _duration_seconds(
    bundle: CanonicalRunBundle,
) -> float:
    execution = _execution(
        bundle
    )

    started = _timestamp(
        execution.get(
            "startedAt"
        ),
        field_name=(
            "Run execution.startedAt"
        ),
    )

    finished = _timestamp(
        execution.get(
            "finishedAt"
        ),
        field_name=(
            "Run execution.finishedAt"
        ),
    )

    duration = (
        finished
        - started
    ).total_seconds()

    if duration < 0.0:
        raise ValueError(
            "Run execution interval is reversed"
        )

    return duration


def _same_exact_workload(
    first: CanonicalRunBundle,
    second: CanonicalRunBundle,
) -> bool:
    return (
        first.session.subject
        == second.session.subject
        and first.session.subject_revision
        == second.session.subject_revision
        and first.session.operation_kind
        == second.session.operation_kind
        and first.session.plan_id
        == second.session.plan_id
        and _snapshot_content(
            first.definition,
            field_name="definition",
        )
        == _snapshot_content(
            second.definition,
            field_name="definition",
        )
        and _snapshot_content(
            first.plan,
            field_name="plan",
        )
        == _snapshot_content(
            second.plan,
            field_name="plan",
        )
    )


@dataclass(
    frozen=True,
    slots=True,
)
class BenchmarkWorkloadIdentity:
    """Identity shared by every measured Run in one aggregate."""

    subject: str
    subject_revision: str
    operation_kind: str
    plan_id: str

    def __post_init__(
        self,
    ) -> None:
        for field_name in (
            "subject",
            "subject_revision",
            "operation_kind",
            "plan_id",
        ):
            value = getattr(
                self,
                field_name,
            )

            if not isinstance(
                value,
                str,
            ):
                raise TypeError(
                    f"{field_name} must be a string"
                )

            if not value.strip():
                raise ValueError(
                    f"{field_name} must be non-empty"
                )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "subject": (
                self.subject
            ),
            "subjectRevision": (
                self.subject_revision
            ),
            "operationKind": (
                self.operation_kind
            ),
            "planId": (
                self.plan_id
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalBenchmarkAggregation:
    """Canonical benchmark aggregate plus workload/policy provenance."""

    workload: BenchmarkWorkloadIdentity
    policy_comparable: bool
    same_effective_policy: bool | None
    aggregate: BenchmarkAggregation

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.workload,
            BenchmarkWorkloadIdentity,
        ):
            raise TypeError(
                "workload must be BenchmarkWorkloadIdentity"
            )

        if not isinstance(
            self.policy_comparable,
            bool,
        ):
            raise TypeError(
                "policy_comparable must be a bool"
            )

        if (
            self.same_effective_policy
            is not None
            and not isinstance(
                self.same_effective_policy,
                bool,
            )
        ):
            raise TypeError(
                "same_effective_policy must be a bool or None"
            )

        if (
            not self.policy_comparable
            and self.same_effective_policy
            is not None
        ):
            raise ValueError(
                "same_effective_policy must be None "
                "when policy evidence is unavailable"
            )

        if not isinstance(
            self.aggregate,
            BenchmarkAggregation,
        ):
            raise TypeError(
                "aggregate must be BenchmarkAggregation"
            )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "workload": (
                self.workload.to_dict()
            ),
            "policy": {
                "comparable": (
                    self.policy_comparable
                ),
                "sameEffectivePolicy": (
                    self.same_effective_policy
                ),
            },
            "aggregate": (
                self.aggregate.to_dict()
            ),
        }


def benchmark_observation_from_bundle(
    bundle: CanonicalRunBundle,
    *,
    require_measured_timing: bool = False,
) -> BenchmarkRunObservation:
    """Convert one persisted canonical Run into benchmark input."""

    if not isinstance(
        bundle,
        CanonicalRunBundle,
    ):
        raise TypeError(
            "bundle must be a CanonicalRunBundle"
        )

    metrics = summarize_run_metrics(
        bundle
    )

    return BenchmarkRunObservation(
        run_id=(
            bundle.session.run_id
        ),
        successful=(
            _successful(
                bundle
            )
        ),
        duration_seconds=(
            _benchmark_duration_seconds(
                bundle,
                require_measured_timing=require_measured_timing,
            )
        ),
        metrics_enabled=(
            metrics.completeness.metrics_enabled
        ),
        metrics_complete=(
            metrics.completeness.complete
        ),
        metrics=tuple(
            BenchmarkRunMetricObservation(
                descriptor=(
                    item.descriptor
                ),
                summary=(
                    item.summary
                ),
            )
            for item
            in metrics.descriptors
        ),
    )


def aggregate_canonical_benchmark_runs(
    bundles: tuple[
        CanonicalRunBundle,
        ...,
    ],
) -> CanonicalBenchmarkAggregation:
    """Aggregate repetitions of one exact canonical workload."""

    if not isinstance(
        bundles,
        tuple,
    ):
        raise TypeError(
            "bundles must be a tuple"
        )

    if not bundles:
        raise ValueError(
            "canonical benchmark requires Runs"
        )

    for bundle in bundles:
        if not isinstance(
            bundle,
            CanonicalRunBundle,
        ):
            raise TypeError(
                "bundles must contain CanonicalRunBundle values"
            )

    first = bundles[
        0
    ]

    for bundle in bundles[
        1:
    ]:
        if not _same_exact_workload(
            first,
            bundle,
        ):
            raise BenchmarkWorkloadMismatchError(
                "benchmark Runs must represent one exact workload; "
                f"{first.session.run_id} and "
                f"{bundle.session.run_id} differ"
            )

    policy_values = tuple(
        _policy_semantics(
            bundle.policy
        )
        for bundle
        in bundles
    )

    policy_comparable = all(
        value is not None
        for value
        in policy_values
    )

    same_effective_policy = (
        all(
            value
            == policy_values[0]
            for value
            in policy_values[
                1:
            ]
        )
        if policy_comparable
        else None
    )

    observations = tuple(
        benchmark_observation_from_bundle(
            bundle
        )
        for bundle
        in bundles
    )

    return CanonicalBenchmarkAggregation(
        workload=BenchmarkWorkloadIdentity(
            subject=(
                first.session.subject
            ),
            subject_revision=(
                first.session.subject_revision
            ),
            operation_kind=(
                first.session.operation_kind
            ),
            plan_id=(
                first.session.plan_id
            ),
        ),
        policy_comparable=(
            policy_comparable
        ),
        same_effective_policy=(
            same_effective_policy
        ),
        aggregate=(
            aggregate_benchmark_observations(
                observations
            )
        ),
    )


def aggregate_measured_canonical_benchmark_runs(
    bundles: tuple[
        CanonicalRunBundle,
        ...,
    ],
) -> CanonicalBenchmarkAggregation:
    """Aggregate canonical Benchmark performance from exact timing evidence.

    Successful Runs are performance samples and therefore require exact
    backend-measured ExecutionTiming.

    Failed Runs remain canonical execution evidence even when the backend
    failed before producing timing. Their lifecycle duration may remain in the
    observation model for historical evidence, but the pure Benchmark
    aggregator excludes failed Runs from performance duration statistics.
    """

    base = (
        aggregate_canonical_benchmark_runs(
            bundles
        )
    )

    observations = tuple(
        benchmark_observation_from_bundle(
            bundle,
            require_measured_timing=(
                _successful(
                    bundle
                )
            ),
        )
        for bundle
        in bundles
    )

    measured = (
        aggregate_benchmark_observations(
            observations
        )
    )

    return CanonicalBenchmarkAggregation(
        workload=base.workload,
        policy_comparable=(
            base.policy_comparable
        ),
        same_effective_policy=(
            base.same_effective_policy
        ),
        aggregate=measured,
    )


__all__ = [
    "BenchmarkRunSetError",
    "BenchmarkWorkloadIdentity",
    "BenchmarkWorkloadMismatchError",
    "CanonicalBenchmarkAggregation",
    "aggregate_canonical_benchmark_runs",
    "aggregate_measured_canonical_benchmark_runs",
    "benchmark_observation_from_bundle",
]
