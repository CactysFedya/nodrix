from __future__ import annotations

import pytest

from nodrix.model import (
    Operation as ModelOperation,
)
from nodrix.model import (
    OperationKind as ModelOperationKind,
)
from nodrix.sdk import (
    CustomDefinition,
    EntityRef,
    Operation,
    OperationKind,
)


def _firmware() -> CustomDefinition:
    return CustomDefinition(
        kind="robot.firmware",
        namespace="acme/rover-01",
        name="navigation",
        schema="robot.firmware/v1",
        spec={
            "image": "firmware.bin",
        },
    )


def test_sdk_reexports_canonical_operation_types() -> None:
    assert (
        Operation
        is ModelOperation
    )

    assert (
        OperationKind
        is ModelOperationKind
    )


def test_sdk_authors_standalone_custom_operation() -> None:
    subject = EntityRef(
        kind="robot.firmware",
        namespace="acme/rover-01",
        name="navigation",
    )

    operation = Operation(
        kind="robot.flash",
        subject=subject,
        parameters={
            "verify": True,
        },
    )

    assert (
        operation.kind_name
        == "robot.flash"
    )

    assert (
        operation.subject
        == subject
    )

    assert (
        operation.subject_revision
        is None
    )

    assert (
        operation.parameters[
            "verify"
        ]
        is True
    )


def test_custom_definition_operation_pins_current_revision_by_default() -> None:
    definition = _firmware()

    operation = (
        definition.operation(
            "robot.flash"
        )
    )

    record = (
        definition.definition_record()
    )

    assert (
        operation.subject
        == record.entity
    )

    assert (
        operation.subject_revision
        == record.revision
    )


def test_custom_definition_operation_can_defer_revision_resolution() -> None:
    definition = _firmware()

    operation = (
        definition.operation(
            "robot.flash",
            pin_revision=False,
        )
    )

    assert (
        operation.subject
        == definition.entity_ref()
    )

    assert (
        operation.subject_revision
        is None
    )


def test_custom_definition_operation_preserves_parameters() -> None:
    definition = _firmware()

    operation = (
        definition.operation(
            "robot.flash",
            parameters={
                "device": "/dev/ttyUSB0",
                "verify": True,
            },
        )
    )

    assert (
        dict(
            operation.parameters
        )
        == {
            "device": "/dev/ttyUSB0",
            "verify": True,
        }
    )


def test_custom_definition_operation_accepts_operation_kind() -> None:
    definition = _firmware()

    kind = OperationKind(
        "robot.flash"
    )

    operation = (
        definition.operation(
            kind
        )
    )

    assert (
        operation.kind
        == kind
    )


def test_custom_definition_operation_validates_pin_revision() -> None:
    definition = _firmware()

    with pytest.raises(
        TypeError,
        match=(
            "pin_revision must "
            "be a boolean"
        ),
    ):
        definition.operation(
            "robot.flash",
            pin_revision="yes",  # type: ignore[arg-type]
        )


def test_operation_is_not_an_execution_api() -> None:
    definition = _firmware()

    operation = (
        definition.operation(
            "robot.flash"
        )
    )

    assert not hasattr(
        operation,
        "execute",
    )

    assert not hasattr(
        operation,
        "run",
    )
