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


def test_benchmark_cli_legacy_mode_routes_through_compatibility_operation(
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
            "--mode",
            "legacy",
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


def test_benchmark_cli_requires_explicit_execution_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from typer.testing import CliRunner

    import nodrix.cli_operation_commands as commands
    from nodrix.cli import app

    source = (
        tmp_path
        / "ambiguous.yaml"
    )

    source.write_text(
        "name: ambiguous\n",
        encoding="utf-8",
    )

    legacy_calls = 0

    def unexpected_legacy(
        *args,
        **kwargs,
    ):
        nonlocal legacy_calls

        del args
        del kwargs

        legacy_calls += 1

        raise AssertionError(
            "legacy Benchmark execution "
            "must not be selected implicitly"
        )

    monkeypatch.setattr(
        commands,
        "execute_benchmark_operation",
        unexpected_legacy,
    )

    result = CliRunner().invoke(
        app,
        [
            "benchmark",
            str(source),
            "--repeat",
            "1",
            "--warmup",
            "0",
        ],
    )

    assert result.exit_code == 1

    assert (
        "--mode is required"
        in result.output
    )

    assert legacy_calls == 0


def test_benchmark_system_mode_routes_to_canonical_system_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from typer.testing import CliRunner

    import nodrix.cli_operation_commands as commands
    from nodrix.cli import app

    source = (
        tmp_path
        / "system.yaml"
    )

    source.write_text(
        "name: canonical-system\n",
        encoding="utf-8",
    )

    legacy_calls = 0
    canonical_calls = []

    def unexpected_legacy(
        *args,
        **kwargs,
    ):
        nonlocal legacy_calls

        del args
        del kwargs

        legacy_calls += 1

        raise AssertionError(
            "canonical System Benchmark "
            "must never fall back to legacy"
        )

    def execute_system(
        plan,
    ):
        canonical_calls.append(
            plan
        )

        return {
            "schema": (
                "nodrix.benchmark-system-cli/v1"
            ),
            "mode": "system",
            "benchmark_plan_id": (
                "plan_test"
            ),
            "benchmark_subject": (
                "nodrix://benchmark/project/test"
            ),
            "benchmark_revision": (
                "nodrix://benchmark/project/"
                "test@sha256:"
                + "0" * 64
            ),
            "warmup_run_ids": [],
            "measured_run_ids": [
                "run_test"
            ],
            "artifacts": [
                {
                    "kind": "benchmark.result",
                    "uri": (
                        "artifacts/benchmarks/"
                        "result.json"
                    ),
                },
            ],
        }

    monkeypatch.setattr(
        commands,
        "execute_benchmark_operation",
        unexpected_legacy,
    )

    monkeypatch.setattr(
        commands,
        "_execute_canonical_benchmark_cli",
        execute_system,
    )

    result = CliRunner().invoke(
        app,
        [
            "benchmark",
            str(
                source
            ),
            "--mode",
            "system",
            "--repeat",
            "1",
            "--warmup",
            "0",
            "--json",
        ],
    )

    assert (
        result.exit_code
        == 0
    ), result.output

    assert legacy_calls == 0

    assert len(
        canonical_calls
    ) == 1

    plan = canonical_calls[
        0
    ]

    assert (
        plan.pipeline.resolve()
        == source.resolve()
    )

    assert plan.repeat == 1
    assert plan.warmup == 0

    summary = json.loads(
        result.stdout
    )

    assert (
        summary[
            "mode"
        ]
        == "system"
    )

    assert (
        summary[
            "benchmark_plan_id"
        ]
        == "plan_test"
    )


def test_benchmark_system_mode_rejects_legacy_set_and_block(
    tmp_path: Path,
) -> None:
    from typer.testing import CliRunner

    from nodrix.cli import app

    source = (
        tmp_path
        / "system.yaml"
    )

    source.write_text(
        "name: system\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "benchmark",
            str(
                source
            ),
            "--mode",
            "system",
            "--set",
            "x=1",
        ],
    )

    assert result.exit_code == 1

    assert (
        "--set and --block are legacy"
        in result.output
    )


def test_benchmark_system_mode_rejects_legacy_output_override(
    tmp_path: Path,
) -> None:
    from typer.testing import CliRunner

    from nodrix.cli import app

    source = (
        tmp_path
        / "system.yaml"
    )

    source.write_text(
        "name: system\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "benchmark",
            str(
                source
            ),
            "--mode",
            "system",
            "--output",
            str(
                tmp_path
                / "custom"
            ),
        ],
    )

    assert result.exit_code == 1

    assert (
        "--output is currently legacy-only"
        in result.output
    )



