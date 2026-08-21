from __future__ import annotations

from copy import deepcopy

import pytest

from nodrix.benchmark_aggregation import (
    BenchmarkRunObservation,
    aggregate_benchmark_observations,
)
from nodrix.benchmark_result import (
    BENCHMARK_AGGREGATION_METHOD,
    BENCHMARK_RESULT_API_VERSION,
    BENCHMARK_RESULT_KIND,
    BenchmarkResultVariant,
    CanonicalBenchmarkResult,
    create_canonical_benchmark_result,
    validate_benchmark_result_document,
)
from nodrix.benchmark_runs import (
    BenchmarkWorkloadIdentity,
    CanonicalBenchmarkAggregation,
)
from nodrix.benchmarking import (
    BenchmarkVariant,
)


def _aggregation(
    *,
    run_ids=(
        "run_result-a",
        "run_result-b",
    ),
    same_policy: bool | None = True,
):
    observations = tuple(
        BenchmarkRunObservation(
            run_id=run_id,
            successful=True,
            duration_seconds=(
                10.0 + index
            ),
            metrics_enabled=False,
            metrics_complete=True,
        )
        for index, run_id
        in enumerate(
            run_ids
        )
    )

    aggregate = (
        aggregate_benchmark_observations(
            observations
        )
    )

    return CanonicalBenchmarkAggregation(
        workload=BenchmarkWorkloadIdentity(
            subject=(
                "nodrix://system/project/demo"
            ),
            subject_revision=(
                "nodrix://system/project/demo"
                "@sha256:"
                + "a" * 64
            ),
            operation_kind="run",
            plan_id="plan_demo",
        ),
        policy_comparable=(
            same_policy is not None
        ),
        same_effective_policy=(
            same_policy
        ),
        aggregate=aggregate,
    )


def test_benchmark_result_is_versioned_and_deterministic() -> None:
    aggregation = _aggregation()

    variant = BenchmarkVariant(
        "fast",
        "benchmark",
        (
            "detector.imgsz=320",
        ),
        (),
    )

    first = (
        create_canonical_benchmark_result(
            benchmark_plan_id=(
                "plan_benchmark"
            ),
            variant=variant,
            aggregation=aggregation,
        )
    )

    second = (
        create_canonical_benchmark_result(
            benchmark_plan_id=(
                "plan_benchmark"
            ),
            variant=variant,
            aggregation=aggregation,
        )
    )

    assert isinstance(
        first,
        CanonicalBenchmarkResult,
    )

    assert first == second

    assert (
        first.identity
        == second.identity
    )

    document = first.to_dict()

    assert (
        document[
            "apiVersion"
        ]
        == BENCHMARK_RESULT_API_VERSION
    )

    assert (
        document[
            "kind"
        ]
        == BENCHMARK_RESULT_KIND
    )

    assert (
        document[
            "aggregationMethod"
        ]
        == BENCHMARK_AGGREGATION_METHOD
    )


def test_result_identity_changes_with_measured_runs() -> None:
    first = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast"
        ),
        aggregation=_aggregation(
            run_ids=(
                "run_result-a",
                "run_result-b",
            )
        ),
    )

    second = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast"
        ),
        aggregation=_aggregation(
            run_ids=(
                "run_result-a",
                "run_result-c",
            )
        ),
    )

    assert (
        first.identity
        != second.identity
    )


def test_result_identity_preserves_measured_run_order() -> None:
    first = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast"
        ),
        aggregation=_aggregation(
            run_ids=(
                "run_result-a",
                "run_result-b",
            )
        ),
    )

    second = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast"
        ),
        aggregation=_aggregation(
            run_ids=(
                "run_result-b",
                "run_result-a",
            )
        ),
    )

    assert (
        first.identity
        != second.identity
    )


def test_result_identity_changes_with_variant_semantics() -> None:
    aggregation = _aggregation()

    first = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast",
            None,
            (
                "x=1",
            ),
            (),
        ),
        aggregation=aggregation,
    )

    second = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast",
            None,
            (
                "x=2",
            ),
            (),
        ),
        aggregation=aggregation,
    )

    assert (
        first.identity
        != second.identity
    )


def test_policy_difference_is_preserved_in_result_semantics() -> None:
    result = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast"
        ),
        aggregation=_aggregation(
            same_policy=False
        ),
    )

    document = result.to_dict()

    assert (
        document[
            "result"
        ][
            "policy"
        ][
            "comparable"
        ]
        is True
    )

    assert (
        document[
            "result"
        ][
            "policy"
        ][
            "sameEffectivePolicy"
        ]
        is False
    )


def test_measured_runs_are_explicit_provenance_inputs() -> None:
    result = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast"
        ),
        aggregation=_aggregation(),
    )

    document = result.to_dict()

    assert (
        document[
            "measuredRuns"
        ]
        == [
            "run_result-a",
            "run_result-b",
        ]
    )

    assert (
        document[
            "measuredRuns"
        ]
        == document[
            "result"
        ][
            "aggregate"
        ][
            "runs"
        ]
    )


def test_wire_validator_accepts_exact_result_document() -> None:
    result = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast"
        ),
        aggregation=_aggregation(),
    )

    document = result.to_dict()

    validated = (
        validate_benchmark_result_document(
            document
        )
    )

    assert (
        dict(validated)
        == document
    )


def test_wire_validator_rejects_semantic_mutation() -> None:
    result = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast"
        ),
        aggregation=_aggregation(),
    )

    document = deepcopy(
        result.to_dict()
    )

    document[
        "result"
    ][
        "aggregate"
    ][
        "durationSeconds"
    ][
        "mean"
    ] = 999.0

    with pytest.raises(
        ValueError,
        match="identity",
    ):
        validate_benchmark_result_document(
            document
        )


def test_wire_validator_rejects_measured_run_mismatch() -> None:
    result = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=BenchmarkVariant(
            "fast"
        ),
        aggregation=_aggregation(),
    )

    document = deepcopy(
        result.to_dict()
    )

    document[
        "measuredRuns"
    ] = [
        "run_other"
    ]

    with pytest.raises(
        ValueError,
        match="measuredRuns",
    ):
        validate_benchmark_result_document(
            document
        )


def test_variant_identity_can_be_constructed_without_domain_object() -> None:
    aggregation = _aggregation()

    variant = BenchmarkResultVariant(
        name="custom",
        profile="benchmark",
        set_values=(
            "x=1",
        ),
        block_values=(
            "detector=blocks/yolo.yaml",
        ),
    )

    result = create_canonical_benchmark_result(
        benchmark_plan_id="plan_benchmark",
        variant=variant,
        aggregation=aggregation,
    )

    assert (
        result.variant
        is variant
    )
