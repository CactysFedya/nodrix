from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

import pytest

from nodrix.executor_contract import (
    PlanExecutor,
)
from nodrix.extension_registry import (
    ExtensionRegistry,
)
from nodrix.model import (
    ExecutionRecord,
    ExecutionState,
    Operation,
    OperationKind,
    PlanKind,
    PlanRecord,
)
from nodrix.planner_contract import (
    OperationPlanner,
    PlanningContext,
)


class FlashPlanner:
    @property
    def planner_id(
        self,
    ) -> str:
        return "test.robot.flash"

    @property
    def operation_kind(
        self,
    ) -> OperationKind:
        return OperationKind(
            "robot.flash"
        )

    def plan(
        self,
        operation: Operation,
        *,
        context: PlanningContext,
    ) -> PlanRecord:
        revision = (
            context.resolve_subject_revision(
                operation
            )
        )

        return PlanRecord(
            plan_id="plan-flash",
            kind="robot.flash",
            operation=operation,
            subject_revision=revision,
            payload={
                "command": "flash",
            },
        )


class FlashExecutor:
    @property
    def executor_id(
        self,
    ) -> str:
        return "test.robot.flash"

    def execute(
        self,
        plan: PlanRecord,
    ) -> ExecutionRecord:
        now = datetime.now(
            timezone.utc
        )

        return ExecutionRecord(
            execution_id="execution-flash",
            plan=plan,
            executor=self.executor_id,
            state=ExecutionState.COMPLETED,
            started_at=now,
            finished_at=now,
        )


def test_registry_starts_empty() -> None:
    registry = ExtensionRegistry()

    assert (
        registry.operation_kinds
        == ()
    )

    assert (
        registry.plan_kinds
        == ()
    )


def test_registry_registers_planner_by_operation_kind() -> None:
    registry = ExtensionRegistry()
    planner = FlashPlanner()

    registry.register_planner(
        planner
    )

    assert (
        registry.planner_for(
            "robot.flash"
        )
        is planner
    )

    assert (
        registry.operation_kinds
        == (
            OperationKind(
                "robot.flash"
            ),
        )
    )


def test_registry_registers_executor_by_plan_kind() -> None:
    registry = ExtensionRegistry()
    executor = FlashExecutor()

    registry.register_executor(
        "robot.flash",
        executor,
    )

    assert (
        registry.executor_for(
            "robot.flash"
        )
        is executor
    )

    assert (
        registry.plan_kinds
        == (
            PlanKind(
                "robot.flash"
            ),
        )
    )


def test_registry_accepts_canonical_kind_objects() -> None:
    registry = ExtensionRegistry()

    planner = FlashPlanner()
    executor = FlashExecutor()

    registry.register_planner(
        planner
    )

    registry.register_executor(
        PlanKind(
            "robot.flash"
        ),
        executor,
    )

    assert (
        registry.planner_for(
            OperationKind(
                "robot.flash"
            )
        )
        is planner
    )

    assert (
        registry.executor_for(
            PlanKind(
                "robot.flash"
            )
        )
        is executor
    )


def test_registry_rejects_duplicate_planner() -> None:
    registry = ExtensionRegistry()

    registry.register_planner(
        FlashPlanner()
    )

    with pytest.raises(
        ValueError,
        match="planner already registered",
    ):
        registry.register_planner(
            FlashPlanner()
        )


def test_registry_rejects_duplicate_executor() -> None:
    registry = ExtensionRegistry()

    registry.register_executor(
        "robot.flash",
        FlashExecutor(),
    )

    with pytest.raises(
        ValueError,
        match="executor already registered",
    ):
        registry.register_executor(
            "robot.flash",
            FlashExecutor(),
        )


def test_registry_rejects_invalid_planner_contract() -> None:
    registry = ExtensionRegistry()

    class InvalidPlanner:
        pass

    with pytest.raises(
        TypeError,
        match="OperationPlanner",
    ):
        registry.register_planner(
            InvalidPlanner()  # type: ignore[arg-type]
        )


def test_registry_rejects_invalid_executor_contract() -> None:
    registry = ExtensionRegistry()

    class InvalidExecutor:
        pass

    with pytest.raises(
        TypeError,
        match="PlanExecutor",
    ):
        registry.register_executor(
            "robot.flash",
            InvalidExecutor(),  # type: ignore[arg-type]
        )


def test_registry_reports_missing_planner() -> None:
    registry = ExtensionRegistry()

    with pytest.raises(
        KeyError,
        match="robot.flash",
    ):
        registry.planner_for(
            "robot.flash"
        )


def test_registry_reports_missing_executor() -> None:
    registry = ExtensionRegistry()

    with pytest.raises(
        KeyError,
        match="robot.flash",
    ):
        registry.executor_for(
            "robot.flash"
        )


def test_registry_keeps_planners_and_executors_separate() -> None:
    registry = ExtensionRegistry()

    planner = FlashPlanner()
    executor = FlashExecutor()

    assert isinstance(
        planner,
        OperationPlanner,
    )

    assert isinstance(
        executor,
        PlanExecutor,
    )

    registry.register_planner(
        planner
    )

    with pytest.raises(
        KeyError,
    ):
        registry.executor_for(
            "robot.flash"
        )

    registry.register_executor(
        "robot.flash",
        executor,
    )

    assert (
        registry.planner_for(
            "robot.flash"
        )
        is planner
    )

    assert (
        registry.executor_for(
            "robot.flash"
        )
        is executor
    )


def test_registry_instances_do_not_share_state() -> None:
    first = ExtensionRegistry()
    second = ExtensionRegistry()

    first.register_planner(
        FlashPlanner()
    )

    first.register_executor(
        "robot.flash",
        FlashExecutor(),
    )

    assert (
        second.operation_kinds
        == ()
    )

    assert (
        second.plan_kinds
        == ()
    )
