from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from nodrix.benchmark_canonical import (
    benchmark_plan_record,
)
from nodrix.benchmark_canonical_suite import (
    CanonicalBenchmarkSuiteInputError,
    assemble_canonical_benchmark_suite,
)
from nodrix.benchmark_operation import (
    benchmark_operation,
)
from nodrix.benchmark_result_artifact import (
    read_benchmark_result_artifact,
)
from nodrix.benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.materialized_storage import (
    verify_materialized_record,
)
from nodrix.model import (
    ExecutionRecord,
)
from nodrix.run_bundle import (
    load_canonical_run_bundle,
)
from nodrix.run_policy import (
    RunPolicyStore,
)
from nodrix.run_record import (
    RunRecordStore,
)
from nodrix.run_session import (
    RunStore,
)
from nodrix.run_snapshots import (
    DEFINITION_SNAPSHOT,
    PLAN_SNAPSHOT,
    RunSnapshotStore,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.model import (
    SystemModel,
)
from nodrix.system.run_snapshots import (
    system_definition_snapshot,
    system_plan_snapshot,
)


STARTED = datetime(
    2026,
    8,
    20,
    18,
    0,
    tzinfo=timezone.utc,
)


def _benchmark_plan(
    tmp_path,
    *,
    variants=(
        BenchmarkVariant(
            "fast"
        ),
    ),
):
    pipeline = (
        tmp_path
        / "pipeline.yaml"
    )

    pipeline.write_text(
        "name: canonical-benchmark-suite\n",
        encoding="utf-8",
    )

    domain = BenchmarkPlan(
        pipeline=pipeline,
        repeat=2,
        warmup=1,
        variants=variants,
    )

    operation = (
        benchmark_operation(
            domain
        )
    )

    revision = (
        operation.subject_revision
    )

    assert (
        revision
        is not None
    )

    return benchmark_plan_record(
        domain,
        operation=operation,
        subject_revision=revision,
    )


def _run_bundle(
    root,
    *,
    system_name: str,
    run_id: str,
    execution_id: str,
    duration: float,
):
    system = SystemModel(
        name=system_name
    )

    plan = (
        plan_canonical_system(
            system
        )
    )

    session = RunStore(
        root,
        clock=lambda: STARTED,
    ).create(
        plan,
        run_id=run_id,
    )

    snapshots = (
        RunSnapshotStore(
            session
        )
    )

    snapshots.create(
        DEFINITION_SNAPSHOT,
        system_definition_snapshot(
            system,
            plan,
        ),
    )

    snapshots.create(
        PLAN_SNAPSHOT,
        system_plan_snapshot(
            plan
        ),
    )

    RunPolicyStore(
        session,
        policy=ExecutionPolicy(),
    ).create()

    RunRecordStore(
        session
    ).create(
        ExecutionRecord(
            execution_id=(
                execution_id
            ),
            plan=plan,
            executor=(
                "nodrix.system.orchestrator"
            ),
            state="completed",
            details={
                "execution_timing": {
                    "source": "backend",
                    "target": "host",
                    "backend": "local",
                    "execution_id": execution_id,
                    "duration_seconds": duration,
                },
            },
            started_at=STARTED,
            finished_at=(
                STARTED
                + timedelta(
                    seconds=duration
                )
            ),
        )
    )

    return (
        load_canonical_run_bundle(
            session.directory
        )
    )


def test_strict_suite_assembles_one_result_artifact_per_variant(
    tmp_path,
) -> None:
    plan = _benchmark_plan(
        tmp_path,
        variants=(
            BenchmarkVariant(
                "fast"
            ),
            BenchmarkVariant(
                "accurate"
            ),
        ),
    )

    runs_root = (
        tmp_path
        / "runs"
    )

    fast_a = _run_bundle(
        runs_root,
        system_name="fast-workload",
        run_id="run_fast-a",
        execution_id="execution-fast-a",
        duration=10.0,
    )

    fast_b = _run_bundle(
        runs_root,
        system_name="fast-workload",
        run_id="run_fast-b",
        execution_id="execution-fast-b",
        duration=12.0,
    )

    accurate_a = _run_bundle(
        runs_root,
        system_name="accurate-workload",
        run_id="run_accurate-a",
        execution_id="execution-accurate-a",
        duration=20.0,
    )

    accurate_b = _run_bundle(
        runs_root,
        system_name="accurate-workload",
        run_id="run_accurate-b",
        execution_id="execution-accurate-b",
        duration=22.0,
    )

    suite = (
        assemble_canonical_benchmark_suite(
            plan,
            measured_runs={
                "fast": (
                    fast_a,
                    fast_b,
                ),
                "accurate": (
                    accurate_a,
                    accurate_b,
                ),
            },
            project=tmp_path,
        )
    )

    assert (
        suite.benchmark_plan_id
        == plan.plan_id
    )

    assert [
        item.variant.name
        for item
        in suite.variants
    ] == [
        "fast",
        "accurate",
    ]

    assert len(
        suite.artifacts
    ) == 2

    assert (
        suite.variants[
            0
        ].aggregation.aggregate.duration.mean
        == 11.0
    )

    assert (
        suite.variants[
            1
        ].aggregation.aggregate.duration.mean
        == 21.0
    )

    for item in suite.variants:
        assert (
            verify_materialized_record(
                tmp_path,
                item.artifact,
            )
            is True
        )

        document = (
            read_benchmark_result_artifact(
                tmp_path,
                item.artifact,
            )
        )

        assert (
            document[
                "benchmarkPlanId"
            ]
            == plan.plan_id
        )


def test_suite_variant_sets_must_match_plan_exactly(
    tmp_path,
) -> None:
    plan = _benchmark_plan(
        tmp_path,
        variants=(
            BenchmarkVariant(
                "fast"
            ),
            BenchmarkVariant(
                "accurate"
            ),
        ),
    )

    bundle = _run_bundle(
        tmp_path / "runs",
        system_name="fast-workload",
        run_id="run_fast",
        execution_id="execution-fast",
        duration=10.0,
    )

    with pytest.raises(
        CanonicalBenchmarkSuiteInputError,
        match="missing",
    ):
        assemble_canonical_benchmark_suite(
            plan,
            measured_runs={
                "fast": (
                    bundle,
                ),
            },
            project=tmp_path,
        )


def test_same_run_cannot_be_reused_across_variants(
    tmp_path,
) -> None:
    plan = _benchmark_plan(
        tmp_path,
        variants=(
            BenchmarkVariant(
                "fast"
            ),
            BenchmarkVariant(
                "accurate"
            ),
        ),
    )

    bundle = _run_bundle(
        tmp_path / "runs",
        system_name="shared-workload",
        run_id="run_shared",
        execution_id="execution-shared",
        duration=10.0,
    )

    with pytest.raises(
        CanonicalBenchmarkSuiteInputError,
        match="multiple",
    ):
        assemble_canonical_benchmark_suite(
            plan,
            measured_runs={
                "fast": (
                    bundle,
                ),
                "accurate": (
                    bundle,
                ),
            },
            project=tmp_path,
        )


def test_mismatched_workloads_inside_variant_are_rejected(
    tmp_path,
) -> None:
    plan = _benchmark_plan(
        tmp_path
    )

    first = _run_bundle(
        tmp_path / "runs",
        system_name="workload-a",
        run_id="run_workload-a",
        execution_id="execution-a",
        duration=10.0,
    )

    second = _run_bundle(
        tmp_path / "runs",
        system_name="workload-b",
        run_id="run_workload-b",
        execution_id="execution-b",
        duration=10.0,
    )

    with pytest.raises(
        Exception,
        match="one exact workload",
    ):
        assemble_canonical_benchmark_suite(
            plan,
            measured_runs={
                "fast": (
                    first,
                    second,
                ),
            },
            project=tmp_path,
        )


def test_suite_does_not_require_legacy_report_directories(
    tmp_path,
) -> None:
    plan = _benchmark_plan(
        tmp_path
    )

    first = _run_bundle(
        tmp_path / "runs",
        system_name="strict-workload",
        run_id="run_strict-a",
        execution_id="execution-a",
        duration=10.0,
    )

    second = _run_bundle(
        tmp_path / "runs",
        system_name="strict-workload",
        run_id="run_strict-b",
        execution_id="execution-b",
        duration=12.0,
    )

    suite = (
        assemble_canonical_benchmark_suite(
            plan,
            measured_runs={
                "fast": (
                    first,
                    second,
                ),
            },
            project=tmp_path,
        )
    )

    assert (
        suite.variants[
            0
        ].run_ids
        == (
            "run_strict-a",
            "run_strict-b",
        )
    )

    assert not (
        tmp_path
        / "legacy-runs"
    ).exists()
