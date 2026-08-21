from __future__ import annotations

import hashlib

from nodrix.benchmark_aggregation import (
    BenchmarkRunObservation,
    aggregate_benchmark_observations,
)
from nodrix.benchmark_result import (
    BenchmarkResultVariant,
    create_canonical_benchmark_result,
)
from nodrix.benchmark_result_artifact import (
    BENCHMARK_RESULT_ARTIFACT_KIND,
    BENCHMARK_RESULT_MEDIA_TYPE,
    benchmark_result_artifact_entity,
    benchmark_result_artifact_payload_path,
    benchmark_result_bytes,
    materialize_benchmark_result,
    read_benchmark_result_artifact,
)
from nodrix.benchmark_runs import (
    BenchmarkWorkloadIdentity,
    CanonicalBenchmarkAggregation,
)
from nodrix.materialized_storage import (
    verify_materialized_record,
)
from nodrix.model import (
    ArtifactRecord,
)


def _aggregation(
    run_ids=(
        "run_result-a",
        "run_result-b",
    ),
):
    aggregate = (
        aggregate_benchmark_observations(
            tuple(
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
        policy_comparable=True,
        same_effective_policy=True,
        aggregate=aggregate,
    )


def _result(
    *,
    run_ids=(
        "run_result-a",
        "run_result-b",
    ),
    variant_name: str = "fast",
):
    return (
        create_canonical_benchmark_result(
            benchmark_plan_id=(
                "plan_benchmark"
            ),
            variant=BenchmarkResultVariant(
                name=variant_name
            ),
            aggregation=_aggregation(
                run_ids
            ),
        )
    )


def test_result_artifact_entity_is_stable_for_plan_and_variant() -> None:
    first = _result(
        run_ids=(
            "run_result-a",
            "run_result-b",
        )
    )

    second = _result(
        run_ids=(
            "run_result-c",
            "run_result-d",
        )
    )

    assert (
        first.identity
        != second.identity
    )

    assert (
        benchmark_result_artifact_entity(
            first
        )
        == benchmark_result_artifact_entity(
            second
        )
    )


def test_different_variant_has_different_logical_artifact_entity() -> None:
    first = _result(
        variant_name="fast"
    )

    second = _result(
        variant_name="accurate"
    )

    assert (
        benchmark_result_artifact_entity(
            first
        )
        != benchmark_result_artifact_entity(
            second
        )
    )


def test_result_materializes_as_canonical_artifact(
    tmp_path,
) -> None:
    result = _result()

    artifact = materialize_benchmark_result(
        result,
        project=tmp_path,
    )

    assert isinstance(
        artifact,
        ArtifactRecord,
    )

    assert (
        artifact.entity
        == benchmark_result_artifact_entity(
            result
        )
    )

    assert (
        artifact.kind
        == BENCHMARK_RESULT_ARTIFACT_KIND
    )

    assert (
        artifact.media_type
        == BENCHMARK_RESULT_MEDIA_TYPE
    )

    assert (
        artifact.metadata[
            "benchmarkResultIdentity"
        ]
        == result.identity.value
    )

    assert (
        artifact.metadata[
            "benchmarkPlanId"
        ]
        == result.benchmark_plan_id
    )

    assert (
        artifact.metadata[
            "measuredRunCount"
        ]
        == 2
    )


def test_artifact_revision_hashes_exact_result_payload_bytes(
    tmp_path,
) -> None:
    result = _result()

    expected_payload = (
        benchmark_result_bytes(
            result
        )
    )

    expected_digest = hashlib.sha256(
        expected_payload
    ).hexdigest()

    artifact = materialize_benchmark_result(
        result,
        project=tmp_path,
    )

    assert (
        artifact.revision.algorithm
        == "sha256"
    )

    assert (
        artifact.revision.digest
        == expected_digest
    )

    assert (
        artifact.revision.entity
        == artifact.entity
    )


def test_repeated_materialization_is_idempotent(
    tmp_path,
) -> None:
    result = _result()

    first = materialize_benchmark_result(
        result,
        project=tmp_path,
    )

    second = materialize_benchmark_result(
        result,
        project=tmp_path,
    )

    assert (
        first.entity
        == second.entity
    )

    assert (
        first.revision
        == second.revision
    )

    assert (
        first.uri
        == second.uri
    )


def test_new_measured_run_set_creates_new_revision_of_same_entity(
    tmp_path,
) -> None:
    first_result = _result(
        run_ids=(
            "run_result-a",
            "run_result-b",
        )
    )

    second_result = _result(
        run_ids=(
            "run_result-c",
            "run_result-d",
        )
    )

    first = materialize_benchmark_result(
        first_result,
        project=tmp_path,
    )

    second = materialize_benchmark_result(
        second_result,
        project=tmp_path,
    )

    assert (
        first.entity
        == second.entity
    )

    assert (
        first.revision
        != second.revision
    )


def test_materialized_payload_round_trips_exact_document(
    tmp_path,
) -> None:
    result = _result()

    artifact = materialize_benchmark_result(
        result,
        project=tmp_path,
    )

    path = (
        benchmark_result_artifact_payload_path(
            tmp_path,
            artifact,
        )
    )

    assert path.is_file()

    assert (
        path.read_bytes()
        == benchmark_result_bytes(
            result
        )
    )

    loaded = read_benchmark_result_artifact(
        tmp_path,
        artifact,
    )

    assert (
        dict(loaded)
        == result.to_dict()
    )


def test_materialized_result_passes_generic_artifact_verification(
    tmp_path,
) -> None:
    artifact = materialize_benchmark_result(
        _result(),
        project=tmp_path,
    )

    assert (
        verify_materialized_record(
            tmp_path,
            artifact,
        )
        is True
    )
