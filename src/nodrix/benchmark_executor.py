"""Canonical executor for benchmark plans."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from .benchmarking import (
    BenchmarkPlan,
    RunCallable,
    run_benchmark_suite,
)
from .model import (
    BENCHMARK_PLAN,
    ExecutionRecord,
    ExecutionState,
    PlanRecord,
)


BENCHMARK_EXECUTOR = "nodrix.benchmark"

BenchmarkSuiteRunner = Callable[
    [BenchmarkPlan, RunCallable],
    Mapping[str, Any],
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _execution_id() -> str:
    return f"benchmark-{uuid4().hex[:12]}"


class BenchmarkExecutor:
    """Execute canonical benchmark PlanRecords."""

    def __init__(
        self,
        *,
        run_callable: RunCallable,
        suite_runner: Callable[..., Mapping[str, Any]] = run_benchmark_suite,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = _execution_id,
    ) -> None:
        if not callable(run_callable):
            raise TypeError(
                "run_callable must be callable"
            )

        if not callable(suite_runner):
            raise TypeError(
                "suite_runner must be callable"
            )

        self._run_callable = run_callable
        self._suite_runner = suite_runner
        self._clock = clock
        self._id_factory = id_factory

    @property
    def executor_id(self) -> str:
        return BENCHMARK_EXECUTOR

    def execute(
        self,
        plan: PlanRecord,
        *,
        output_root: str | Path | None = None,
    ) -> ExecutionRecord:
        if not isinstance(plan, PlanRecord):
            raise TypeError(
                "plan must be a PlanRecord"
            )

        if plan.kind != BENCHMARK_PLAN:
            raise ValueError(
                "BenchmarkExecutor requires a benchmark PlanRecord"
            )

        domain_plan = plan.payload

        if not isinstance(
            domain_plan,
            BenchmarkPlan,
        ):
            raise TypeError(
                "benchmark PlanRecord payload must be a BenchmarkPlan"
            )

        execution_id = self._id_factory()
        started_at = self._clock()

        try:
            suite = dict(
                self._suite_runner(
                    domain_plan,
                    self._run_callable,
                    output_root=output_root,
                )
            )
        except Exception as exc:
            finished_at = self._clock()

            return ExecutionRecord(
                execution_id=execution_id,
                plan=plan,
                executor=self.executor_id,
                state=ExecutionState.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                details={
                    "pipeline": str(
                        domain_plan.pipeline
                    ),
                    "repeat": domain_plan.repeat,
                    "warmup": domain_plan.warmup,
                    "variant_count": len(
                        domain_plan.variants
                    ),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )

        finished_at = self._clock()

        return ExecutionRecord(
            execution_id=execution_id,
            plan=plan,
            executor=self.executor_id,
            state=ExecutionState.COMPLETED,
            started_at=started_at,
            finished_at=finished_at,
            details={
                "pipeline": str(
                    domain_plan.pipeline
                ),
                "repeat": domain_plan.repeat,
                "warmup": domain_plan.warmup,
                "variant_count": len(
                    domain_plan.variants
                ),
                "variants": [
                    variant.name
                    for variant
                    in domain_plan.variants
                ],
                "benchmark_schema": suite.get(
                    "schema"
                ),
                "suite_dir": suite.get(
                    "suite_dir"
                ),
                "suite": suite,
            },
        )


__all__ = [
    "BENCHMARK_EXECUTOR",
    "BenchmarkExecutor",
]