def test_canonical_benchmark_cli_frontend_uses_project_storage_and_reusable_layers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    import nodrix.cli_operation_commands as commands

    source_dir = (
        tmp_path
        / "systems"
    )

    source_dir.mkdir()

    source = (
        source_dir
        / "system.yaml"
    )

    source.write_text(
        "name: benchmark-system\n",
        encoding="utf-8",
    )

    plan = (
        commands.direct_benchmark_plan(
            source,
            repeat=1,
            warmup=0,
        )
    )

    project_root = (
        tmp_path.resolve()
    )

    runs_root = (
        project_root
        / ".nodrix"
        / "runs"
    )

    captured = {}

    monkeypatch.setattr(
        commands,
        "find_workspace",
        lambda start: (
            project_root
        ),
    )

    class FakeLayout:
        def __init__(
            self,
            root,
        ) -> None:
            captured[
                "layout_root"
            ] = Path(
                root
            ).resolve()

            self.runs_root = (
                runs_root
            )

    class FakeRunStore:
        def __init__(
            self,
            root,
        ) -> None:
            captured[
                "run_store_root"
            ] = Path(
                root
            ).resolve()

    class FakeResolver:
        def __init__(
            self,
            *,
            orchestrator_factory,
            catalog_provider=None,
            execution_policy=None,
        ) -> None:
            captured[
                "orchestrator_factory"
            ] = orchestrator_factory

            captured[
                "catalog_provider"
            ] = catalog_provider

            captured[
                "execution_policy"
            ] = execution_policy

    class FakeRunner:
        def __init__(
            self,
            *,
            workload_resolver,
            run_store,
            **kwargs,
        ) -> None:
            captured[
                "runner_resolver"
            ] = workload_resolver

            captured[
                "runner_store"
            ] = run_store

            captured[
                "runner_kwargs"
            ] = kwargs

    orchestrator = object()

    def build_orchestrator(
        value,
        *,
        project=None,
        working_directory=None,
        run_root=None,
        stop_timeout_seconds=10.0,
    ):
        captured[
            "orchestrator_plan"
        ] = value

        captured[
            "orchestrator_project"
        ] = project

        captured[
            "orchestrator_working_directory"
        ] = working_directory

        captured[
            "orchestrator_run_root"
        ] = run_root

        captured[
            "orchestrator_stop_timeout_seconds"
        ] = stop_timeout_seconds

        return orchestrator

    execution = SimpleNamespace(
        plan=SimpleNamespace(
            plan_id=(
                "plan_benchmark_test"
            ),
            operation=SimpleNamespace(
                subject=SimpleNamespace(
                    canonical=(
                        "nodrix://benchmark/"
                        "project/test"
                    ),
                ),
            ),
            subject_revision=(
                SimpleNamespace(
                    canonical=(
                        "nodrix://benchmark/"
                        "project/test@sha256:"
                        + "0" * 64
                    ),
                )
            ),
        ),
        warmup_run_ids=(
            "run_warmup",
        ),
        measured_run_ids=(
            "run_measured",
        ),
        artifacts=(
            SimpleNamespace(
                kind="benchmark.result",
                uri=(
                    "artifacts/benchmarks/"
                    "result.json"
                ),
            ),
        ),
    )

    coordinator_calls = []

    def execute(
        received_plan,
        *,
        runner,
        project,
    ):
        coordinator_calls.append(
            (
                received_plan,
                runner,
                Path(
                    project
                ).resolve(),
            )
        )

        return execution

    monkeypatch.setattr(
        commands,
        "StorageLayout",
        FakeLayout,
    )

    monkeypatch.setattr(
        commands,
        "RunStore",
        FakeRunStore,
    )

    monkeypatch.setattr(
        commands,
        "CanonicalBenchmarkSystemWorkloadResolver",
        FakeResolver,
    )

    monkeypatch.setattr(
        commands,
        "CanonicalSystemBenchmarkRunner",
        FakeRunner,
    )

    monkeypatch.setattr(
        commands,
        "build_local_system_orchestrator",
        build_orchestrator,
    )

    monkeypatch.setattr(
        commands,
        "execute_canonical_system_benchmark",
        execute,
    )

    summary = (
        commands
        ._execute_canonical_benchmark_cli(
            plan
        )
    )

    assert (
        captured[
            "layout_root"
        ]
        == project_root
    )

    assert (
        captured[
            "run_store_root"
        ]
        == runs_root
    )

    assert (
        captured[
            "catalog_provider"
        ]
        is commands
        .local_project_definition_catalog
    )

    assert len(
        coordinator_calls
    ) == 1

    received_plan, _, received_project = (
        coordinator_calls[
            0
        ]
    )

    assert (
        received_plan
        is plan
    )

    assert (
        received_project
        == project_root
    )

    resolved = SimpleNamespace(
        project_root=project_root,
        source=source,
        plan="SYSTEM_PLAN",
    )

    created = (
        captured[
            "orchestrator_factory"
        ](
            resolved
        )
    )

    assert (
        created
        is orchestrator
    )

    assert (
        captured[
            "orchestrator_plan"
        ]
        == "SYSTEM_PLAN"
    )

    assert (
        captured[
            "orchestrator_project"
        ]
        == project_root
    )

    assert (
        Path(
            captured[
                "orchestrator_working_directory"
            ]
        ).resolve()
        == project_root
    )

    assert (
        Path(
            captured[
                "orchestrator_run_root"
            ]
        ).resolve()
        == runs_root
    )

    assert (
        summary[
            "schema"
        ]
        == "nodrix.benchmark-system-cli/v1"
    )

    assert (
        summary[
            "mode"
        ]
        == "system"
    )

    assert (
        summary[
            "benchmark_plan_id"
        ]
        == "plan_benchmark_test"
    )

    assert (
        summary[
            "warmup_run_ids"
        ]
        == [
            "run_warmup"
        ]
    )

    assert (
        summary[
            "measured_run_ids"
        ]
        == [
            "run_measured"
        ]
    )

    assert (
        summary[
            "artifacts"
        ]
        == [
            {
                "kind": (
                    "benchmark.result"
                ),
                "uri": (
                    "artifacts/benchmarks/"
                    "result.json"
                ),
            },
        ]
    )


