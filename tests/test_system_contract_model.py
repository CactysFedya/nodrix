from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

import nodrix
from nodrix.system import (
    SystemModel,
    SystemPort,
    dumps_system,
    loads_system,
    system_json_schema,
    system_to_canonical,
    validate_system,
)
from nodrix.system.definition import (
    system_definition_digest,
)


POINT_CLOUD = "spatial.point_cloud/v1"
IMU = "spatial.imu/v1"


def test_system_port_normalizes_type_id() -> None:
    port = SystemPort(
        name="lidar",
        type_id=f"  {POINT_CLOUD}  ",
        description="Registered point cloud",
    )

    assert port.name == "lidar"
    assert port.type_id == POINT_CLOUD
    assert (
        port.description
        == "Registered point cloud"
    )


def test_system_port_does_not_embed_transport_fields() -> None:
    with pytest.raises(
        ValidationError,
    ):
        SystemPort(
            name="lidar",
            type_id=POINT_CLOUD,
            topic="/livox/lidar",
        )


def test_system_contract_round_trip_is_canonical() -> None:
    system = SystemModel(
        name="fast-livo2",
        inputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
            SystemPort(
                name="imu",
                type_id=IMU,
            ),
        ),
        outputs=(
            SystemPort(
                name="registered_cloud",
                type_id=POINT_CLOUD,
            ),
        ),
    )

    serialized = dumps_system(
        system,
        format="yaml",
    )

    restored = loads_system(
        serialized,
        format="yaml",
    )

    assert restored == system

    canonical = system_to_canonical(
        restored
    )

    assert list(
        canonical
    )[:5] == [
        "apiVersion",
        "kind",
        "name",
        "inputs",
        "outputs",
    ]

    assert canonical["inputs"] == [
        {
            "name": "lidar",
            "optional": False,
            "type_id": POINT_CLOUD,
        },
        {
            "name": "imu",
            "optional": False,
            "type_id": IMU,
        },
    ]

    assert canonical["outputs"] == [
        {
            "name": "registered_cloud",
            "optional": False,
            "type_id": POINT_CLOUD,
        }
    ]


@pytest.mark.parametrize(
    ("direction", "expected_path"),
    (
        ("inputs", "inputs.lidar"),
        ("outputs", "outputs.lidar"),
    ),
)
def test_duplicate_system_port_names_are_invalid(
    direction: str,
    expected_path: str,
) -> None:
    values = {
        direction: (
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
        )
    }

    system = SystemModel(
        name="duplicate-contract",
        **values,
    )

    report = validate_system(
        system
    )

    diagnostic = next(
        item
        for item in report.errors
        if item.code == "SYS001"
        and item.path == expected_path
    )

    assert "duplicate" in diagnostic.message


def test_same_port_name_may_exist_in_both_directions() -> None:
    system = SystemModel(
        name="bidirectional",
        inputs=(
            SystemPort(
                name="state",
                type_id="robot.state/v1",
            ),
        ),
        outputs=(
            SystemPort(
                name="state",
                type_id="robot.state/v1",
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert report.valid, report.errors
    assert (
        system.input("state").type_id
        == "robot.state/v1"
    )
    assert (
        system.output("state").type_id
        == "robot.state/v1"
    )


def test_system_contract_changes_definition_identity() -> None:
    base = SystemModel(
        name="sensor"
    )

    with_output = SystemModel(
        name="sensor",
        outputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
        ),
    )

    changed_type = SystemModel(
        name="sensor",
        outputs=(
            SystemPort(
                name="lidar",
                type_id="spatial.point_cloud/v2",
            ),
        ),
    )

    assert (
        system_definition_digest(base)
        != system_definition_digest(
            with_output
        )
    )

    assert (
        system_definition_digest(
            with_output
        )
        != system_definition_digest(
            changed_type
        )
    )


def test_empty_contract_preserves_existing_canonical_shape() -> None:
    system = SystemModel(
        name="flat"
    )

    canonical = system_to_canonical(
        system
    )

    assert "inputs" not in canonical
    assert "outputs" not in canonical

    assert json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_system_schema_exposes_system_ports() -> None:
    schema = system_json_schema()

    assert "inputs" in schema["properties"]
    assert "outputs" in schema["properties"]
    assert "SystemPort" in schema["$defs"]

    port = schema[
        "$defs"
    ]["SystemPort"]

    assert "name" in port["properties"]
    assert "type_id" in port["properties"]
    assert "optional" in port["properties"]


def test_checked_system_schema_matches_generated_schema() -> None:
    root = Path(__file__).resolve().parents[1]

    checked = json.loads(
        (
            root
            / "src/nodrix/schemas/system-v1.schema.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert checked == system_json_schema()


def test_system_port_is_public_api() -> None:
    assert nodrix.SystemPort is SystemPort


def test_system_port_optional_semantics_change_identity() -> None:
    required = SystemModel(
        name="consumer",
        inputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
        ),
    )

    optional = SystemModel(
        name="consumer",
        inputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
                optional=True,
            ),
        ),
    )

    assert (
        system_definition_digest(required)
        != system_definition_digest(optional)
    )
