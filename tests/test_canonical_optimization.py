from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from types import SimpleNamespace

import pytest

from nodrix.benchmarking import (
    BENCHMARK_SCHEMA,
)
from nodrix.model import (
    BENCHMARK,
    OPTIMIZATION_PLAN,
    OPTIMIZE,
    WORKFLOW,
    EntityRef,
    ExecutionRecord,
    ExecutionState,
    Operation,
    PlanRecord,
    RevisionRef,
)
from nodrix.optimization import (
    build_optimization_plan,
)
from nodrix.optimization_canonical import (
    optimization_plan_digest,
    optimization_plan_record,
)
from nodrix.optimization_executor import (
    OPTIMIZATION_EXECUTOR,
    OptimizationExecutor,
)


def _time(
    hour: int,
) -> datetime:
    return datetime(
        2026,
        8,
        16,
        hour,
        tzinfo=timezone.utc,
    )


def _domain_plan(
    root: Path,
):
    pipeline = (
        root / "pipeline.yaml"
    )

    pipeline.write_text(
        "name: demo\n",
        encoding="utf-8",
    )

    manifest = SimpleNamespace(
        metadata=SimpleNamespace(
            name="demo"
        ),
        nodes={},
    )

    return build_optimization_plan(
        pipeline,
        manifest,
        constraints={
            "latency_p95_ms": 20.0,
        },
    )


def _operation(
    *,
    run_benchmarks: bool,
) -> Operation:
    entity = EntityRef(
        kind="pipeline",
        namespace="workspace",
        name="demo",
    )

    revision = (
        RevisionRef.from_sha256(
            entity,
            "a" * 64,
        )
    )

    return Operation(
        kind=OPTIMIZE,
        subject=entity,
        subject_revision=revision,
        parameters={
            "run_benchmarks": (
                run_benchmarks
            ),
        },
    )


def _canonical_plan(
    root: Path,
    *,
    run_benchmarks: bool,
) -> tuple[object, PlanRecord]:
    domain = _domain_plan(
        root
    )

    operation = _operation(
        run_benchmarks=run_benchmarks
    )

    record = optimization_plan_record(
        domain,
        operation=operation,
        subject_revision=(
            operation.subject_revision
        ),
    )

    return domain, record


class FakeBenchmarkExecutor:
    def __init__(
        self,
        *,
        state: ExecutionState = (
            ExecutionState.COMPLETED
        ),
    ) -> None:
        self.state = state
        self.calls: list[
            tuple[PlanRecord, object]
        ] = []

    def execute(
        self,
        plan: PlanRecord,
        *,
        output_root=None,
    ) -> ExecutionRecord:
        self.calls.append(
            (plan, output_root)
        )

        suite = {
            "schema": BENCHMARK_SCHEMA,
            "suite_dir": str(
                Path(
                    output_root or "."
                )
                / "suite"
            ),
            "variants": {
                "baseline": {
                    "sink_rate_hz": {
                        "mean": 12.0
                    },
                    "end_to_end_p95_ms": {
                        "mean": 5.0
                    },
                    "temperature_c": {
                        "max": 45.0
                    },
                    "estimated_memory_bytes": {
                        "max": 1024
                    },
                }
            },
        }

        details = {
            "suite_dir": (
                suite["suite_dir"]
            ),
        }

        if (
            self.state
            is ExecutionState.COMPLETED
        ):
            details["suite"] = suite
        else:
            details["error"] = (
                "benchmark failed"
            )

        return ExecutionRecord(
            execution_id=(
                "benchmark-child"
            ),
            plan=plan,
            executor="nodrix.benchmark",
            state=self.state,
            started_at=_time(10),
            finished_at=_time(11),
            details=details,
        )


def test_optimization_vocabulary_is_canonical() -> None:
    assert OPTIMIZE.value == "optimize"
    assert (
        OPTIMIZATION_PLAN.value
        == "optimization"
    )


def test_build_optimization_plan_preserves_optimizer_contract(
    tmp_path: Path,
) -> None:
    plan = _domain_plan(
        tmp_path
    )

    rendered = plan.as_dict()

    assert (
        rendered["schema"]
        == "nodrix.optimization/v1"
    )
    assert rendered["pipeline"] == "demo"
    assert (
        rendered["constraints"][
            "latency_p95_ms"
        ]
        == 20.0
    )
    assert (
        list(rendered["variants"])
        == ["baseline"]
    )
    assert (
        plan.benchmark_plan.pipeline
        == (tmp_path / "pipeline.yaml").resolve()
    )
    assert plan.benchmark_plan.repeat == 3
    assert plan.benchmark_plan.warmup == 1


