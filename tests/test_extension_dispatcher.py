from __future__ import annotations

from dataclasses import dataclass
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
from nodrix.model import (
    DefinitionRecord,
    EntityRef,
    ExecutionRecord,
    ExecutionState,
    Operation,
    OperationKind,
    PlanRecord,
    RevisionRef,
)
from nodrix.planner_contract import (
    PlanningContext,
)


def _entity() -> EntityRef:
    return EntityRef(
        kind="robot.firmware",
        namespace="acme/rover-01",
        name="navigation",
    )


def _revision(
    entity: EntityRef,
) -> RevisionRef:
    return RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )


def _definition() -> DefinitionRecord:
    entity = _entity()

    return DefinitionRecord(
        entity=entity,
        revision=_revision(entity),
        schema="robot.firmware/v1",
        definition={
            "apiVersion": "robot.firmware/v1",
            "kind": "robot.firmware",
            "metadata": {
                "namespace": "acme/rover-01",
                "name": "navigation",
            },
            "spec": {
                "image": "firmware.bin",
            },
        },
    )


@dataclass
class StaticResolver:
    record: DefinitionRecord

    def resolve_definition(
        self,
        entity: EntityRef,
    ) -> DefinitionRecord:
        assert (
            entity
            == self.record.entity
        )

        return self.record


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
                "image": "firmware.bin",
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
            details={
                "flashed": True,
            },
        )


def _operation() -> Operation:
    return Operation(
        kind="robot.flash",
        subject=_entity(),
        parameters={
            "verify": True,
        },
    )


def _context() -> PlanningContext:
    return PlanningContext(
        definition_resolver=(
            StaticResolver(
                _definition()
            )
        )
    )


def _registry() -> ExtensionRegistry:
    registry = ExtensionRegistry()

    registry.register_planner(
        FlashPlanner()
    )

    registry.register_executor(
        "robot.flash",
        FlashExecutor(),
    )

    return registry


def test_dispatcher_plans_operation_through_registry() -> None:
    dispatcher = ExtensionDispatcher(
        _registry()
    )

    operation = _operation()

    plan = dispatcher.plan(
        operation,
        context=_context(),
    )

    assert (
        plan.operation
        == operation
    )

    assert (
        plan.kind.value
        == "robot.flash"
    )

    assert (
        plan.subject_revision
        == _definition().revision
    )


def test_dispatcher_executes_plan_through_registry() -> None:
    dispatcher = ExtensionDispatcher(
        _registry()
    )

    plan = dispatcher.plan(
        _operation(),
        context=_context(),
    )

    execution = dispatcher.execute(
        plan
    )

    assert (
        execution.plan
        is plan
    )

    assert (
        execution.executor
        == "test.robot.flash"
    )

    assert execution.successful


def test_dispatcher_runs_complete_extension_path() -> None:
    dispatcher = ExtensionDispatcher(
        _registry()
    )

    execution = dispatcher.dispatch(
        _operation(),
        context=_context(),
    )

    assert (
        execution.operation.kind_name
        == "robot.flash"
    )

    assert (
        execution.subject
        == _entity()
    )

    assert (
        execution.subject_revision
        == _definition().revision
    )

    assert (
        execution.details[
            "flashed"
        ]
        is True
    )


def test_dispatcher_reports_missing_planner() -> None:
    dispatcher = ExtensionDispatcher(
        ExtensionRegistry()
    )

    with pytest.raises(
        KeyError,
        match="robot.flash",
    ):
        dispatcher.plan(
            _operation(),
            context=_context(),
        )


def test_dispatcher_reports_missing_executor() -> None:
    registry = ExtensionRegistry()

    registry.register_planner(
        FlashPlanner()
    )

    dispatcher = ExtensionDispatcher(
        registry
    )

    plan = dispatcher.plan(
        _operation(),
        context=_context(),
    )

    with pytest.raises(
        KeyError,
        match="robot.flash",
    ):
        dispatcher.execute(
            plan
        )


