"""Unified canonical execution service for benchmark operations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping

from .benchmark_canonical import benchmark_plan_record
from .benchmark_executor import BenchmarkExecutor
from .benchmarking import BenchmarkPlan, RunCallable
from .execution_history import PersistedRun, persist_execution
from .model import (
    BENCHMARK,
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RevisionRef,
)


def _pipeline_digest(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def benchmark_subject(
    plan: BenchmarkPlan,
) -> tuple[EntityRef, RevisionRef]:
    """Return the canonical identity of the benchmarked pipeline definition."""

    if not isinstance(plan, BenchmarkPlan):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    pipeline = plan.pipeline.resolve()

    entity = EntityRef(
        kind="pipeline",
        namespace="workspace",
        name=pipeline.stem,
    )

    revision = RevisionRef.from_sha256(
        entity,
        _pipeline_digest(pipeline),
    )

    return entity, revision


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

    history = persist_execution(
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
        history=history,
    )


__all__ = [
    "BenchmarkOperationResult",
    "benchmark_operation",
    "benchmark_subject",
    "execute_benchmark_operation",
]
