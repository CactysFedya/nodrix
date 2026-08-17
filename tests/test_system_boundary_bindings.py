from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

import nodrix
from nodrix.system import (
    ApplicationInstance,
    Graph,
    NodeInstance,
    SystemBoundaryBindings,
    SystemModel,
    SystemPort,
    SystemPortBinding,
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


def test_system_port_binding_normalizes_values() -> None:
    binding = SystemPortBinding(
        port="  lidar  ",
        endpoint="  driver.lidar  ",
    )

    assert binding.port == "lidar"
    assert binding.endpoint == "driver.lidar"


@pytest.mark.parametrize(
    "endpoint",
    (
        "driver",
        "/node.port",
        "graph/node",
    ),
)
def test_system_port_binding_requires_system_endpoint_syntax(
    endpoint: str,
) -> None:
    with pytest.raises(
        ValidationError,
    ):
        SystemPortBinding(
            port="lidar",
            endpoint=endpoint,
        )


def test_boundary_bindings_round_trip_canonically() -> None:
    system = SystemModel(
        name="sensor",
        outputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
        ),
        applications=(
            ApplicationInstance(
                name="driver",
                uses="sensor.driver",
            ),
        ),
        bindings=SystemBoundaryBindings(
            outputs=(
                SystemPortBinding(
                    port="lidar",
                    endpoint="driver.lidar",
                ),
            ),
        ),
    )

    text = dumps_system(
        system,
        format="yaml",
    )

    restored = loads_system(
        text,
        format="yaml",
    )

    assert restored == system
    assert (
        restored.bindings.output(
            "lidar"
        ).endpoint
        == "driver.lidar"
    )

    canonical = system_to_canonical(
        restored
    )

    assert canonical["bindings"] == {
        "outputs": [
            {
                "port": "lidar",
                "endpoint": "driver.lidar",
            }
        ]
    }


def test_empty_bindings_preserve_existing_canonical_shape() -> None:
    system = SystemModel(
        name="empty"
    )

    canonical = system_to_canonical(
        system
    )

    assert "bindings" not in canonical


def test_binding_changes_system_definition_identity() -> None:
    base = SystemModel(
        name="sensor",
        outputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
        ),
        applications=(
            ApplicationInstance(
                name="driver",
                uses="sensor.driver",
            ),
        ),
    )

    bound = SystemModel(
        name="sensor",
        outputs=base.outputs,
        applications=base.applications,
        bindings=SystemBoundaryBindings(
            outputs=(
                SystemPortBinding(
                    port="lidar",
                    endpoint="driver.lidar",
                ),
            ),
        ),
    )

    assert (
        system_definition_digest(base)
        != system_definition_digest(bound)
    )


def test_input_binding_must_reference_declared_system_input() -> None:
    system = SystemModel(
        name="consumer",
        applications=(
            ApplicationInstance(
                name="consumer",
                uses="consumer.app",
            ),
        ),
        bindings=SystemBoundaryBindings(
            inputs=(
                SystemPortBinding(
                    port="missing",
                    endpoint="consumer.input",
                ),
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert any(
        item.code == "SYS053"
        for item in report.errors
    )


def test_output_binding_must_reference_declared_system_output() -> None:
    system = SystemModel(
        name="producer",
        applications=(
            ApplicationInstance(
                name="producer",
                uses="producer.app",
            ),
        ),
        bindings=SystemBoundaryBindings(
            outputs=(
                SystemPortBinding(
                    port="missing",
                    endpoint="producer.output",
                ),
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert any(
        item.code == "SYS054"
        for item in report.errors
    )


@pytest.mark.parametrize(
    ("direction", "code"),
    (
        ("inputs", "SYS051"),
        ("outputs", "SYS052"),
    ),
)
def test_system_port_may_not_have_duplicate_boundary_bindings(
    direction: str,
    code: str,
) -> None:
    port = SystemPort(
        name="data",
        type_id=POINT_CLOUD,
    )

    bindings = (
        SystemPortBinding(
            port="data",
            endpoint="worker.first",
        ),
        SystemPortBinding(
            port="data",
            endpoint="worker.second",
        ),
    )

    system = SystemModel(
        name="duplicate",
        inputs=(port,)
        if direction == "inputs"
        else (),
        outputs=(port,)
        if direction == "outputs"
        else (),
        applications=(
            ApplicationInstance(
                name="worker",
                uses="worker.app",
            ),
        ),
        bindings=SystemBoundaryBindings(
            **{
                direction: bindings,
            }
        ),
    )

    report = validate_system(
        system
    )

    assert any(
        item.code == code
        for item in report.errors
    )


def test_boundary_binding_requires_existing_application() -> None:
    system = SystemModel(
        name="sensor",
        outputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
        ),
        bindings=SystemBoundaryBindings(
            outputs=(
                SystemPortBinding(
                    port="lidar",
                    endpoint="missing.lidar",
                ),
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert any(
        item.code == "SYS041"
        for item in report.errors
    )


def test_boundary_binding_requires_existing_graph() -> None:
    system = SystemModel(
        name="sensor",
        outputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
        ),
        bindings=SystemBoundaryBindings(
            outputs=(
                SystemPortBinding(
                    port="lidar",
                    endpoint="missing/node.lidar",
                ),
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert any(
        item.code == "SYS042"
        for item in report.errors
    )


def test_boundary_binding_requires_existing_graph_node() -> None:
    system = SystemModel(
        name="sensor",
        outputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
        ),
        graphs=(
            Graph(
                name="pipeline",
            ),
        ),
        bindings=SystemBoundaryBindings(
            outputs=(
                SystemPortBinding(
                    port="lidar",
                    endpoint="pipeline/missing.lidar",
                ),
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert any(
        item.code == "SYS043"
        for item in report.errors
    )


def test_existing_graph_node_boundary_is_structurally_valid_without_catalog() -> None:
    system = SystemModel(
        name="sensor",
        inputs=(
            SystemPort(
                name="imu",
                type_id=IMU,
            ),
        ),
        outputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD,
            ),
        ),
        graphs=(
            Graph(
                name="pipeline",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="sensor.worker",
                    ),
                ),
            ),
        ),
        bindings=SystemBoundaryBindings(
            inputs=(
                SystemPortBinding(
                    port="imu",
                    endpoint="pipeline/worker.imu",
                ),
            ),
            outputs=(
                SystemPortBinding(
                    port="lidar",
                    endpoint="pipeline/worker.lidar",
                ),
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert report.valid, report.errors


def test_schema_exposes_boundary_bindings() -> None:
    schema = system_json_schema()

    assert "bindings" in schema["properties"]
    assert (
        "SystemBoundaryBindings"
        in schema["$defs"]
    )
    assert (
        "SystemPortBinding"
        in schema["$defs"]
    )


def test_checked_schema_matches_generated_schema() -> None:
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


def test_boundary_binding_is_public_api() -> None:
    assert (
        nodrix.SystemBoundaryBindings
        is SystemBoundaryBindings
    )
    assert (
        nodrix.SystemPortBinding
        is SystemPortBinding
    )
