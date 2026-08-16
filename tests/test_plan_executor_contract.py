from __future__ import annotations

from nodrix.benchmark_executor import (
    BENCHMARK_EXECUTOR,
    BenchmarkExecutor,
)
from nodrix.executor_contract import (
    PlanExecutor,
)
from nodrix.optimization_executor import (
    OPTIMIZATION_EXECUTOR,
    OptimizationExecutor,
)
from nodrix.workflow_executor import (
    WORKFLOW_EXECUTOR,
    WorkflowExecutor,
)


def _benchmark_run_callable(
    *args: object,
    **kwargs: object,
) -> None:
    del args
    del kwargs


def test_workflow_executor_satisfies_plan_executor_contract() -> None:
    executor = WorkflowExecutor()

    assert isinstance(
        executor,
        PlanExecutor,
    )

    assert (
        executor.executor_id
        == WORKFLOW_EXECUTOR
    )


def test_benchmark_executor_satisfies_plan_executor_contract() -> None:
    executor = BenchmarkExecutor(
        run_callable=(
            _benchmark_run_callable
        ),
    )

    assert isinstance(
        executor,
        PlanExecutor,
    )

    assert (
        executor.executor_id
        == BENCHMARK_EXECUTOR
    )


def test_optimization_executor_satisfies_plan_executor_contract() -> None:
    executor = (
        OptimizationExecutor()
    )

    assert isinstance(
        executor,
        PlanExecutor,
    )

    assert (
        executor.executor_id
        == OPTIMIZATION_EXECUTOR
    )


def test_plan_executor_contract_requires_executor_id() -> None:
    class MissingExecutorId:
        def execute(
            self,
            plan: object,
        ) -> object:
            return plan

    assert not isinstance(
        MissingExecutorId(),
        PlanExecutor,
    )


def test_plan_executor_contract_requires_execute() -> None:
    class MissingExecute:
        @property
        def executor_id(
            self,
        ) -> str:
            return "test.missing"

    assert not isinstance(
        MissingExecute(),
        PlanExecutor,
    )


def test_system_backend_remains_a_separate_contract() -> None:
    from nodrix.system import (
        ExecutionBackend,
    )

    assert not hasattr(
        ExecutionBackend,
        "executor_id",
    )

    assert not hasattr(
        ExecutionBackend,
        "execute",
    )

    assert hasattr(
        ExecutionBackend,
        "prepare",
    )

    assert hasattr(
        ExecutionBackend,
        "start",
    )

    assert hasattr(
        ExecutionBackend,
        "inspect",
    )

    assert hasattr(
        ExecutionBackend,
        "stop",
    )
