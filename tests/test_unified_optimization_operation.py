from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from nodrix.model import (
    OPTIMIZATION_PLAN,
    OPTIMIZE,
    ExecutionState,
)
from nodrix.optimization import (
    build_optimization_plan,
)
from nodrix.optimization_operation import (
    execute_optimization_operation,
    optimization_operation,
)


def _plan(
    tmp_path: Path,
):
    pipeline = (
        tmp_path / "pipeline.yaml"
    )

    pipeline.write_text(
        "name: optimization-demo\n",
        encoding="utf-8",
    )

    manifest = SimpleNamespace(
        metadata=SimpleNamespace(
            name="optimization-demo"
        ),
        nodes={},
    )

    return build_optimization_plan(
        pipeline,
        manifest,
    )


def _runner(
    pipeline: Path,
    run_root: Path,
    profile: str | None,
    set_values: list[str],
    block_values: list[str],
) -> dict[str, object]:
    del (
        profile,
        set_values,
        block_values,
    )

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
        "pipeline": str(
            pipeline
        ),
        "status": "completed",
        "run_dir": str(
            run_dir
        ),
        "duration_seconds": 1.0,
        "nodes": {},
        "edges": [],
        "system": {},
    }


def test_optimization_operation_targets_pipeline_revision(
    tmp_path: Path,
) -> None:
    plan = _plan(
        tmp_path
    )

    operation = (
        optimization_operation(
            plan,
            run_benchmarks=True,
        )
    )

    assert (
        operation.kind
        == OPTIMIZE
    )

    assert (
        operation.subject.kind
        == "pipeline"
    )

    assert (
        operation.subject.name
        == "pipeline"
    )

    assert (
        operation.subject_revision
        is not None
    )

    assert (
        operation.parameters[
            "run_benchmarks"
        ]
        is True
    )


def test_optimization_operation_without_benchmark_writes_one_canonical_run(
    tmp_path: Path,
) -> None:
    plan = _plan(
        tmp_path
    )

    outcome = (
        execute_optimization_operation(
            plan,
            run_benchmarks=False,
            output_dir=(
                tmp_path
                / "optimization"
            ),
        )
    )

    assert outcome.successful

    assert (
        outcome.plan.kind
        == OPTIMIZATION_PLAN
    )

    assert (
        outcome.plan.operation.kind
        == OPTIMIZE
    )

    assert (
        outcome.execution.state
        is ExecutionState.COMPLETED
    )

    assert (
        outcome.spec_path
        .is_file()
    )

    assert (
        outcome.report_path
        .is_file()
    )

    summary = outcome.summary()

    assert (
        summary["schema"]
        == "nodrix.optimization/v1"
    )

    assert (
        summary["applied"]
        is False
    )

    runs = list(
        (
            tmp_path
            / ".nodrix"
            / "runs"
        ).glob("*/run.json")
    )

    assert len(runs) == 1

    document = json.loads(
        runs[0].read_text(
            encoding="utf-8"
        )
    )

    assert (
        document["operation"]["kind"]
        == "optimize"
    )

    assert (
        document["plan"]["kind"]
        == "optimization"
    )

    assert (
        document["execution"]["executor"]
        == "nodrix.optimization"
    )


def test_measured_optimization_uses_embedded_benchmark_without_child_run(
    tmp_path: Path,
) -> None:
    plan = _plan(
        tmp_path
    )

    outcome = (
        execute_optimization_operation(
            plan,
            run_benchmarks=True,
            run_callable=_runner,
            output_dir=(
                tmp_path
                / "optimization"
            ),
        )
    )

    assert outcome.successful

    result = outcome.summary()

    assert (
        "benchmark"
        in result
    )

    assert (
        result["recommendation"][
            "selected"
        ]
        == "baseline"
    )

    assert (
        outcome.execution.details[
            "benchmark_execution_id"
        ].startswith(
            "benchmark-"
        )
    )

    suite_dir = Path(
        outcome.execution.details[
            "benchmark_suite_dir"
        ]
    )

    assert (
        suite_dir
        / "benchmark.json"
    ).is_file()

    runs = list(
        (
            tmp_path
            / ".nodrix"
            / "runs"
        ).glob("*/run.json")
    )

    # The nested Benchmark Execution is evidence inside the optimization
    # operation, not an independently persisted top-level Run.
    assert len(runs) == 1

    document = json.loads(
        runs[0].read_text(
            encoding="utf-8"
        )
    )

    assert (
        document["operation"]["kind"]
        == "optimize"
    )


def test_failed_embedded_benchmark_persists_failed_optimization_run(
    tmp_path: Path,
) -> None:
    plan = _plan(
        tmp_path
    )

    def failing_runner(
        *args,
        **kwargs,
    ):
        del args, kwargs
        raise RuntimeError(
            "measurement failed"
        )

    outcome = (
        execute_optimization_operation(
            plan,
            run_benchmarks=True,
            run_callable=(
                failing_runner
            ),
            output_dir=(
                tmp_path
                / "optimization"
            ),
        )
    )

    assert not outcome.successful

    assert (
        outcome.execution.state
        is ExecutionState.FAILED
    )

    assert (
        outcome.report_path
        .is_file()
    )

    document = json.loads(
        outcome.history.path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        document["status"]
        == "failed"
    )

    assert (
        document["successful"]
        is False
    )

    assert (
        document["operation"]["kind"]
        == "optimize"
    )


def test_optimize_cli_routes_through_canonical_operation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from typer.testing import (
        CliRunner,
    )

    import nodrix.cli_operation_commands as commands
    from nodrix.cli import app

    pipeline = (
        tmp_path
        / "pipeline.yaml"
    )

    pipeline.write_text(
        "name: cli-optimization\n",
        encoding="utf-8",
    )

    manifest = SimpleNamespace(
        metadata=SimpleNamespace(
            name="cli-optimization"
        ),
        nodes={},
    )

    monkeypatch.setattr(
        commands,
        "load_manifest_details",
        lambda path: SimpleNamespace(
            manifest=manifest
        ),
    )

    calls = []

    original = (
        commands
        .execute_optimization_operation
    )

    def execute(
        plan,
        **kwargs,
    ):
        calls.append(plan)

        kwargs[
            "run_callable"
        ] = _runner

        return original(
            plan,
            **kwargs,
        )

    monkeypatch.setattr(
        commands,
        "execute_optimization_operation",
        execute,
    )

    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "optimize",
            str(pipeline),
            "--output-dir",
            str(
                tmp_path
                / "optimization"
            ),
            "--benchmark",
            "--json",
        ],
    )

    assert (
        result.exit_code == 0
    ), result.output

    assert len(calls) == 1

    decoded = json.loads(
        result.stdout
    )

    assert (
        decoded["schema"]
        == "nodrix.optimization/v1"
    )

    assert (
        decoded["recommendation"][
            "selected"
        ]
        == "baseline"
    )

    runs = list(
        (
            tmp_path
            / ".nodrix"
            / "runs"
        ).glob("*/run.json")
    )

    assert len(runs) == 1

    document = json.loads(
        runs[0].read_text(
            encoding="utf-8"
        )
    )

    assert (
        document["operation"]["kind"]
        == "optimize"
    )

    assert (
        document["plan"]["kind"]
        == "optimization"
    )
