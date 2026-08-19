from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

import pytest

from nodrix.extension_dispatcher import (
    ExtensionDispatcher,
)
from nodrix.extension_registry import (
    ExtensionRegistry,
)
from nodrix.foreground_operation import (
    ForegroundOperationResult,
    execute_foreground_operation,
    persist_foreground_execution,
)
from nodrix.model import (
    ExecutionRecord,
    PlanRecord,
)
from nodrix.planner_contract import (
    PlanningContext,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.model import (
    SystemModel,
)


NOW = datetime(
    2026,
    8,
    19,
    8,
    30,
    tzinfo=timezone.utc,
)


def _plan(
    name: str = "foreground-demo",
) -> PlanRecord:
    return plan_canonical_system(
        SystemModel(
            name=name
        )
    )


def _terminal_execution(
    plan: PlanRecord,
    *,
    execution_id: str = "exec-foreground",
) -> ExecutionRecord:
    return ExecutionRecord(
        execution_id=execution_id,
        plan=plan,
        executor="test.foreground",
        state="completed",
        started_at=NOW,
        finished_at=NOW,
        details={
            "source": "test",
        },
    )


def test_persist_foreground_execution_returns_canonical_run(
    tmp_path,
) -> None:
    plan = _plan()

    execution = _terminal_execution(
        plan
    )

    result = persist_foreground_execution(
        plan,
        execution,
        project=tmp_path,
        summary={
            "mode": "foreground",
        },
    )

    assert isinstance(
        result,
        ForegroundOperationResult,
    )

    assert result.plan is plan
    assert result.execution is execution

    assert (
        result.history.run.execution
        is execution
    )

    assert (
        result.history.run.summary[
            "mode"
        ]
        == "foreground"
    )

    assert result.successful


def test_foreground_execution_rejects_different_plan(
    tmp_path,
) -> None:
    expected_plan = _plan(
        "foreground-expected"
    )

    other_plan = _plan(
        "foreground-other"
    )

    execution = _terminal_execution(
        other_plan
    )

    with pytest.raises(
        ValueError,
        match="exact foreground PlanRecord",
    ):
        persist_foreground_execution(
            expected_plan,
            execution,
            project=tmp_path,
        )


def test_foreground_execution_rejects_nonterminal_execution(
    tmp_path,
) -> None:
    plan = _plan()

    execution = ExecutionRecord(
        execution_id="exec-running",
        plan=plan,
        executor="test.foreground",
        state="running",
        started_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="terminal ExecutionRecord",
    ):
        persist_foreground_execution(
            plan,
            execution,
            project=tmp_path,
        )


def test_foreground_service_plans_executes_and_persists(
    tmp_path,
) -> None:
    expected_plan = _plan(
        "foreground-dispatch"
    )

    operation = (
        expected_plan.operation
    )

    class Planner:
        @property
        def planner_id(
            self,
        ) -> str:
            return "test.foreground.planner"

        @property
        def operation_kind(
            self,
        ):
            return operation.kind

        def plan(
            self,
            candidate,
            *,
            context,
        ):
            assert candidate == operation
            assert isinstance(
                context,
                PlanningContext,
            )

            return expected_plan

    class Executor:
        @property
        def executor_id(
            self,
        ) -> str:
            return "test.foreground"

        def execute(
            self,
            plan,
        ):
            assert plan is expected_plan

            return _terminal_execution(
                plan,
                execution_id=(
                    "exec-dispatched-foreground"
                ),
            )

    registry = ExtensionRegistry()

    registry.register_planner(
        Planner()
    )

    registry.register_executor(
        expected_plan.kind,
        Executor(),
    )

    result = execute_foreground_operation(
        operation,
        dispatcher=ExtensionDispatcher(
            registry
        ),
        context=PlanningContext(),
        project=tmp_path,
        run_id="run-foreground",
    )

    assert result.plan is expected_plan

    assert (
        result.execution.plan
        is expected_plan
    )

    assert (
        result.history.run.run_id
        == "run-foreground"
    )

    assert (
        result.history.run.execution
        is result.execution
    )


def test_foreground_service_has_no_background_controls() -> None:
    import inspect

    signature = inspect.signature(
        execute_foreground_operation
    )

    forbidden = {
        "background",
        "detach",
        "daemon",
        "supervisor",
        "async_mode",
    }

    assert forbidden.isdisjoint(
        signature.parameters
    )