def test_optimization_digest_is_location_independent_but_content_sensitive(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    first_root.mkdir()
    second_root.mkdir()

    first = _domain_plan(
        first_root
    )

    second = _domain_plan(
        second_root
    )

    assert (
        optimization_plan_digest(first)
        == optimization_plan_digest(second)
    )

    (
        second_root / "pipeline.yaml"
    ).write_text(
        "name: changed\n",
        encoding="utf-8",
    )

    changed = build_optimization_plan(
        second_root / "pipeline.yaml",
        SimpleNamespace(
            metadata=SimpleNamespace(
                name="demo"
            ),
            nodes={},
        ),
        constraints={
            "latency_p95_ms": 20.0,
        },
    )

    assert (
        optimization_plan_digest(first)
        != optimization_plan_digest(changed)
    )


def test_optimization_plan_record_uses_canonical_kind(
    tmp_path: Path,
) -> None:
    domain, record = _canonical_plan(
        tmp_path,
        run_benchmarks=False,
    )

    assert (
        record.kind
        == OPTIMIZATION_PLAN
    )
    assert (
        record.operation.kind
        == OPTIMIZE
    )
    assert record.payload is domain


def test_optimization_executor_can_complete_without_benchmark(
    tmp_path: Path,
) -> None:
    _, record = _canonical_plan(
        tmp_path,
        run_benchmarks=False,
    )

    times = iter(
        (_time(12), _time(13))
    )

    execution = (
        OptimizationExecutor(
            clock=lambda: next(times),
            id_factory=lambda: (
                "optimization-no-benchmark"
            ),
        )
        .execute(record)
    )

    assert (
        execution.state
        is ExecutionState.COMPLETED
    )
    assert execution.successful
    assert (
        execution.executor
        == OPTIMIZATION_EXECUTOR
    )
    assert (
        execution.details[
            "run_benchmarks"
        ]
        is False
    )
    assert (
        execution.details[
            "recommendation"
        ]
        is None
    )


def test_optimization_executor_composes_exact_benchmark_execution(
    tmp_path: Path,
) -> None:
    domain, record = _canonical_plan(
        tmp_path,
        run_benchmarks=True,
    )

    benchmark_executor = (
        FakeBenchmarkExecutor()
    )

    times = iter(
        (_time(12), _time(13))
    )

    output_root = (
        tmp_path / "benchmarks"
    )

    execution = (
        OptimizationExecutor(
            benchmark_executor=(
                benchmark_executor
            ),
            clock=lambda: next(times),
            id_factory=lambda: (
                "optimization-measured"
            ),
        )
        .execute(
            record,
            output_root=output_root,
        )
    )

    assert execution.successful
    assert (
        execution.state
        is ExecutionState.COMPLETED
    )

    assert (
        len(
            benchmark_executor.calls
        )
        == 1
    )

    child_plan, child_output = (
        benchmark_executor.calls[0]
    )

    assert (
        child_plan.operation.kind
        == BENCHMARK
    )
    assert (
        child_plan.operation.subject
        == record.operation.subject
    )
    assert (
        child_plan.subject_revision
        == record.subject_revision
    )

    assert (
        child_plan.payload
        is domain.benchmark_plan
    )

    assert (
        child_output
        == output_root
    )

    assert (
        execution.details[
            "benchmark_execution_id"
        ]
        == "benchmark-child"
    )

    assert (
        execution.details[
            "recommendation"
        ]["selected"]
        == "baseline"
    )


def test_failed_embedded_benchmark_fails_optimization(
    tmp_path: Path,
) -> None:
    _, record = _canonical_plan(
        tmp_path,
        run_benchmarks=True,
    )

    benchmark_executor = (
        FakeBenchmarkExecutor(
            state=ExecutionState.FAILED
        )
    )

    times = iter(
        (_time(12), _time(13))
    )

    execution = (
        OptimizationExecutor(
            benchmark_executor=(
                benchmark_executor
            ),
            clock=lambda: next(times),
            id_factory=lambda: (
                "optimization-failed"
            ),
        )
        .execute(record)
    )

    assert (
        execution.state
        is ExecutionState.FAILED
    )
    assert not execution.successful
    assert (
        execution.details[
            "benchmark_error"
        ]
        == "benchmark failed"
    )


def test_optimization_executor_rejects_wrong_plan_kind(
    tmp_path: Path,
) -> None:
    _, canonical = _canonical_plan(
        tmp_path,
        run_benchmarks=False,
    )

    wrong = PlanRecord(
        plan_id=canonical.plan_id,
        kind=WORKFLOW,
        operation=canonical.operation,
        subject_revision=(
            canonical.subject_revision
        ),
        payload=canonical.payload,
    )

    with pytest.raises(
        ValueError,
        match=(
            "requires an optimization "
            "PlanRecord"
        ),
    ):
        (
            OptimizationExecutor()
            .execute(wrong)
        )