def test_canonical_benchmark_cli_orchestrator_rejects_cross_project_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    import pytest

    import nodrix.cli_operation_commands as commands

    source = (
        tmp_path
        / "system.yaml"
    )

    source.write_text(
        "name: benchmark-system\n",
        encoding="utf-8",
    )

    plan = (
        commands.direct_benchmark_plan(
            source,
            repeat=1,
            warmup=0,
        )
    )

    project_root = (
        tmp_path.resolve()
    )

    captured = {}

    monkeypatch.setattr(
        commands,
        "find_workspace",
        lambda start: (
            project_root
        ),
    )

    class FakeLayout:
        def __init__(
            self,
            root,
        ) -> None:
            self.runs_root = (
                Path(root)
                / ".nodrix"
                / "runs"
            )

    class FakeRunStore:
        def __init__(
            self,
            root,
        ) -> None:
            self.root = root

    class FakeResolver:
        def __init__(
            self,
            *,
            orchestrator_factory,
            **kwargs,
        ) -> None:
            del kwargs

            captured[
                "factory"
            ] = orchestrator_factory

    class FakeRunner:
        def __init__(
            self,
            **kwargs,
        ) -> None:
            self.kwargs = kwargs

    execution = SimpleNamespace(
        plan=SimpleNamespace(
            plan_id="plan_test",
            operation=SimpleNamespace(
                subject=SimpleNamespace(
                    canonical=(
                        "nodrix://benchmark/"
                        "project/test"
                    ),
                ),
            ),
            subject_revision=(
                SimpleNamespace(
                    canonical=(
                        "nodrix://benchmark/"
                        "project/test@sha256:"
                        + "0" * 64
                    ),
                )
            ),
        ),
        warmup_run_ids=(),
        measured_run_ids=(),
        artifacts=(),
    )

    monkeypatch.setattr(
        commands,
        "StorageLayout",
        FakeLayout,
    )

    monkeypatch.setattr(
        commands,
        "RunStore",
        FakeRunStore,
    )

    monkeypatch.setattr(
        commands,
        "CanonicalBenchmarkSystemWorkloadResolver",
        FakeResolver,
    )

    monkeypatch.setattr(
        commands,
        "CanonicalSystemBenchmarkRunner",
        FakeRunner,
    )

    monkeypatch.setattr(
        commands,
        "execute_canonical_system_benchmark",
        (
            lambda plan, runner, project: (
                execution
            )
        ),
    )

    commands._execute_canonical_benchmark_cli(
        plan
    )

    other_project = (
        tmp_path
        / "other-project"
    ).resolve()

    resolved = SimpleNamespace(
        project_root=other_project,
        source=(
            other_project
            / "system.yaml"
        ),
        plan="SYSTEM_PLAN",
    )

    with pytest.raises(
        ValueError,
        match=(
            "same project root"
        ),
    ):
        captured[
            "factory"
        ](
            resolved
        )
