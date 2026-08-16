from __future__ import annotations

import json
from pathlib import Path

from nodrix.benchmark_operation import (
    benchmark_operation,
    execute_benchmark_operation,
)
from nodrix.benchmarking import (
    BENCHMARK_SCHEMA,
    BenchmarkPlan,
    BenchmarkVariant,
)
from nodrix.model import (
    BENCHMARK,
    BENCHMARK_PLAN,
    ExecutionState,
)


def _plan(
    tmp_path: Path,
) -> BenchmarkPlan:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        "name: benchmark-demo\n",
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


def _runner(
    pipeline: Path,
    run_root: Path,
    profile: str | None,
    set_values: list[str],
    block_values: list[str],
) -> dict[str, object]:
    del profile, set_values, block_values

    existing = list(
        run_root.glob("run-*")
    )

    run_dir = (
        run_root
        / f"run-{len(existing) + 1}"
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return {
        "pipeline": str(pipeline),
        "status": "completed",
        "run_dir": str(run_dir),
        "duration_seconds": 1.0,
        "nodes": {},
        "edges": [],
        "system": {},
    }


def test_benchmark_operation_targets_pipeline_revision(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)

    operation = benchmark_operation(plan)

    assert operation.kind == BENCHMARK
    assert operation.subject.kind == "pipeline"
    assert operation.subject.name == "pipeline"
    assert operation.subject_revision is not None
    assert (
        operation.subject_revision.entity
        == operation.subject
    )
    assert operation.parameters["repeat"] == 2
    assert operation.parameters["warmup"] == 1


def test_execute_benchmark_operation_uses_complete_canonical_path(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)

    outcome = execute_benchmark_operation(
        plan,
        run_callable=_runner,
        output_root=tmp_path / "benchmarks",
    )

    assert outcome.successful
    assert outcome.plan.kind == BENCHMARK_PLAN
    assert outcome.plan.operation.kind == BENCHMARK
    assert (
        outcome.execution.state
        is ExecutionState.COMPLETED
    )
    assert (
        outcome.execution.executor
        == "nodrix.benchmark"
    )

    summary = outcome.summary()

    assert summary["schema"] == BENCHMARK_SCHEMA

    suite_dir = Path(summary["suite_dir"])

    assert (
        suite_dir / "benchmark.json"
    ).is_file()

    assert outcome.history.path.is_file()

    document = json.loads(
        outcome.history.path.read_text(
            encoding="utf-8"
        )
    )

    assert document["schema"] == "nodrix.run/v1"
    assert document["operation"]["kind"] == "benchmark"
    assert document["plan"]["kind"] == "benchmark"
    assert (
        document["execution"]["executor"]
        == "nodrix.benchmark"
    )
    assert document["status"] == "completed"
    assert document["successful"] is True


def test_benchmark_history_does_not_replace_suite_artifacts(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)

    outcome = execute_benchmark_operation(
        plan,
        run_callable=_runner,
        output_root=tmp_path / "benchmarks",
    )

    suite_dir = Path(
        outcome.execution.details["suite_dir"]
    )

    assert (
        suite_dir / "benchmark.json"
    ).is_file()

    assert (
        suite_dir
        / "variants"
        / "fast"
        / "summary.json"
    ).is_file()

    assert outcome.history.path.is_file()

    assert (
        outcome.history.path.parent
        != suite_dir
    )


def test_failed_benchmark_is_persisted_as_failed_run(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)

    def failing_runner(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("benchmark failed")

    outcome = execute_benchmark_operation(
        plan,
        run_callable=failing_runner,
    )

    assert not outcome.successful
    assert (
        outcome.execution.state
        is ExecutionState.FAILED
    )
    assert outcome.history.path.is_file()

    document = json.loads(
        outcome.history.path.read_text(
            encoding="utf-8"
        )
    )

    assert document["status"] == "failed"
    assert document["successful"] is False


def test_benchmark_cli_routes_through_canonical_operation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from typer.testing import CliRunner

    import nodrix.cli_operation_commands as commands
    from nodrix.cli import app

    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        "name: cli-benchmark\n",
        encoding="utf-8",
    )

    calls = []

    original = commands.execute_benchmark_operation

    def execute(plan, **kwargs):
        calls.append(plan)
        kwargs["run_callable"] = _runner
        return original(plan, **kwargs)

    monkeypatch.setattr(
        commands,
        "execute_benchmark_operation",
        execute,
    )

    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "benchmark",
            str(pipeline),
            "--repeat",
            "1",
            "--warmup",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(calls) == 1

    summary = json.loads(result.stdout)

    assert summary["schema"] == BENCHMARK_SCHEMA

    canonical_runs = list(
        (tmp_path / ".nodrix" / "runs").glob(
            "*/run.json"
        )
    )

    assert len(canonical_runs) == 1

    document = json.loads(
        canonical_runs[0].read_text(
            encoding="utf-8"
        )
    )

    assert document["operation"]["kind"] == "benchmark"
    assert document["plan"]["kind"] == "benchmark"
