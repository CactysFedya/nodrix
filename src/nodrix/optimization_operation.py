"""Unified canonical execution service for optimization operations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from .benchmark_executor import BenchmarkExecutor
from .benchmark_operation import benchmark_subject
from .benchmarking import RunCallable
from .execution_history import (
    PersistedRun,
)
from .foreground_operation import (
    persist_foreground_execution,
)
from .model import (
    OPTIMIZE,
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RevisionRef,
)
from .optimization import (
    OptimizationPlan,
    write_optimization_plan,
)
from .optimization_canonical import (
    optimization_plan_record,
)
from .optimization_executor import (
    OptimizationExecutor,
)
from .storage_layout import StorageLayout


def optimization_subject(
    plan: OptimizationPlan,
) -> tuple[EntityRef, RevisionRef]:
    """Return the canonical identity of the targeted 2.x Pipeline Definition."""

    if not isinstance(
        plan,
        OptimizationPlan,
    ):
        raise TypeError(
            "plan must be an OptimizationPlan"
        )

    return benchmark_subject(
        plan.benchmark_plan
    )


def optimization_operation(
    plan: OptimizationPlan,
    *,
    run_benchmarks: bool,
) -> Operation:
    """Create the canonical OPTIMIZE operation represented by a plan."""

    if not isinstance(
        plan,
        OptimizationPlan,
    ):
        raise TypeError(
            "plan must be an OptimizationPlan"
        )

    if not isinstance(
        run_benchmarks,
        bool,
    ):
        raise TypeError(
            "run_benchmarks must be a boolean"
        )

    entity, revision = (
        optimization_subject(plan)
    )

    return Operation(
        kind=OPTIMIZE,
        subject=entity,
        subject_revision=revision,
        parameters={
            "run_benchmarks": (
                run_benchmarks
            ),
            "objectives": dict(
                plan.objectives
            ),
            "constraints": dict(
                plan.constraints
            ),
        },
    )


@dataclass(frozen=True, slots=True)
class OptimizationOperationResult:
    """Canonical result of one optimization operation."""

    plan: PlanRecord
    execution: ExecutionRecord
    history: PersistedRun
    spec_path: Path
    report_path: Path
    result: Mapping[str, Any]

    @property
    def successful(self) -> bool:
        return self.execution.successful

    def summary(self) -> dict[str, Any]:
        return dict(
            self.result
        )


def execute_optimization_operation(
    plan: OptimizationPlan,
    *,
    run_benchmarks: bool,
    run_callable: RunCallable | None = None,
    output_dir: str | Path | None = None,
    history_root: str | Path | None = None,
    executor: OptimizationExecutor | None = None,
) -> OptimizationOperationResult:
    """Execute and persist one canonical OPTIMIZE operation."""

    if not isinstance(
        plan,
        OptimizationPlan,
    ):
        raise TypeError(
            "plan must be an OptimizationPlan"
        )

    if not isinstance(
        run_benchmarks,
        bool,
    ):
        raise TypeError(
            "run_benchmarks must be a boolean"
        )

    # Resolve the requested execution policy into the exact domain Plan
    # before canonical planning and execution.
    plan = replace(
        plan,
        run_benchmarks=run_benchmarks,
    )

    artifact_root = (
        Path(output_dir)
        .expanduser()
        .resolve()
        if output_dir is not None
        else StorageLayout(
            plan.pipeline.parent
        ).optimization_root
    )

    # Materialize the exact plan before execution.  This preserves the
    # historical optimization artifacts even when measurement later fails.
    spec_path, report_path, result = (
        write_optimization_plan(
            plan,
            artifact_root,
        )
    )

    operation = optimization_operation(
        plan,
        run_benchmarks=plan.run_benchmarks,
    )

    revision = (
        operation.subject_revision
    )

    assert revision is not None

    canonical_plan = (
        optimization_plan_record(
            plan,
            operation=operation,
            subject_revision=revision,
            metadata={
                "operation_source": (
                    "optimization"
                ),
                "spec_path": str(
                    spec_path
                ),
                "report_path": str(
                    report_path
                ),
            },
        )
    )

    if executor is not None:
        selected_executor = executor
    else:
        benchmark_executor = None

        if plan.run_benchmarks:
            if run_callable is None:
                raise ValueError(
                    "run_benchmarks requires "
                    "a run_callable"
                )

            benchmark_executor = (
                BenchmarkExecutor(
                    run_callable=run_callable
                )
            )

        selected_executor = (
            OptimizationExecutor(
                benchmark_executor=(
                    benchmark_executor
                )
            )
        )

    execution = selected_executor.execute(
        canonical_plan,
        output_root=(
            artifact_root / "benchmarks"
            if plan.run_benchmarks
            else None
        ),
    )

    benchmark = (
        execution.details.get(
            "benchmark"
        )
    )

    recommendation = (
        execution.details.get(
            "recommendation"
        )
    )

    benchmark_mapping = (
        benchmark
        if isinstance(
            benchmark,
            Mapping,
        )
        else None
    )

    recommendation_mapping = (
        recommendation
        if isinstance(
            recommendation,
            Mapping,
        )
        else None
    )

    # Successful measured optimization updates the public decision report
    # from the exact same OptimizationPlan and embedded benchmark result.
    if benchmark_mapping is not None:
        spec_path, report_path, result = (
            write_optimization_plan(
                plan,
                artifact_root,
                benchmark=(
                    benchmark_mapping
                ),
                recommendation=(
                    recommendation_mapping
                ),
            )
        )

    selected_variant = (
        recommendation_mapping.get(
            "selected"
        )
        if recommendation_mapping
        is not None
        else None
    )

    outcome = persist_foreground_execution(
        canonical_plan,
        execution,
        project=(
            Path(history_root)
            .expanduser()
            .resolve()
            if history_root
            is not None
            else plan.pipeline.parent
        ),
        summary={
            "optimization_status": (
                execution.state.value
            ),
            "optimization_schema": (
                result.get("schema")
            ),
            "variant_count": len(
                plan.variants
            ),
            "run_benchmarks": (
                plan.run_benchmarks
            ),
            "benchmark_suite_dir": (
                execution.details.get(
                    "benchmark_suite_dir"
                )
            ),
            "recommended_variant": (
                selected_variant
            ),
            "spec_path": str(
                spec_path
            ),
            "report_path": str(
                report_path
            ),
        },
    )

    return OptimizationOperationResult(
        plan=canonical_plan,
        execution=execution,
        history=outcome.history,
        spec_path=spec_path,
        report_path=report_path,
        result=result,
    )


__all__ = [
    "OptimizationOperationResult",
    "execute_optimization_operation",
    "optimization_operation",
    "optimization_subject",
]
