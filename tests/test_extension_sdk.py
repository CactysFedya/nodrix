from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

import pytest

from nodrix.executor_contract import (
    PlanExecutor as CorePlanExecutor,
)
from nodrix.extension_registry import (
    ExtensionRegistry as CoreExtensionRegistry,
)
from nodrix.model import (
    ExecutionRecord as ModelExecutionRecord,
)
from nodrix.model import (
    ExecutionState as ModelExecutionState,
)
from nodrix.model import (
    PlanKind as ModelPlanKind,
)
from nodrix.model import (
    PlanRecord as ModelPlanRecord,
)
from nodrix.model import (
    ExecutionRecord,
    ExecutionState,
    Operation,
    OperationKind,
    PlanRecord,
)
from nodrix.planner_contract import (
    DefinitionResolver as CoreDefinitionResolver,
)
from nodrix.planner_contract import (
    OperationPlanner as CoreOperationPlanner,
)
from nodrix.planner_contract import (
    PlanningContext as CorePlanningContext,
)
from nodrix.sdk import (
    DefinitionResolver,
    ExecutionRecord as SDKExecutionRecord,
    ExecutionState as SDKExecutionState,
    Extension,
    ExtensionRegistry,
    OperationPlanner,
    PlanExecutor,
    PlanKind,
    PlanRecord as SDKPlanRecord,
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
            context
            .resolve_subject_revision(
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


def test_sdk_reexports_canonical_extension_contracts() -> None:
    assert (
        PlanExecutor
        is CorePlanExecutor
    )

    assert (
        OperationPlanner
        is CoreOperationPlanner
    )

    assert (
        DefinitionResolver
        is CoreDefinitionResolver
    )

    assert (
        PlanningContext
        is CorePlanningContext
    )

    assert (
        ExtensionRegistry
        is CoreExtensionRegistry
    )


def test_sdk_reexports_canonical_plan_execution_models() -> None:
    assert (
        PlanKind
        is ModelPlanKind
    )

    assert (
        SDKPlanRecord
        is ModelPlanRecord
    )

    assert (
        SDKExecutionState
        is ModelExecutionState
    )

    assert (
        SDKExecutionRecord
        is ModelExecutionRecord
    )


def test_extension_starts_empty() -> None:
    extension = Extension(
        " acme.robot "
    )

    assert (
        extension.name
        == "acme.robot"
    )

    assert (
        extension.planners
        == ()
    )

    assert (
        extension.executors
        == ()
    )


def test_extension_requires_name() -> None:
    with pytest.raises(
        ValueError,
        match="must be non-empty",
    ):
        Extension("   ")


def test_extension_adds_planner() -> None:
    extension = Extension(
        "acme.robot"
    )

    planner = FlashPlanner()

    returned = extension.add_planner(
        planner
    )

    assert returned is planner

    assert (
        extension.planners
        == (
            planner,
        )
    )


def test_extension_rejects_duplicate_planner_kind() -> None:
    extension = Extension(
        "acme.robot"
    )

    extension.add_planner(
        FlashPlanner()
    )

    with pytest.raises(
        ValueError,
        match="already contains a planner",
    ):
        extension.add_planner(
            FlashPlanner()
        )


def test_extension_adds_executor() -> None:
    extension = Extension(
        "acme.robot"
    )

    executor = FlashExecutor()

    returned = extension.add_executor(
        "robot.flash",
        executor,
    )

    assert returned is executor

    assert (
        extension.executors
        == (
            (
                PlanKind(
                    "robot.flash"
                ),
                executor,
            ),
        )
    )


def test_extension_rejects_duplicate_executor_kind() -> None:
    extension = Extension(
        "acme.robot"
    )

    extension.add_executor(
        "robot.flash",
        FlashExecutor(),
    )

    with pytest.raises(
        ValueError,
        match="already contains an executor",
    ):
        extension.add_executor(
            "robot.flash",
            FlashExecutor(),
        )


def test_extension_registers_into_explicit_registry() -> None:
    extension = Extension(
        "acme.robot"
    )

    planner = FlashPlanner()
    executor = FlashExecutor()

    extension.add_planner(
        planner
    )

    extension.add_executor(
        "robot.flash",
        executor,
    )

    registry = ExtensionRegistry()

    extension.register_into(
        registry
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


def test_extension_conflict_is_checked_before_registry_mutation() -> None:
    registry = ExtensionRegistry()

    existing_executor = (
        FlashExecutor()
    )

    registry.register_executor(
        "robot.flash",
        existing_executor,
    )

    extension = Extension(
        "acme.robot"
    )

    extension.add_planner(
        FlashPlanner()
    )

    extension.add_executor(
        "robot.flash",
        FlashExecutor(),
    )

    with pytest.raises(
        ValueError,
        match="conflicts",
    ):
        extension.register_into(
            registry
        )

    with pytest.raises(
        KeyError,
    ):
        registry.planner_for(
            "robot.flash"
        )

    assert (
        registry.executor_for(
            "robot.flash"
        )
        is existing_executor
    )


def test_extension_is_not_an_execution_api() -> None:
    extension = Extension(
        "acme.robot"
    )

    assert not hasattr(
        extension,
        "plan",
    )

    assert not hasattr(
        extension,
        "execute",
    )

    assert not hasattr(
        extension,
        "dispatch",
    )
