"""End-to-end canonical System Benchmark execution coordination.

This module composes already-existing canonical contracts:

BenchmarkPlan
    -> ordinary canonical System Runs
    -> measured Run set
    -> strict Benchmark aggregation
    -> Benchmark Result Artifacts

It deliberately does not resolve authoring inputs, construct backends, measure
runtime duration or persist a separate BenchmarkRun.  Those responsibilities
belong to their existing layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .benchmark_canonical_suite import (
    assemble_canonical_benchmark_suite,
)
from .benchmark_measured_runs import (
    CanonicalBenchmarkRuns,
    execute_canonical_benchmark_runs,
)
from .benchmark_system_identity import (
    CanonicalBenchmarkWorkloadSet,
    canonical_system_benchmark_plan_record,
)
from .benchmark_system_runner import (
    CanonicalSystemBenchmarkRunner,
)
from .benchmarking import (
    BenchmarkPlan,
)
from .model import (
    BENCHMARK_PLAN,
    ArtifactRecord,
    PlanRecord,
)


class CanonicalSystemBenchmarkExecutionError(
    RuntimeError
):
    """Canonical System Benchmark coordination contract was violated."""


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalSystemBenchmarkExecution:
    """Structured result of one complete canonical System Benchmark suite.

    ``runs`` contains both warmup and measured ordinary Runs.

    ``artifacts`` contains only canonical Benchmark Result artifacts assembled
    from measured Runs. Warmup Runs remain historical execution evidence but
    never participate in performance aggregation.
    """

    plan: PlanRecord
    runs: CanonicalBenchmarkRuns
    suite: object
    artifacts: tuple[
        ArtifactRecord,
        ...,
    ]

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.plan,
            PlanRecord,
        ):
            raise TypeError(
                "plan must be a PlanRecord"
            )

        if (
            self.plan.kind
            != BENCHMARK_PLAN
        ):
            raise ValueError(
                "canonical System Benchmark execution "
                "requires a benchmark PlanRecord"
            )

        if not isinstance(
            self.runs,
            CanonicalBenchmarkRuns,
        ):
            raise TypeError(
                "runs must be CanonicalBenchmarkRuns"
            )

        if not isinstance(
            self.artifacts,
            tuple,
        ):
            raise TypeError(
                "artifacts must be a tuple"
            )

        if not all(
            isinstance(
                artifact,
                ArtifactRecord,
            )
            for artifact
            in self.artifacts
        ):
            raise TypeError(
                "artifacts must contain "
                "ArtifactRecord values"
            )

    @property
    def warmup_run_ids(
        self,
    ) -> tuple[
        str,
        ...,
    ]:
        return tuple(
            bundle.session.run_id
            for variant
            in self.runs.variants
            for bundle
            in variant.warmup
        )

    @property
    def measured_run_ids(
        self,
    ) -> tuple[
        str,
        ...,
    ]:
        return tuple(
            bundle.session.run_id
            for variant
            in self.runs.variants
            for bundle
            in variant.measured
        )


def execute_canonical_system_benchmark(
    plan: BenchmarkPlan,
    *,
    runner: CanonicalSystemBenchmarkRunner,
    project: str | Path,
) -> CanonicalSystemBenchmarkExecution:
    """Execute one BenchmarkPlan entirely through canonical System Runs.

    Benchmark identity and Run execution are derived from the exact same
    workload resolver owned by ``runner``.

    The coordinator deliberately does not accept an externally constructed
    Benchmark PlanRecord. Allowing that would permit Benchmark provenance to
    describe different System Plans from those actually executed.
    """

    if not isinstance(
        plan,
        BenchmarkPlan,
    ):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    if not isinstance(
        runner,
        CanonicalSystemBenchmarkRunner,
    ):
        raise TypeError(
            "runner must be a "
            "CanonicalSystemBenchmarkRunner"
        )

    resolver = (
        runner.workload_resolver
    )

    workload_set_method = getattr(
        resolver,
        "workload_set",
        None,
    )

    if not callable(
        workload_set_method
    ):
        raise TypeError(
            "canonical System Benchmark runner "
            "workload_resolver must expose "
            "workload_set(plan)"
        )

    workload_set = (
        workload_set_method(
            plan
        )
    )

    if not isinstance(
        workload_set,
        CanonicalBenchmarkWorkloadSet,
    ):
        raise TypeError(
            "workload_resolver.workload_set(plan) "
            "must return "
            "CanonicalBenchmarkWorkloadSet"
        )

    canonical_plan = (
        canonical_system_benchmark_plan_record(
            plan,
            workload_set=workload_set,
        )
    )

    project_root = (
        Path(
            project
        )
        .expanduser()
        .resolve()
    )

    runs = (
        execute_canonical_benchmark_runs(
            plan,
            run_callable=runner,
        )
    )

    if (
        len(
            runs.variants
        )
        != len(
            plan.variants
        )
    ):
        raise CanonicalSystemBenchmarkExecutionError(
            "measured-run coordinator returned "
            "a different variant count"
        )

    # Benchmark Result assembly consumes measured evidence only. Warmup Runs
    # remain ordinary persisted Runs but are intentionally excluded here.
    measured_runs = {
        configured.name: tuple(
            executed.measured
        )
        for configured, executed
        in zip(
            plan.variants,
            runs.variants,
            strict=True,
        )
    }

    suite = (
        assemble_canonical_benchmark_suite(
            canonical_plan,
            measured_runs=measured_runs,
            project=project_root,
        )
    )

    raw_artifacts = getattr(
        suite,
        "artifacts",
        None,
    )

    if raw_artifacts is None:
        raise CanonicalSystemBenchmarkExecutionError(
            "canonical Benchmark suite did not "
            "expose result artifacts"
        )

    try:
        artifacts = tuple(
            raw_artifacts
        )
    except TypeError as exc:
        raise (
            CanonicalSystemBenchmarkExecutionError(
                "canonical Benchmark suite artifacts "
                "must be iterable"
            )
        ) from exc

    if not all(
        isinstance(
            artifact,
            ArtifactRecord,
        )
        for artifact
        in artifacts
    ):
        raise CanonicalSystemBenchmarkExecutionError(
            "canonical Benchmark suite returned "
            "non-ArtifactRecord outputs"
        )

    return CanonicalSystemBenchmarkExecution(
        plan=canonical_plan,
        runs=runs,
        suite=suite,
        artifacts=artifacts,
    )


__all__ = [
    "CanonicalSystemBenchmarkExecution",
    "CanonicalSystemBenchmarkExecutionError",
    "execute_canonical_system_benchmark",
]
