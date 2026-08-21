"""Pure typed aggregation model for canonical Nodrix benchmarks.

A Benchmark is not a special Run type.  It is an ordered collection of
ordinary canonical Runs plus deterministic aggregate statistics.

Aggregation deliberately treats each successful Run as one benchmark sample.
Metric observations are summarized inside each Run first; benchmark statistics
then aggregate those per-Run summaries.  This prevents Runs with more internal
Metric observations from receiving hidden statistical weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .model import MetricDescriptor
from .run_metric_comparison import MetricSeriesSummary


def _finite_number(
    value: object,
    *,
    field_name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(
            value,
            (int, float),
        )
    ):
        raise TypeError(
            f"{field_name} must be numeric"
        )

    result = float(
        value
    )

    if not isfinite(
        result
    ):
        raise ValueError(
            f"{field_name} must be finite"
        )

    return result


@dataclass(
    frozen=True,
    slots=True,
)
class BenchmarkNumericSummary:
    """Statistics across independent successful benchmark Runs."""

    count: int
    minimum: float
    maximum: float
    mean: float

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

        minimum = _finite_number(
            self.minimum,
            field_name="minimum",
        )

        maximum = _finite_number(
            self.maximum,
            field_name="maximum",
        )

        mean = _finite_number(
            self.mean,
            field_name="mean",
        )

        if minimum > maximum:
            raise ValueError(
                "minimum must not exceed maximum"
            )

        if not (
            minimum
            <= mean
            <= maximum
        ):
            raise ValueError(
                "mean must be within minimum/maximum"
            )

        object.__setattr__(
            self,
            "minimum",
            minimum,
        )

        object.__setattr__(
            self,
            "maximum",
            maximum,
        )

        object.__setattr__(
            self,
            "mean",
            mean,
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "count": self.count,
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.mean,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class BenchmarkRunMetricObservation:
    """One descriptor summary produced by one ordinary canonical Run."""

    descriptor: MetricDescriptor
    summary: MetricSeriesSummary

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.descriptor,
            MetricDescriptor,
        ):
            raise TypeError(
                "descriptor must be a MetricDescriptor"
            )

        if not isinstance(
            self.summary,
            MetricSeriesSummary,
        ):
            raise TypeError(
                "summary must be a MetricSeriesSummary"
            )

    @property
    def descriptor_id(
        self,
    ) -> str:
        return self.descriptor.descriptor_id


@dataclass(
    frozen=True,
    slots=True,
)
class BenchmarkRunObservation:
    """Benchmark-relevant observation of one ordinary canonical Run."""

    run_id: str
    successful: bool
    duration_seconds: float
    metrics_enabled: bool | None
    metrics_complete: bool
    metrics: tuple[
        BenchmarkRunMetricObservation,
        ...,
    ] = ()

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.run_id,
            str,
        ):
            raise TypeError(
                "run_id must be a string"
            )

        run_id = self.run_id.strip()

        if not run_id:
            raise ValueError(
                "run_id must be non-empty"
            )

        if not isinstance(
            self.successful,
            bool,
        ):
            raise TypeError(
                "successful must be a bool"
            )

        duration = _finite_number(
            self.duration_seconds,
            field_name="duration_seconds",
        )

        if duration < 0.0:
            raise ValueError(
                "duration_seconds must be non-negative"
            )

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

        if not isinstance(
            self.metrics_complete,
            bool,
        ):
            raise TypeError(
                "metrics_complete must be a bool"
            )

        if not isinstance(
            self.metrics,
            tuple,
        ):
            raise TypeError(
                "metrics must be a tuple"
            )

        ids = []

        for item in self.metrics:
            if not isinstance(
                item,
                BenchmarkRunMetricObservation,
            ):
                raise TypeError(
                    "metrics must contain "
                    "BenchmarkRunMetricObservation values"
                )

            ids.append(
                item.descriptor_id
            )

        if len(ids) != len(
            set(ids)
        ):
            raise ValueError(
                "one Run cannot contain duplicate "
                "Metric descriptor identities"
            )

        if ids != sorted(
            ids
        ):
            raise ValueError(
                "Run Metric observations must be sorted "
                "by descriptor_id"
            )

        object.__setattr__(
            self,
            "run_id",
            run_id,
        )

        object.__setattr__(
            self,
            "duration_seconds",
            duration,
        )


@dataclass(
    frozen=True,
    slots=True,
)
class BenchmarkMetricAggregate:
    """Aggregate of one canonical Metric descriptor across successful Runs."""

    descriptor: MetricDescriptor
    successful_runs: int
    observed_runs: int
    total_observations: int
    run_means: BenchmarkNumericSummary
    metrics_storage_complete: bool

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.descriptor,
            MetricDescriptor,
        ):
            raise TypeError(
                "descriptor must be a MetricDescriptor"
            )

        for field_name in (
            "successful_runs",
            "observed_runs",
            "total_observations",
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

        if self.successful_runs < 1:
            raise ValueError(
                "successful_runs must be positive"
            )

        if (
            self.observed_runs < 1
            or self.observed_runs
            > self.successful_runs
        ):
            raise ValueError(
                "observed_runs must be between 1 "
                "and successful_runs"
            )

        if (
            self.run_means.count
            != self.observed_runs
        ):
            raise ValueError(
                "run_means count must equal observed_runs"
            )

        if (
            self.total_observations
            < self.observed_runs
        ):
            raise ValueError(
                "total_observations cannot be smaller "
                "than observed_runs"
            )

        if not isinstance(
            self.metrics_storage_complete,
            bool,
        ):
            raise TypeError(
                "metrics_storage_complete must be a bool"
            )

    @property
    def descriptor_id(
        self,
    ) -> str:
        return self.descriptor.descriptor_id

    @property
    def all_runs_observed(
        self,
    ) -> bool:
        return (
            self.observed_runs
            == self.successful_runs
        )

    @property
    def complete(
        self,
    ) -> bool:
        return (
            self.all_runs_observed
            and self.metrics_storage_complete
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "descriptorId": (
                self.descriptor.descriptor_id
            ),
            "name": (
                self.descriptor.name
            ),
            "valueType": (
                self.descriptor.value_type.value
            ),
            "unit": (
                self.descriptor.unit
            ),
            "successfulRuns": (
                self.successful_runs
            ),
            "observedRuns": (
                self.observed_runs
            ),
            "allRunsObserved": (
                self.all_runs_observed
            ),
            "totalObservations": (
                self.total_observations
            ),
            "metricsStorageComplete": (
                self.metrics_storage_complete
            ),
            "complete": (
                self.complete
            ),
            "runMeans": (
                self.run_means.to_dict()
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class BenchmarkAggregation:
    """Deterministic aggregate result over ordinary canonical Runs."""

    run_ids: tuple[str, ...]
    successful_run_ids: tuple[str, ...]
    failed_run_ids: tuple[str, ...]
    duration: BenchmarkNumericSummary
    metrics_storage_complete: bool
    metrics: tuple[
        BenchmarkMetricAggregate,
        ...,
    ]

    def __post_init__(
        self,
    ) -> None:
        if not self.run_ids:
            raise ValueError(
                "benchmark aggregation requires Runs"
            )

        if not self.successful_run_ids:
            raise ValueError(
                "benchmark aggregation requires at least "
                "one successful Run"
            )

        if (
            len(
                set(self.run_ids)
            )
            != len(
                self.run_ids
            )
        ):
            raise ValueError(
                "benchmark Run identities must be unique"
            )

        partition = (
            self.successful_run_ids
            + self.failed_run_ids
        )

        if (
            set(partition)
            != set(self.run_ids)
            or len(partition)
            != len(self.run_ids)
        ):
            raise ValueError(
                "successful/failed Runs must exactly "
                "partition run_ids"
            )

        if (
            self.duration.count
            != len(
                self.successful_run_ids
            )
        ):
            raise ValueError(
                "duration count must equal successful Run count"
            )

        if not isinstance(
            self.metrics_storage_complete,
            bool,
        ):
            raise TypeError(
                "metrics_storage_complete must be a bool"
            )

        ids = tuple(
            item.descriptor_id
            for item
            in self.metrics
        )

        if ids != tuple(
            sorted(ids)
        ):
            raise ValueError(
                "Metric aggregates must be sorted "
                "by descriptor_id"
            )

        if len(ids) != len(
            set(ids)
        ):
            raise ValueError(
                "Metric aggregate identities must be unique"
            )

    @property
    def run_count(
        self,
    ) -> int:
        return len(
            self.run_ids
        )

    @property
    def successful_runs(
        self,
    ) -> int:
        return len(
            self.successful_run_ids
        )

    @property
    def failed_runs(
        self,
    ) -> int:
        return len(
            self.failed_run_ids
        )

    @property
    def execution_complete(
        self,
    ) -> bool:
        return not self.failed_run_ids

    @property
    def complete(
        self,
    ) -> bool:
        return (
            self.execution_complete
            and self.metrics_storage_complete
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "runs": list(
                self.run_ids
            ),
            "runCount": (
                self.run_count
            ),
            "successfulRuns": (
                self.successful_runs
            ),
            "failedRuns": (
                self.failed_runs
            ),
            "successfulRunIds": list(
                self.successful_run_ids
            ),
            "failedRunIds": list(
                self.failed_run_ids
            ),
            "executionComplete": (
                self.execution_complete
            ),
            "metricsStorageComplete": (
                self.metrics_storage_complete
            ),
            "complete": (
                self.complete
            ),
            "durationSeconds": (
                self.duration.to_dict()
            ),
            "metrics": [
                item.to_dict()
                for item
                in self.metrics
            ],
        }


def _numeric_summary(
    values: list[float],
) -> BenchmarkNumericSummary:
    if not values:
        raise ValueError(
            "cannot summarize an empty value set"
        )

    return BenchmarkNumericSummary(
        count=len(
            values
        ),
        minimum=min(
            values
        ),
        maximum=max(
            values
        ),
        mean=(
            sum(values)
            / len(values)
        ),
    )


def aggregate_benchmark_observations(
    observations: tuple[
        BenchmarkRunObservation,
        ...,
    ],
) -> BenchmarkAggregation:
    """Aggregate benchmark observations without filesystem/runtime concerns."""

    if not isinstance(
        observations,
        tuple,
    ):
        raise TypeError(
            "observations must be a tuple"
        )

    if not observations:
        raise ValueError(
            "cannot aggregate an empty Benchmark"
        )

    for item in observations:
        if not isinstance(
            item,
            BenchmarkRunObservation,
        ):
            raise TypeError(
                "observations must contain "
                "BenchmarkRunObservation values"
            )

    run_ids = tuple(
        item.run_id
        for item
        in observations
    )

    if len(run_ids) != len(
        set(run_ids)
    ):
        raise ValueError(
            "benchmark Run identities must be unique"
        )

    successful = tuple(
        item
        for item
        in observations
        if item.successful
    )

    failed = tuple(
        item
        for item
        in observations
        if not item.successful
    )

    if not successful:
        raise ValueError(
            "benchmark aggregation requires at least "
            "one successful Run"
        )

    duration = _numeric_summary(
        [
            item.duration_seconds
            for item
            in successful
        ]
    )

    metrics_storage_complete = all(
        item.metrics_complete
        for item
        in successful
    )

    descriptors: dict[
        str,
        MetricDescriptor,
    ] = {}

    by_descriptor: dict[
        str,
        list[
            BenchmarkRunMetricObservation
        ],
    ] = {}

    for run in successful:
        for metric in run.metrics:
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

            by_descriptor.setdefault(
                descriptor_id,
                [],
            ).append(
                metric
            )

    aggregates = []

    for descriptor_id in sorted(
        by_descriptor
    ):
        observations_for_metric = (
            by_descriptor[
                descriptor_id
            ]
        )

        run_means = [
            item.summary.mean
            for item
            in observations_for_metric
        ]

        total_observations = sum(
            item.summary.count
            for item
            in observations_for_metric
        )

        aggregates.append(
            BenchmarkMetricAggregate(
                descriptor=(
                    descriptors[
                        descriptor_id
                    ]
                ),
                successful_runs=len(
                    successful
                ),
                observed_runs=len(
                    observations_for_metric
                ),
                total_observations=(
                    total_observations
                ),
                run_means=(
                    _numeric_summary(
                        run_means
                    )
                ),
                metrics_storage_complete=(
                    metrics_storage_complete
                ),
            )
        )

    return BenchmarkAggregation(
        run_ids=run_ids,
        successful_run_ids=tuple(
            item.run_id
            for item
            in successful
        ),
        failed_run_ids=tuple(
            item.run_id
            for item
            in failed
        ),
        duration=duration,
        metrics_storage_complete=(
            metrics_storage_complete
        ),
        metrics=tuple(
            aggregates
        ),
    )


__all__ = [
    "BenchmarkAggregation",
    "BenchmarkMetricAggregate",
    "BenchmarkNumericSummary",
    "BenchmarkRunMetricObservation",
    "BenchmarkRunObservation",
    "aggregate_benchmark_observations",
]
