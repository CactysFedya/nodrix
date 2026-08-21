from __future__ import annotations

from pathlib import Path

import pytest

from nodrix.benchmark_system_execution import (
    execute_canonical_system_benchmark,
)
from nodrix.benchmark_system_identity import (
    canonical_benchmark_workload_set,
)
from nodrix.benchmark_system_runner import (
    CanonicalSystemBenchmarkRunner,
    CanonicalSystemBenchmarkWorkload,
)
from nodrix.benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from nodrix.run_session import (
    RunStore,
)
from nodrix.system import (
    BackendCapabilities,
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    ExecutionTiming,
    Graph,
    NodeInstance,
    PreparedExecution,
    SystemModel,
    SystemOrchestrator,
    Target,
    plan_system,
)
from nodrix.system.canonical import (
    system_plan_record,
)


def _system() -> SystemModel:
    return SystemModel(
        name="benchmark-end-to-end",
        targets=(
            Target(
                name="host",
                kind="host",
                properties={
                    "backend": "local",
                },
            ),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                        target="host",
                    ),
                ),
            ),
        ),
    )


class CompletingBackend(
    ExecutionBackend
):
    def __init__(
        self,
        *,
        duration_seconds: float,
    ) -> None:
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds={
                    "host",
                },
            ),
        )

        self.duration_seconds = (
            duration_seconds
        )

    def _prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        return PreparedExecution(
            backend=self.backend_id,
            context=context,
        )

    def _start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id="benchmark-backend",
            prepared=prepared,
        )

    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=(
                handle.execution_id
            ),
            state=(
                BackendExecutionState.COMPLETED
            ),
            timing=ExecutionTiming(
                self.duration_seconds
            ),
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        del timeout_seconds

        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=(
                handle.execution_id
            ),
            state=(
                BackendExecutionState.STOPPED
            ),
            timing=ExecutionTiming(
                self.duration_seconds
            ),
        )


def _domain_plan(
    tmp_path: Path,
    *,
    repeat: int = 2,
    warmup: int = 1,
) -> BenchmarkPlan:
    source = (
        tmp_path
        / "system.yaml"
    )

    source.write_text(
        "# canonical System test source\n",
        encoding="utf-8",
    )

    return BenchmarkPlan(
        pipeline=source,
        repeat=repeat,
        warmup=warmup,
        variants=(
            BenchmarkVariant(
                "default"
            ),
        ),
    )




def test_end_to_end_system_benchmark_produces_runs_and_result_artifact(
    tmp_path,
) -> None:
    benchmark_plan = (
        _domain_plan(
            tmp_path
        )
    )

    system = _system()

    system_plan = (
        system_plan_record(
            plan_system(
                system
            )
        )
    )

    durations = iter(
        (
            # warmup
            99.0,
            # measured
            3.0,
            5.0,
        )
    )

    class Resolver:
        def workload_set(
            self,
            plan,
        ):
            return canonical_benchmark_workload_set(
                plan,
                variant_plans={
                    "default": system_plan,
                },
            )

        def __call__(
            self,
            request,
        ) -> CanonicalSystemBenchmarkWorkload:
            del request

            backend = CompletingBackend(
                duration_seconds=next(
                    durations
                )
            )

            return CanonicalSystemBenchmarkWorkload(
                system_definition=system,
                plan=system_plan,
                orchestrator=(
                    SystemOrchestrator(
                        {
                            (
                                "host",
                                "local",
                            ): backend,
                        }
                    )
                ),
            )

    resolve = Resolver()

    runner = (
        CanonicalSystemBenchmarkRunner(
            workload_resolver=resolve,
            run_store=RunStore(
                tmp_path
                / ".nodrix"
                / "runs"
            ),
            # All synthetic executions are terminal at first inspection.
            sleeper=lambda delay: None,
        )
    )

    result = (
        execute_canonical_system_benchmark(
            benchmark_plan,
            runner=runner,
            project=tmp_path,
        )
    )

    assert (
        result.plan.operation.subject.kind
        == "benchmark"
    )

    assert (
        result.plan.subject_revision
        == result.plan.operation.subject_revision
    )

    assert (
        result.plan.metadata[
            "benchmark_workload_set"
        ]
        == result.plan.subject_revision.canonical
    )

    assert len(
        result.warmup_run_ids
    ) == 1

    assert len(
        result.measured_run_ids
    ) == 2

    assert len(
        set(
            result.warmup_run_ids
            + result.measured_run_ids
        )
    ) == 3

    assert len(
        result.artifacts
    ) == 1

    artifact = result.artifacts[
        0
    ]

    assert (
        artifact.kind
        == "benchmark.result"
    )

    # ArtifactRecord.uri is intentionally project-relative so historical
    # records remain portable across machines and workspace locations.
    payload_path = (
        tmp_path
        / artifact.uri
    )

    assert payload_path.is_file()

    # Warmup duration=99 must never enter the measured result.
    variant = result.runs.variants[
        0
    ]

    assert len(
        variant.warmup
    ) == 1

    assert len(
        variant.measured
    ) == 2

    measured_durations = tuple(
        bundle.run[
            "execution"
        ][
            "details"
        ][
            "execution_timing"
        ][
            "duration_seconds"
        ]
        for bundle
        in variant.measured
    )

    assert measured_durations == (
        3.0,
        5.0,
    )


def test_canonical_system_benchmark_requires_identity_capable_resolver(
    tmp_path,
) -> None:
    benchmark_plan = (
        _domain_plan(
            tmp_path
        )
    )

    system = _system()

    system_plan = (
        system_plan_record(
            plan_system(
                system
            )
        )
    )

    def run_only_resolver(
        request,
    ) -> CanonicalSystemBenchmarkWorkload:
        raise AssertionError(
            "Run execution must not start before "
            "Benchmark workload-set identity exists"
        )

    runner = (
        CanonicalSystemBenchmarkRunner(
            workload_resolver=(
                run_only_resolver
            ),
            run_store=RunStore(
                tmp_path
                / ".nodrix"
                / "runs"
            ),
            sleeper=lambda delay: None,
        )
    )

    with pytest.raises(
        TypeError,
        match=(
            r"workload_resolver must expose "
            r"workload_set\(plan\)"
        ),
    ):
        execute_canonical_system_benchmark(
            benchmark_plan,
            runner=runner,
            project=tmp_path,
        )

    # Keep this reference explicit: the failure above is about Benchmark
    # identity capability, not an invalid System execution Plan.
    assert (
        system_plan.operation.subject.kind
        == "system"
    )