def test_dispatcher_rejects_invalid_planner_result() -> None:
    class InvalidPlanner:
        @property
        def planner_id(
            self,
        ) -> str:
            return "test.invalid"

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
        ) -> object:
            del operation
            del context

            return {
                "command": "flash",
            }

    registry = ExtensionRegistry()

    registry.register_planner(
        InvalidPlanner()  # type: ignore[arg-type]
    )

    dispatcher = ExtensionDispatcher(
        registry
    )

    with pytest.raises(
        TypeError,
        match="must return a PlanRecord",
    ):
        dispatcher.plan(
            _operation(),
            context=_context(),
        )


def test_dispatcher_rejects_plan_for_different_operation() -> None:
    class DifferentOperationPlanner:
        @property
        def planner_id(
            self,
        ) -> str:
            return "test.different"

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

            different = Operation(
                kind=operation.kind,
                subject=operation.subject,
                subject_revision=revision,
                parameters={
                    "different": True,
                },
            )

            return PlanRecord(
                plan_id="plan-different",
                kind="robot.flash",
                operation=different,
                subject_revision=revision,
                payload={},
            )

    registry = ExtensionRegistry()

    registry.register_planner(
        DifferentOperationPlanner()
    )

    dispatcher = ExtensionDispatcher(
        registry
    )

    with pytest.raises(
        ValueError,
        match="different Operation",
    ):
        dispatcher.plan(
            _operation(),
            context=_context(),
        )


def test_dispatcher_rejects_invalid_executor_result() -> None:
    class InvalidExecutor:
        @property
        def executor_id(
            self,
        ) -> str:
            return "test.invalid"

        def execute(
            self,
            plan: PlanRecord,
        ) -> object:
            return plan

    registry = ExtensionRegistry()

    registry.register_planner(
        FlashPlanner()
    )

    registry.register_executor(
        "robot.flash",
        InvalidExecutor(),  # type: ignore[arg-type]
    )

    dispatcher = ExtensionDispatcher(
        registry
    )

    plan = dispatcher.plan(
        _operation(),
        context=_context(),
    )

    with pytest.raises(
        TypeError,
        match="must return an ExecutionRecord",
    ):
        dispatcher.execute(
            plan
        )


def test_dispatcher_requires_exact_plan_on_execution_record() -> None:
    class DifferentPlanExecutor:
        @property
        def executor_id(
            self,
        ) -> str:
            return "test.different-plan"

        def execute(
            self,
            plan: PlanRecord,
        ) -> ExecutionRecord:
            other = PlanRecord(
                plan_id=plan.plan_id,
                kind=plan.kind,
                operation=plan.operation,
                subject_revision=(
                    plan.subject_revision
                ),
                payload={
                    "different": True,
                },
                metadata=plan.metadata,
            )

            now = datetime.now(
                timezone.utc
            )

            return ExecutionRecord(
                execution_id="execution-other",
                plan=other,
                executor=self.executor_id,
                state=ExecutionState.COMPLETED,
                started_at=now,
                finished_at=now,
            )

    registry = ExtensionRegistry()

    registry.register_planner(
        FlashPlanner()
    )

    registry.register_executor(
        "robot.flash",
        DifferentPlanExecutor(),
    )

    dispatcher = ExtensionDispatcher(
        registry
    )

    plan = dispatcher.plan(
        _operation(),
        context=_context(),
    )

    with pytest.raises(
        ValueError,
        match="different PlanRecord",
    ):
        dispatcher.execute(
            plan
        )


def test_dispatcher_validates_executor_identity() -> None:
    class WrongIdentityExecutor:
        @property
        def executor_id(
            self,
        ) -> str:
            return "test.expected"

        def execute(
            self,
            plan: PlanRecord,
        ) -> ExecutionRecord:
            now = datetime.now(
                timezone.utc
            )

            return ExecutionRecord(
                execution_id="execution-wrong-id",
                plan=plan,
                executor="test.other",
                state=ExecutionState.COMPLETED,
                started_at=now,
                finished_at=now,
            )

    registry = ExtensionRegistry()

    registry.register_planner(
        FlashPlanner()
    )

    registry.register_executor(
        "robot.flash",
        WrongIdentityExecutor(),
    )

    dispatcher = ExtensionDispatcher(
        registry
    )

    plan = dispatcher.plan(
        _operation(),
        context=_context(),
    )

    with pytest.raises(
        ValueError,
        match="selected PlanExecutor",
    ):
        dispatcher.execute(
            plan
        )
