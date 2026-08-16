"""Canonical executor for resolved Nodrix optimization plans."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from .benchmark_canonical import (
    benchmark_plan_record,
)
from .model import (
    BENCHMARK,
    OPTIMIZATION_PLAN,
    ExecutionRecord,
    ExecutionState,
    Operation,
    PlanRecord,
)
from .optimization import OptimizationPlan
from .planning import (
    select_optimization_variant,
)


OPTIMIZATION_EXECUTOR = "nodrix.optimization"

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _execution_id() -> str:
    return (
        f"optimization-"
        f"{uuid4().hex[:12]}"
    )


def _now(
    clock: Clock,
) -> datetime:
    value = clock()

    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(
            "clock result must be a datetime"
        )

    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            "clock result must be timezone-aware"
        )

    return value


def _validate_plan(
    plan: PlanRecord,
) -> OptimizationPlan:
    if not isinstance(
        plan,
        PlanRecord,
    ):
        raise TypeError(
            "plan must be a PlanRecord"
        )

    if (
        plan.kind
        != OPTIMIZATION_PLAN
    ):
        raise ValueError(
            "OptimizationExecutor requires "
            "an optimization PlanRecord"
        )

    if not isinstance(
        plan.payload,
        OptimizationPlan,
    ):
        raise TypeError(
            "optimization PlanRecord payload "
            "must be an OptimizationPlan"
        )

    return plan.payload


def _boolean_parameter(
    plan: PlanRecord,
    name: str,
    *,
    default: bool = False,
) -> bool:
    value = plan.operation.parameters.get(
        name,
        default,
    )

    if not isinstance(
        value,
        bool,
    ):
        raise TypeError(
            f"operation parameter {name!r} "
            "must be a boolean"
        )

    return value


def _base_details(
    plan: OptimizationPlan,
    *,
    run_benchmarks: bool,
) -> dict[str, Any]:
    return {
        "pipeline": str(
            plan.pipeline
        ),
        "pipeline_name": (
            plan.pipeline_name
        ),
        "run_benchmarks": (
            run_benchmarks
        ),
        "variant_count": len(
            plan.variants
        ),
        "variants": tuple(
            variant.name
            for variant
            in plan.variants
        ),
    }


class OptimizationExecutor:
    """Execute one exact optimization plan.

    Benchmarking is a nested canonical Execution, not a separately
    persisted top-level Run.
    """

    def __init__(
        self,
        *,
        benchmark_executor: object | None = None,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _execution_id,
    ) -> None:
        if (
            benchmark_executor is not None
            and not callable(
                getattr(
                    benchmark_executor,
                    "execute",
                    None,
                )
            )
        ):
            raise TypeError(
                "benchmark_executor must expose "
                "a callable execute()"
            )

        if not callable(clock):
            raise TypeError(
                "clock must be callable"
            )

        if not callable(
            id_factory
        ):
            raise TypeError(
                "id_factory must be callable"
            )

        self._benchmark_executor = (
            benchmark_executor
        )
        self._clock = clock
        self._id_factory = (
            id_factory
        )

    @property
    def executor_id(self) -> str:
        return OPTIMIZATION_EXECUTOR

    def execute(
        self,
        plan: PlanRecord,
        *,
        output_root: str | Path | None = None,
    ) -> ExecutionRecord:
        domain_plan = _validate_plan(
            plan
        )

        run_benchmarks = (
            _boolean_parameter(
                plan,
                "run_benchmarks",
            )
        )

        execution_id = (
            self._id_factory()
        )

        if not isinstance(
            execution_id,
            str,
        ) or not execution_id.strip():
            raise ValueError(
                "id_factory must return "
                "a non-empty string"
            )

        started_at = _now(
            self._clock
        )

        details = _base_details(
            domain_plan,
            run_benchmarks=run_benchmarks,
        )

        if not run_benchmarks:
            finished_at = _now(
                self._clock
            )

            return ExecutionRecord(
                execution_id=execution_id,
                plan=plan,
                executor=self.executor_id,
                state=ExecutionState.COMPLETED,
                started_at=started_at,
                finished_at=finished_at,
                details={
                    **details,
                    "recommendation": None,
                },
            )

        if (
            self._benchmark_executor
            is None
        ):
            raise ValueError(
                "run_benchmarks requires "
                "a benchmark_executor"
            )

        benchmark_operation = Operation(
            kind=BENCHMARK,
            subject=plan.operation.subject,
            subject_revision=(
                plan.subject_revision
            ),
        )

        benchmark_plan = (
            benchmark_plan_record(
                domain_plan.benchmark_plan,
                operation=benchmark_operation,
                subject_revision=(
                    plan.subject_revision
                ),
                metadata={
                    "embedded": True,
                    "parent_plan_id": (
                        plan.plan_id
                    ),
                },
            )
        )

        try:
            child = (
                self._benchmark_executor
                .execute(
                    benchmark_plan,
                    output_root=output_root,
                )
            )
        except Exception as exc:
            finished_at = _now(
                self._clock
            )

            return ExecutionRecord(
                execution_id=execution_id,
                plan=plan,
                executor=self.executor_id,
                state=ExecutionState.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                details={
                    **details,
                    "exception_type": (
                        type(exc).__name__
                    ),
                    "message": str(exc),
                },
            )

        if not isinstance(
            child,
            ExecutionRecord,
        ):
            raise TypeError(
                "benchmark executor must return "
                "an ExecutionRecord"
            )

        child_details = dict(
            child.details
        )

        nested = {
            "benchmark_execution_id": (
                child.execution_id
            ),
            "benchmark_plan_id": (
                child.plan.plan_id
            ),
            "benchmark_executor": (
                child.executor
            ),
            "benchmark_state": (
                child.state.value
            ),
            "benchmark_suite_dir": (
                child_details.get(
                    "suite_dir"
                )
            ),
        }

        if not child.successful:
            finished_at = _now(
                self._clock
            )

            return ExecutionRecord(
                execution_id=execution_id,
                plan=plan,
                executor=self.executor_id,
                state=ExecutionState.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                details={
                    **details,
                    **nested,
                    "benchmark_error": (
                        child_details.get(
                            "error"
                        )
                        or child_details.get(
                            "message"
                        )
                    ),
                },
            )

        suite = child_details.get(
            "suite"
        )

        if not isinstance(
            suite,
            Mapping,
        ):
            raise TypeError(
                "successful benchmark execution "
                "must expose suite details"
            )

        recommendation = (
            select_optimization_variant(
                suite,
                constraints=dict(
                    domain_plan.constraints
                ),
            )
        )

        finished_at = _now(
            self._clock
        )

        return ExecutionRecord(
            execution_id=execution_id,
            plan=plan,
            executor=self.executor_id,
            state=ExecutionState.COMPLETED,
            started_at=started_at,
            finished_at=finished_at,
            details={
                **details,
                **nested,
                "recommendation": (
                    recommendation
                ),
            },
        )


__all__ = [
    "OPTIMIZATION_EXECUTOR",
    "OptimizationExecutor",
]
