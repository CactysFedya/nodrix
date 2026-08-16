from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
import hashlib
import json
from typing import Any

from nodrix.extension_dispatcher import (
    ExtensionDispatcher,
)
from nodrix.model import (
    DefinitionRecord,
    ExecutionRecord,
    ExecutionState,
    Operation,
    OperationKind,
    PlanRecord,
)
from nodrix.model.plans import (
    canonical_plan_id,
)
from nodrix.sdk import (
    CustomDefinition,
    Extension,
    ExtensionRegistry,
    PlanningContext,
)


PLAN_KIND = "robot.flash"


def _payload_digest(
    payload: dict[str, Any],
) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()


@dataclass
class StaticDefinitionResolver:
    record: DefinitionRecord
    calls: int = 0

    def resolve_definition(
        self,
        entity,
    ) -> DefinitionRecord:
        self.calls += 1

        if entity != self.record.entity:
            raise KeyError(
                entity.canonical
            )

        return self.record


class FlashPlanner:
    @property
    def planner_id(
        self,
    ) -> str:
        return "acme.robot.flash.planner"

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
        definition = (
            context.resolve_definition(
                operation
            )
        )

        raw_spec = (
            definition
            .definition
            .get(
                "spec",
                {},
            )
        )

        if not isinstance(
            raw_spec,
            dict,
        ):
            raise TypeError(
                "firmware spec must be a mapping"
            )

        image = raw_spec.get(
            "image"
        )

        if not isinstance(
            image,
            str,
        ) or not image:
            raise ValueError(
                "firmware image must be defined"
            )

        payload = {
            "image": image,
            "verify": bool(
                operation.parameters.get(
                    "verify",
                    False,
                )
            ),
        }

        plan_id = canonical_plan_id(
            kind=PLAN_KIND,
            operation=operation,
            subject_revision=(
                definition.revision
            ),
            payload_sha256=(
                _payload_digest(
                    payload
                )
            ),
        )

        return PlanRecord(
            plan_id=plan_id,
            kind=PLAN_KIND,
            operation=operation,
            subject_revision=(
                definition.revision
            ),
            payload=payload,
            metadata={
                "planner": (
                    self.planner_id
                ),
            },
        )


class FlashExecutor:
    @property
    def executor_id(
        self,
    ) -> str:
        return (
            "acme.robot.flash.executor"
        )

    def execute(
        self,
        plan: PlanRecord,
    ) -> ExecutionRecord:
        payload = plan.payload

        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError(
                "flash plan payload must be a mapping"
            )

        now = datetime.now(
            timezone.utc
        )

        return ExecutionRecord(
            execution_id=(
                "execution-robot-flash"
            ),
            plan=plan,
            executor=self.executor_id,
            state=(
                ExecutionState.COMPLETED
            ),
            started_at=now,
            finished_at=now,
            details={
                "image": payload[
                    "image"
                ],
                "verify": payload[
                    "verify"
                ],
                "flashed": True,
            },
        )


def _firmware() -> CustomDefinition:
    return CustomDefinition(
        kind="robot.firmware",
        namespace="acme/rover-01",
        name="navigation",
        schema="robot.firmware/v1",
        spec={
            "target": "controller",
            "image": "firmware.bin",
        },
    )


def _extension() -> Extension:
    extension = Extension(
        "acme.robot"
    )

    extension.add_planner(
        FlashPlanner()
    )

    extension.add_executor(
        PLAN_KIND,
        FlashExecutor(),
    )

    return extension


def _dispatcher() -> ExtensionDispatcher:
    registry = ExtensionRegistry()

    _extension().register_into(
        registry
    )

    return ExtensionDispatcher(
        registry
    )


def test_custom_definition_operation_is_canonical_and_pinned_by_default() -> None:
    firmware = _firmware()

    record = (
        firmware.definition_record()
    )

    operation = firmware.operation(
        "robot.flash",
        parameters={
            "verify": True,
        },
    )

    assert (
        operation.subject
        == record.entity
    )

    assert (
        operation.subject_revision
        == record.revision
    )

    assert (
        operation.kind_name
        == "robot.flash"
    )

    assert (
        operation.parameters[
            "verify"
        ]
        is True
    )


def test_public_extension_bundle_drives_complete_custom_execution() -> None:
    firmware = _firmware()

    record = (
        firmware.definition_record()
    )

    resolver = (
        StaticDefinitionResolver(
            record
        )
    )

    operation = firmware.operation(
        "robot.flash",
        parameters={
            "verify": True,
        },
    )

    execution = (
        _dispatcher()
        .dispatch(
            operation,
            context=PlanningContext(
                definition_resolver=(
                    resolver
                )
            ),
        )
    )

    assert execution.successful

    assert (
        execution.operation
        == operation
    )

    assert (
        execution.subject
        == record.entity
    )

    assert (
        execution.subject_revision
        == record.revision
    )

    assert (
        execution.plan.kind_name
        == PLAN_KIND
    )

    assert (
        execution.details[
            "image"
        ]
        == "firmware.bin"
    )

    assert (
        execution.details[
            "verify"
        ]
        is True
    )

    assert (
        execution.details[
            "flashed"
        ]
        is True
    )

    assert resolver.calls == 1


def test_unpinned_custom_operation_resolves_revision_during_planning() -> None:
    firmware = _firmware()

    record = (
        firmware.definition_record()
    )

    resolver = (
        StaticDefinitionResolver(
            record
        )
    )

    operation = firmware.operation(
        "robot.flash",
        parameters={
            "verify": False,
        },
        pin_revision=False,
    )

    assert (
        operation.subject_revision
        is None
    )

    execution = (
        _dispatcher()
        .dispatch(
            operation,
            context=PlanningContext(
                definition_resolver=(
                    resolver
                )
            ),
        )
    )

    assert (
        execution.subject_revision
        == record.revision
    )

    assert (
        execution.details[
            "verify"
        ]
        is False
    )

    assert resolver.calls == 1


def test_custom_plan_identity_is_deterministic() -> None:
    firmware = _firmware()

    record = (
        firmware.definition_record()
    )

    operation = firmware.operation(
        "robot.flash",
        parameters={
            "verify": True,
        },
    )

    resolver = (
        StaticDefinitionResolver(
            record
        )
    )

    context = PlanningContext(
        definition_resolver=resolver
    )

    dispatcher = _dispatcher()

    first = dispatcher.plan(
        operation,
        context=context,
    )

    second = dispatcher.plan(
        operation,
        context=context,
    )

    assert (
        first.plan_id
        == second.plan_id
    )

    assert (
        first.subject_revision
        == second.subject_revision
        == record.revision
    )

    assert (
        first.payload
        == second.payload
    )


def test_custom_domain_requires_no_nodrix_builtin_operation_kind() -> None:
    operation = (
        _firmware()
        .operation(
            "robot.flash"
        )
    )

    assert (
        operation.kind
        == OperationKind(
            "robot.flash"
        )
    )

    assert (
        operation.kind_name
        == "robot.flash"
    )
