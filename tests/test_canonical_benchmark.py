from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from nodrix.benchmark_canonical import (
    benchmark_plan_digest,
    benchmark_plan_record,
)
from nodrix.benchmark_executor import (
    BENCHMARK_EXECUTOR,
    BenchmarkExecutor,
)
from nodrix.benchmarking import (
    BENCHMARK_SCHEMA,
    BenchmarkPlan,
    BenchmarkVariant,
)
from nodrix.model import (
    BENCHMARK,
    BENCHMARK_PLAN,
    WORKFLOW,
    EntityRef,
    ExecutionState,
    Operation,
    PlanRecord,
    RevisionRef,
)


def _time(hour: int):
    return datetime(
        2026,
        8,
        16,
        hour,
        0,
        tzinfo=timezone.utc,
    )


def _identity():
    entity = EntityRef(
        kind="project",
        namespace="workspace",
        name="benchmark-project",
    )

    revision = RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )

    return entity, revision


def _operation():
    entity, revision = _identity()

    return Operation(
        kind=BENCHMARK,
        subject=entity,
        subject_revision=revision,
    )


def _plan(
    root: Path,
) -> BenchmarkPlan:
    pipeline = root / "pipeline.yaml"
    pipeline.write_text(
        "name: demo\n",
        encoding="utf-8",
    )

    return BenchmarkPlan(
        pipeline=pipeline,
        repeat=2,
        warmup=1,
        variants=(
            BenchmarkVariant(
                "fast",
                "maximum-throughput",
                ("detector.imgsz=320",),
                (),
            ),
        ),
    )


def test_benchmark_plan_digest_is_location_independent(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    first = _plan(first_root)
    second = _plan(second_root)

    assert (
        benchmark_plan_digest(first)
        == benchmark_plan_digest(second)
    )


def test_benchmark_plan_digest_changes_with_pipeline_content(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    first = benchmark_plan_digest(plan)

    plan.pipeline.write_text(
        "name: changed\n",
        encoding="utf-8",
    )

    assert benchmark_plan_digest(plan) != first


def test_benchmark_plan_record_uses_canonical_benchmark_kind(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    operation = _operation()

    record = benchmark_plan_record(
        plan,
        operation=operation,
        subject_revision=operation.subject_revision,
    )

    assert record.kind == BENCHMARK_PLAN
    assert record.kind_name == "benchmark"
    assert record.operation.kind_name == "benchmark"
    assert record.payload is plan
    assert record.plan_id.startswith(
        "benchmark-"
    )
    assert len(
        record.metadata["benchmark_digest"]
    ) == 64


def test_benchmark_executor_runs_exact_domain_plan(
    tmp_path: Path,
) -> None:
    domain_plan = _plan(tmp_path)
    operation = _operation()

    canonical_plan = benchmark_plan_record(
        domain_plan,
        operation=operation,
        subject_revision=operation.subject_revision,
    )

    calls = []

    def run_callable(
        pipeline,
        run_root,
        profile,
        set_values,
        block_values,
    ):
        calls.append(
            (
                pipeline,
                run_root,
                profile,
                set_values,
                block_values,
            )
        )

        run_dir = run_root / f"run-{len(calls)}"
        run_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        return {
            "pipeline": "demo",
            "status": "completed",
            "run_dir": str(run_dir),
            "duration_seconds": 1.0,
            "nodes": {},
            "edges": [],
            "system": {},
        }

    times = iter((_time(12), _time(13)))

    execution = BenchmarkExecutor(
        run_callable=run_callable,
        clock=lambda: next(times),
        id_factory=lambda: "benchmark-test",
    ).execute(
        canonical_plan,
        output_root=tmp_path / "benchmarks",
    )

    assert execution.execution_id == "benchmark-test"
    assert execution.executor == BENCHMARK_EXECUTOR
    assert execution.state is ExecutionState.COMPLETED
    assert execution.successful

    # 1 warm-up + 2 measured runs.
    assert len(calls) == 3

    assert execution.details["repeat"] == 2
    assert execution.details["warmup"] == 1
    assert execution.details["variant_count"] == 1
    assert execution.details["variants"] == ["fast"]
    assert (
        execution.details["benchmark_schema"]
        == BENCHMARK_SCHEMA
    )

    suite_dir = Path(
        execution.details["suite_dir"]
    )

    assert (
        suite_dir / "benchmark.json"
    ).is_file()


def test_benchmark_executor_records_failure(
    tmp_path: Path,
) -> None:
    domain_plan = _plan(tmp_path)
    operation = _operation()

    canonical_plan = benchmark_plan_record(
        domain_plan,
        operation=operation,
        subject_revision=operation.subject_revision,
    )

    def run_callable(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("benchmark exploded")

    times = iter((_time(12), _time(13)))

    execution = BenchmarkExecutor(
        run_callable=run_callable,
        clock=lambda: next(times),
        id_factory=lambda: "benchmark-failed",
    ).execute(canonical_plan)

    assert execution.state is ExecutionState.FAILED
    assert not execution.successful
    assert execution.details["error_type"] == "RuntimeError"
    assert (
        execution.details["error"]
        == "benchmark exploded"
    )


def test_benchmark_executor_rejects_wrong_plan_kind(
    tmp_path: Path,
) -> None:
    domain_plan = _plan(tmp_path)
    operation = _operation()

    canonical_plan = benchmark_plan_record(
        domain_plan,
        operation=operation,
        subject_revision=operation.subject_revision,
    )

    wrong_plan = PlanRecord(
        plan_id=canonical_plan.plan_id,
        kind=WORKFLOW,
        operation=canonical_plan.operation,
        subject_revision=canonical_plan.subject_revision,
        payload=canonical_plan.payload,
    )

    with pytest.raises(
        ValueError,
        match="requires a benchmark PlanRecord",
    ):
        BenchmarkExecutor(
            run_callable=lambda *args: {},
        ).execute(wrong_plan)
