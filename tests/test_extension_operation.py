from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import json
from pathlib import Path

import pytest

from nodrix.extension_dispatcher import (
    ExtensionDispatcher,
)
from nodrix.extension_operation import (
    ExtensionOperationResult,
    execute_extension_operation,
)
from nodrix.extension_registry import (
    ExtensionRegistry,
)
from nodrix.model import (
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


def _revision() -> RevisionRef:
    entity = _entity()

    return RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )


def _operation() -> Operation:
    return Operation(
        kind="robot.flash",
        subject=_entity(),
        subject_revision=_revision(),
        parameters={
            "verify": True,
        },
    )


class FlashPlanner:
    @property
    def planner_id(
        self,
    ) -> str:
        return "test.robot.flash.planner"

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
            plan_id="plan-robot-flash",
            kind="robot.flash",
            operation=operation,
            subject_revision=revision,
            payload={
                "image": "firmware.bin",
                "verify": True,
            },
            metadata={
                "planner": self.planner_id,
            },
        )


class FlashExecutor:
    @property
    def executor_id(
        self,
    ) -> str:
        return "test.robot.flash.executor"

    def execute(
        self,
        plan: PlanRecord,
    ) -> ExecutionRecord:
        now = datetime.now(
            timezone.utc
        )

        return ExecutionRecord(
            execution_id="execution-robot-flash",
            plan=plan,
            executor=self.executor_id,
            state=ExecutionState.COMPLETED,
            started_at=now,
            finished_at=now,
            details={
                "flashed": True,
            },
        )


class FailedFlashExecutor:
    @property
    def executor_id(
        self,
    ) -> str:
        return "test.robot.flash.failed"

    def execute(
        self,
        plan: PlanRecord,
    ) -> ExecutionRecord:
        now = datetime.now(
            timezone.utc
        )

        return ExecutionRecord(
            execution_id="execution-robot-flash-failed",
            plan=plan,
            executor=self.executor_id,
            state=ExecutionState.FAILED,
            started_at=now,
            finished_at=now,
            details={
                "message": "device rejected image",
            },
        )


class RunningFlashExecutor:
    @property
    def executor_id(
        self,
    ) -> str:
        return "test.robot.flash.running"

    def execute(
        self,
        plan: PlanRecord,
    ) -> ExecutionRecord:
        return ExecutionRecord(
            execution_id="execution-robot-flash-running",
            plan=plan,
            executor=self.executor_id,
            state=ExecutionState.RUNNING,
            started_at=datetime.now(
                timezone.utc
            ),
        )


def _dispatcher(
    executor: object | None = None,
) -> ExtensionDispatcher:
    registry = ExtensionRegistry()

    registry.register_planner(
        FlashPlanner()
    )

    registry.register_executor(
        "robot.flash",
        (
            FlashExecutor()
            if executor is None
            else executor
        ),
    )

    return ExtensionDispatcher(
        registry
    )


def test_extension_operation_persists_one_canonical_run(
    tmp_path: Path,
) -> None:
    operation = _operation()

    result = execute_extension_operation(
        operation,
        dispatcher=_dispatcher(),
        context=PlanningContext(),
        project=tmp_path,
    )

    assert isinstance(
        result,
        ExtensionOperationResult,
    )

    assert result.successful

    assert (
        result.plan
        is result.execution.plan
    )

    assert (
        result.history.run.execution
        is result.execution
    )

    assert (
        result.history.run.operation
        == operation
    )

    expected = (
        tmp_path
        / ".nodrix"
        / "runs"
        / "execution-robot-flash"
        / "run.json"
    )

    assert (
        result.history.path
        == expected.resolve()
    )

    assert expected.is_file()


def test_extension_run_document_preserves_canonical_chain(
    tmp_path: Path,
) -> None:
    operation = _operation()

    result = execute_extension_operation(
        operation,
        dispatcher=_dispatcher(),
        context=PlanningContext(),
        project=tmp_path,
        summary={
            "flashed": True,
        },
        metadata={
            "source": "extension-test",
        },
    )

    document = json.loads(
        result.history.path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        document["schema"]
        == "nodrix.run/v1"
    )

    assert (
        document["kind"]
        == "Run"
    )

    assert (
        document["operation"]["kind"]
        == "robot.flash"
    )

    assert (
        document["plan"]["id"]
        == result.plan.plan_id
    )

    assert (
        document["plan"]["kind"]
        == "robot.flash"
    )

    assert (
        document["execution"]["id"]
        == result.execution.execution_id
    )

    assert (
        document["execution"]["executor"]
        == "test.robot.flash.executor"
    )

    assert (
        document["subject"]["entity"]
        == str(operation.subject)
    )

    assert (
        document["subject"]["revision"]
        == str(
            result.plan.subject_revision
        )
    )

    assert (
        document["summary"]["flashed"]
        is True
    )

    assert (
        document["metadata"]["source"]
        == "extension-test"
    )


def test_extension_operation_supports_explicit_run_id(
    tmp_path: Path,
) -> None:
    result = execute_extension_operation(
        _operation(),
        dispatcher=_dispatcher(),
        context=PlanningContext(),
        project=tmp_path,
        run_id="run-custom-flash",
    )

    assert (
        result.history.run.run_id
        == "run-custom-flash"
    )

    assert (
        result.history.path
        == (
            tmp_path
            / ".nodrix"
            / "runs"
            / "run-custom-flash"
            / "run.json"
        ).resolve()
    )


def test_failed_extension_execution_is_still_durable_history(
    tmp_path: Path,
) -> None:
    result = execute_extension_operation(
        _operation(),
        dispatcher=_dispatcher(
            FailedFlashExecutor()
        ),
        context=PlanningContext(),
        project=tmp_path,
    )

    assert not result.successful

    assert (
        result.execution.state
        == ExecutionState.FAILED
    )

    assert (
        result.history.run.state
        == ExecutionState.FAILED
    )

    assert result.history.path.is_file()


def test_nonterminal_extension_execution_cannot_become_run(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="terminal ExecutionRecord",
    ):
        execute_extension_operation(
            _operation(),
            dispatcher=_dispatcher(
                RunningFlashExecutor()
            ),
            context=PlanningContext(),
            project=tmp_path,
        )

    assert not (
        tmp_path
        / ".nodrix"
        / "runs"
    ).exists()


def test_dispatcher_alone_does_not_persist_run(
    tmp_path: Path,
) -> None:
    dispatcher = _dispatcher()

    execution = dispatcher.dispatch(
        _operation(),
        context=PlanningContext(),
    )

    assert execution.successful

    assert not (
        tmp_path
        / ".nodrix"
    ).exists()


def test_extension_operation_boundary_is_not_sdk_authoring_surface() -> None:
    import nodrix.sdk as sdk

    assert not hasattr(
        sdk,
        "execute_extension_operation",
    )

    assert not hasattr(
        sdk,
        "ExtensionOperationResult",
    )
