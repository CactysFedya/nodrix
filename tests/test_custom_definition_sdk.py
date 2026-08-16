from __future__ import annotations

import pytest

from nodrix.custom_definition import (
    custom_definition_digest,
    custom_definition_record,
)
from nodrix.sdk import (
    CustomDefinition,
    EntityRef,
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


def test_custom_definition_authors_canonical_document() -> None:
    definition = _firmware()

    assert (
        definition.to_dict()
        == {
            "apiVersion": (
                "robot.firmware/v1"
            ),
            "kind": "robot.firmware",
            "metadata": {
                "namespace": (
                    "acme/rover-01"
                ),
                "name": "navigation",
            },
            "spec": {
                "target": "controller",
                "image": "firmware.bin",
            },
        }
    )


def test_custom_definition_uses_canonical_entity_ref() -> None:
    definition = _firmware()

    assert (
        definition.entity_ref()
        == EntityRef(
            kind="robot.firmware",
            namespace="acme/rover-01",
            name="navigation",
        )
    )


def test_custom_definition_record_matches_core_bridge() -> None:
    definition = _firmware()

    sdk_record = (
        definition.definition_record()
    )

    core_record = (
        custom_definition_record(
            definition.to_dict()
        )
    )

    assert (
        sdk_record.entity
        == core_record.entity
    )

    assert (
        sdk_record.revision
        == core_record.revision
    )

    assert (
        sdk_record.definition
        == core_record.definition
    )


def test_custom_definition_digest_is_mapping_order_independent() -> None:
    first = _firmware().to_dict()

    second = {
        "spec": {
            "image": "firmware.bin",
            "target": "controller",
        },
        "metadata": {
            "name": "navigation",
            "namespace": "acme/rover-01",
        },
        "kind": "robot.firmware",
        "apiVersion": "robot.firmware/v1",
    }

    assert (
        custom_definition_digest(
            first
        )
        == custom_definition_digest(
            second
        )
    )


def test_custom_definition_digest_changes_with_spec() -> None:
    first = _firmware()

    second = CustomDefinition(
        kind="robot.firmware",
        namespace="acme/rover-01",
        name="navigation",
        schema="robot.firmware/v1",
        spec={
            "target": "controller",
            "image": "firmware-v2.bin",
        },
    )

    assert (
        first.definition_record().revision
        != second.definition_record().revision
    )


def test_custom_definition_snapshots_input_spec() -> None:
    spec = {
        "nested": {
            "value": 1,
        },
    }

    definition = CustomDefinition(
        kind="vendor.example",
        namespace="workspace/demo",
        name="sample",
        schema="vendor.example/v1",
        spec=spec,
    )

    spec["nested"]["value"] = 2

    assert (
        definition.to_dict()[
            "spec"
        ][
            "nested"
        ][
            "value"
        ]
        == 1
    )


def test_custom_definition_requires_namespaced_kind() -> None:
    with pytest.raises(
        ValueError,
        match="must be namespaced",
    ):
        CustomDefinition(
            kind="firmware",
            namespace="workspace/demo",
            name="navigation",
            schema="firmware/v1",
        )


def test_custom_definition_record_metadata_is_non_semantic() -> None:
    definition = _firmware()

    first = (
        definition.definition_record(
            metadata={
                "source": "python",
            }
        )
    )

    second = (
        definition.definition_record(
            metadata={
                "source": "generated",
            }
        )
    )

    assert (
        first.revision
        == second.revision
    )


def test_custom_definition_to_dict_is_detached() -> None:
    definition = _firmware()

    document = (
        definition.to_dict()
    )

    document["spec"]["image"] = (
        "changed.bin"
    )

    assert (
        definition.to_dict()[
            "spec"
        ][
            "image"
        ]
        == "firmware.bin"
    )
