"""Unified canonical execution service for benchmark operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .benchmark_canonical import benchmark_plan_record
from .benchmark_executor import BenchmarkExecutor
from .benchmarking import BenchmarkPlan, RunCallable
from .execution_history import PersistedRun
from .foreground_operation import (
    persist_foreground_execution,
)
from .model import (
    BENCHMARK,
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RevisionRef,
)
from .pipeline_definition import (
    pipeline_source_identity,
)


def benchmark_subject(
    plan: BenchmarkPlan,
) -> tuple[EntityRef, RevisionRef]:
    """Return the canonical source identity of the benchmarked Pipeline."""

    if not isinstance(
        plan,
        BenchmarkPlan,
    ):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    return pipeline_source_identity(
        plan.pipeline
    )


def benchmark_operation(
    plan: BenchmarkPlan,
) -> Operation:
    """Create the canonical BENCHMARK operation represented by a plan."""

    entity, revision = benchmark_subject(plan)

    return Operation(
        kind=BENCHMARK,
        subject=entity,
        subject_revision=revision,
        parameters={
            "repeat": plan.repeat,
            "warmup": plan.warmup,
            "variants": [
                {
                    "name": variant.name,
                    "profile": variant.profile,
                    "set": list(variant.set_values),
                    "block": list(variant.block_values),
                }
                for variant in plan.variants
            ],
        },
    )


@dataclass(frozen=True, slots=True)
class BenchmarkOperationResult:
    """Canonical result of one benchmark operation."""

    plan: PlanRecord
    execution: ExecutionRecord
    history: PersistedRun

    @property
    def successful(self) -> bool:
        return self.execution.successful

    def summary(self) -> dict[str, Any]:
        raw = self.execution.details.get("suite")

        if not isinstance(raw, Mapping):
            return {}

        return dict(raw)


def execute_benchmark_operation(
    plan: BenchmarkPlan,
    *,
    run_callable: RunCallable,
    output_root: str | Path | None = None,
    history_root: str | Path | None = None,
    executor: BenchmarkExecutor | None = None,
) -> BenchmarkOperationResult:
    """Plan, execute and persist one canonical BENCHMARK operation."""

    if not isinstance(plan, BenchmarkPlan):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    operation = benchmark_operation(plan)

    revision = operation.subject_revision
    assert revision is not None

    canonical_plan = benchmark_plan_record(
        plan,
        operation=operation,
        subject_revision=revision,
        metadata={
            "operation_source": "benchmark",
        },
    )

    selected_executor = (
        executor
        if executor is not None
        else BenchmarkExecutor(
            run_callable=run_callable
        )
    )

    execution = selected_executor.execute(
        canonical_plan,
        output_root=output_root,
    )

    suite = execution.details.get("suite")
    suite_mapping = (
        dict(suite)
        if isinstance(suite, Mapping)
        else {}
    )

    outcome = persist_foreground_execution(
        canonical_plan,
        execution,
        project=(
            Path(history_root).expanduser().resolve()
            if history_root is not None
            else plan.pipeline.parent
        ),
        summary={
            "benchmark_status": execution.state.value,
            "benchmark_schema": execution.details.get(
                "benchmark_schema"
            ),
            "suite_dir": execution.details.get(
                "suite_dir"
            ),
            "repeat": plan.repeat,
            "warmup": plan.warmup,
            "variants": [
                variant.name
                for variant in plan.variants
            ],
            "suite_variant_count": len(
                dict(suite_mapping.get("variants") or {})
            ),
        },
    )

    return BenchmarkOperationResult(
        plan=canonical_plan,
        execution=execution,
        history=outcome.history,
    )


__all__ = [
    "BenchmarkOperationResult",
    "benchmark_operation",
    "benchmark_subject",
    "execute_benchmark_operation",
]
