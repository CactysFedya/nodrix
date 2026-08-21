from __future__ import annotations

import pytest

from nodrix.benchmark_aggregation import (
    BenchmarkRunMetricObservation,
    BenchmarkRunObservation,
    aggregate_benchmark_observations,
)
from nodrix.model import (
    MetricDescriptor,
)
from nodrix.run_metric_comparison import (
    MetricSeriesSummary,
)


LATENCY = MetricDescriptor(
    name="mapping.update_ms",
    value_type="float",
    unit="ms",
)

VOXELS = MetricDescriptor(
    name="mapping.voxels",
    value_type="integer",
    unit="count",
)


def _metric(
    descriptor,
    *,
    count: int,
    mean: float,
    minimum=None,
    maximum=None,
    last=None,
):
    minimum = (
        mean
        if minimum is None
        else minimum
    )

    maximum = (
        mean
        if maximum is None
        else maximum
    )

    last = (
        mean
        if last is None
        else last
    )

    return BenchmarkRunMetricObservation(
        descriptor=descriptor,
        summary=MetricSeriesSummary(
            count=count,
            minimum=minimum,
            maximum=maximum,
            mean=mean,
            last=last,
        ),
    )


def _run(
    run_id: str,
    *,
    duration: float,
    successful: bool = True,
    complete: bool = True,
    metrics=(),
):
    return BenchmarkRunObservation(
        run_id=run_id,
        successful=successful,
        duration_seconds=duration,
        metrics_enabled=True,
        metrics_complete=complete,
        metrics=tuple(
            sorted(
                metrics,
                key=lambda item: (
                    item.descriptor_id
                ),
            )
        ),
    )


def test_benchmark_aggregates_successful_run_durations() -> None:
    result = aggregate_benchmark_observations(
        (
            _run(
                "run-a",
                duration=10.0,
            ),
            _run(
                "run-b",
                duration=12.0,
            ),
            _run(
                "run-c",
                duration=14.0,
            ),
        )
    )

    assert result.run_count == 3
    assert result.successful_runs == 3
    assert result.failed_runs == 0
    assert result.execution_complete is True

    assert result.duration.count == 3
    assert result.duration.minimum == 10.0
    assert result.duration.maximum == 14.0
    assert result.duration.mean == 12.0


def test_failed_runs_are_explicit_and_excluded_from_statistics() -> None:
    result = aggregate_benchmark_observations(
        (
            _run(
                "run-ok",
                duration=10.0,
            ),
            _run(
                "run-failed",
                duration=999.0,
                successful=False,
            ),
        )
    )

    assert result.run_count == 2
    assert result.successful_runs == 1
    assert result.failed_runs == 1

    assert result.failed_run_ids == (
        "run-failed",
    )

    assert (
        result.duration.mean
        == 10.0
    )

    assert (
        result.execution_complete
        is False
    )

    assert result.complete is False


def test_metric_aggregation_weights_runs_not_internal_samples() -> None:
    result = aggregate_benchmark_observations(
        (
            _run(
                "run-many-samples",
                duration=10.0,
                metrics=(
                    _metric(
                        LATENCY,
                        count=100,
                        mean=10.0,
                        minimum=1.0,
                        maximum=20.0,
                        last=10.0,
                    ),
                ),
            ),
            _run(
                "run-one-sample",
                duration=10.0,
                metrics=(
                    _metric(
                        LATENCY,
                        count=1,
                        mean=20.0,
                    ),
                ),
            ),
        )
    )

    assert len(
        result.metrics
    ) == 1

    metric = result.metrics[
        0
    ]

    assert (
        metric.descriptor_id
        == LATENCY.descriptor_id
    )

    assert metric.observed_runs == 2
    assert metric.total_observations == 101

    # Each Run is one independent benchmark observation.
    assert metric.run_means.mean == 15.0

    assert (
        metric.run_means.mean
        != pytest.approx(
            (
                100 * 10.0
                + 20.0
            )
            / 101
        )
    )


def test_missing_descriptor_is_coverage_not_storage_loss() -> None:
    result = aggregate_benchmark_observations(
        (
            _run(
                "run-a",
                duration=10.0,
                metrics=(
                    _metric(
                        LATENCY,
                        count=2,
                        mean=10.0,
                    ),
                ),
            ),
            _run(
                "run-b",
                duration=11.0,
                metrics=(),
            ),
        )
    )

    assert (
        result.metrics_storage_complete
        is True
    )

    metric = result.metrics[
        0
    ]

    assert metric.observed_runs == 1

    assert (
        metric.all_runs_observed
        is False
    )

    assert metric.complete is False


def test_metric_storage_loss_marks_benchmark_incomplete() -> None:
    result = aggregate_benchmark_observations(
        (
            _run(
                "run-a",
                duration=10.0,
                complete=False,
                metrics=(
                    _metric(
                        LATENCY,
                        count=1,
                        mean=10.0,
                    ),
                ),
            ),
            _run(
                "run-b",
                duration=11.0,
                metrics=(
                    _metric(
                        LATENCY,
                        count=1,
                        mean=11.0,
                    ),
                ),
            ),
        )
    )

    assert (
        result.execution_complete
        is True
    )

    assert (
        result.metrics_storage_complete
        is False
    )

    assert result.complete is False

    assert (
        result.metrics[
            0
        ].complete
        is False
    )


def test_metric_aggregates_are_deterministically_sorted() -> None:
    result = aggregate_benchmark_observations(
        (
            _run(
                "run-a",
                duration=10.0,
                metrics=(
                    _metric(
                        VOXELS,
                        count=1,
                        mean=100.0,
                        minimum=100,
                        maximum=100,
                        last=100,
                    ),
                    _metric(
                        LATENCY,
                        count=1,
                        mean=10.0,
                    ),
                ),
            ),
        )
    )

    ids = tuple(
        item.descriptor_id
        for item
        in result.metrics
    )

    assert ids == tuple(
        sorted(ids)
    )

    assert (
        result.to_dict()
        == result.to_dict()
    )


def test_duplicate_descriptor_inside_one_run_is_rejected() -> None:
    metric = _metric(
        LATENCY,
        count=1,
        mean=10.0,
    )

    with pytest.raises(
        ValueError,
        match="duplicate",
    ):
        BenchmarkRunObservation(
            run_id="run-a",
            successful=True,
            duration_seconds=10.0,
            metrics_enabled=True,
            metrics_complete=True,
            metrics=(
                metric,
                metric,
            ),
        )


def test_empty_benchmark_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="empty Benchmark",
    ):
        aggregate_benchmark_observations(
            ()
        )


def test_benchmark_requires_at_least_one_successful_run() -> None:
    with pytest.raises(
        ValueError,
        match="successful Run",
    ):
        aggregate_benchmark_observations(
            (
                _run(
                    "run-failed",
                    duration=10.0,
                    successful=False,
                ),
            )
        )
