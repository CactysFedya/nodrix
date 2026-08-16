from __future__ import annotations

from dataclasses import dataclass

import pytest

from nodrix.model import (
    DefinitionRecord,
    EntityRef,
    Operation,
    OperationKind,
    PlanRecord,
    RevisionRef,
)
from nodrix.planner_contract import (
    DefinitionResolver,
    OperationPlanner,
    PlanningContext,
)


def _entity(
    name: str = "navigation",
) -> EntityRef:
    return EntityRef(
        kind="robot.firmware",
        namespace="acme/rover-01",
        name=name,
    )


def _revision(
    entity: EntityRef,
    token: str = "a",
) -> RevisionRef:
    return RevisionRef.from_sha256(
        entity,
        token * 64,
    )


def _definition(
    *,
    entity: EntityRef | None = None,
    token: str = "a",
) -> DefinitionRecord:
    selected = (
        entity
        if entity is not None
        else _entity()
    )

    return DefinitionRecord(
        entity=selected,
        revision=_revision(
            selected,
            token,
        ),
        schema="robot.firmware/v1",
        definition={
            "apiVersion": "robot.firmware/v1",
            "kind": "robot.firmware",
            "metadata": {
                "namespace": selected.namespace,
                "name": selected.name,
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
        del entity
        return self.record


def test_definition_resolver_is_structural_contract() -> None:
    resolver = StaticResolver(
        _definition()
    )

    assert isinstance(
        resolver,
        DefinitionResolver,
    )


def test_pinned_operation_revision_does_not_require_resolver() -> None:
    entity = _entity()
    revision = _revision(entity)

    operation = Operation(
        kind="robot.flash",
        subject=entity,
        subject_revision=revision,
    )

    context = PlanningContext()

    assert (
        context.resolve_subject_revision(
            operation
        )
        == revision
    )


def test_unpinned_operation_resolves_definition_revision() -> None:
    record = _definition()

    operation = Operation(
        kind="robot.flash",
        subject=record.entity,
    )

    context = PlanningContext(
        definition_resolver=(
            StaticResolver(record)
        )
    )

    assert (
        context.resolve_subject_revision(
            operation
        )
        == record.revision
    )


def test_unpinned_operation_requires_definition_resolver() -> None:
    operation = Operation(
        kind="robot.flash",
        subject=_entity(),
    )

    context = PlanningContext()

    with pytest.raises(
        ValueError,
        match="has no DefinitionResolver",
    ):
        context.resolve_subject_revision(
            operation
        )


def test_resolved_definition_must_match_operation_subject() -> None:
    operation = Operation(
        kind="robot.flash",
        subject=_entity(),
    )

    other = _definition(
        entity=_entity(
            "perception"
        )
    )

    context = PlanningContext(
        definition_resolver=(
            StaticResolver(other)
        )
    )

    with pytest.raises(
        ValueError,
        match="operation subject",
    ):
        context.resolve_definition(
            operation
        )


def test_resolved_definition_must_match_pinned_revision() -> None:
    record = _definition(
        token="a"
    )

    operation = Operation(
        kind="robot.flash",
        subject=record.entity,
        subject_revision=_revision(
            record.entity,
            "b",
        ),
    )

    context = PlanningContext(
        definition_resolver=(
            StaticResolver(record)
        )
    )

    with pytest.raises(
        ValueError,
        match="revision pinned",
    ):
        context.resolve_definition(
            operation
        )


def test_definition_resolver_must_return_definition_record() -> None:
    class InvalidResolver:
        def resolve_definition(
            self,
            entity: EntityRef,
        ) -> object:
            return entity

    operation = Operation(
        kind="robot.flash",
        subject=_entity(),
    )

    context = PlanningContext(
        definition_resolver=(
            InvalidResolver()
        )
    )

    with pytest.raises(
        TypeError,
        match="must return a DefinitionRecord",
    ):
        context.resolve_definition(
            operation
        )


def test_operation_planner_is_structural_contract() -> None:
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
            del context

            revision = (
                operation.subject_revision
            )

            assert revision is not None

            return PlanRecord(
                plan_id="plan-test",
                kind="robot.flash",
                operation=operation,
                subject_revision=revision,
                payload={
                    "command": "flash",
                },
            )

    assert isinstance(
        FlashPlanner(),
        OperationPlanner,
    )


def test_operation_planner_requires_planning_surface() -> None:
    class NotAPlanner:
        @property
        def planner_id(
            self,
        ) -> str:
            return "test.invalid"

    assert not isinstance(
        NotAPlanner(),
        OperationPlanner,
    )
