from __future__ import annotations

from nodrix.sdk.definitions import (
    MessageDefinition,
    NodeDefinition,
    PortDefinition,
)
from nodrix.system import (
    ApplicationInstance,
    DefinitionCatalog,
    Graph,
    NodeInstance,
    SystemBoundaryBindings,
    SystemModel,
    SystemPort,
    SystemPortBinding,
    validate_system,
)


POINT_CLOUD_V1 = "spatial.point_cloud/v1"
POINT_CLOUD_V2 = "spatial.point_cloud/v2"
IMAGE_V1 = "image.rgb/v1"


def _node_definition(
    *,
    inputs: tuple[PortDefinition, ...] = (),
    outputs: tuple[PortDefinition, ...] = (),
) -> NodeDefinition:
    return NodeDefinition(
        name="worker",
        inputs=inputs,
        outputs=outputs,
        parameters=(),
        dependencies=(),
        implementation=object(),
    )


def _graph_system(
    *,
    inputs: tuple[SystemPort, ...] = (),
    outputs: tuple[SystemPort, ...] = (),
    input_bindings: tuple[SystemPortBinding, ...] = (),
    output_bindings: tuple[SystemPortBinding, ...] = (),
) -> SystemModel:
    return SystemModel(
        name="typed-boundary",
        inputs=inputs,
        outputs=outputs,
        graphs=(
            Graph(
                name="pipeline",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="test.worker",
                    ),
                ),
            ),
        ),
        bindings=SystemBoundaryBindings(
            inputs=input_bindings,
            outputs=output_bindings,
        ),
    )


def test_graph_input_binding_accepts_matching_contract() -> None:
    system = _graph_system(
        inputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        input_bindings=(
            SystemPortBinding(
                port="lidar",
                endpoint="pipeline/worker.lidar",
            ),
        ),
    )

    catalog = DefinitionCatalog.from_definitions(
        nodes={
            "test.worker": _node_definition(
                inputs=(
                    PortDefinition(
                        name="lidar",
                        type_id=POINT_CLOUD_V1,
                    ),
                ),
            ),
        }
    )

    report = validate_system(
        system,
        catalog=catalog,
    )

    assert report.valid, report.errors
    assert not any(
        item.code == "SYS153"
        for item in report.diagnostics
    )


def test_graph_input_binding_rejects_contract_mismatch() -> None:
    system = _graph_system(
        inputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        input_bindings=(
            SystemPortBinding(
                port="lidar",
                endpoint="pipeline/worker.lidar",
            ),
        ),
    )

    catalog = DefinitionCatalog.from_definitions(
        nodes={
            "test.worker": _node_definition(
                inputs=(
                    PortDefinition(
                        name="lidar",
                        type_id=IMAGE_V1,
                    ),
                ),
            ),
        }
    )

    report = validate_system(
        system,
        catalog=catalog,
    )

    mismatch = next(
        item
        for item in report.errors
        if item.code == "SYS153"
    )

    assert POINT_CLOUD_V1 in mismatch.message
    assert IMAGE_V1 in mismatch.message


def test_graph_output_binding_accepts_matching_contract() -> None:
    system = _graph_system(
        outputs=(
            SystemPort(
                name="cloud",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        output_bindings=(
            SystemPortBinding(
                port="cloud",
                endpoint="pipeline/worker.cloud",
            ),
        ),
    )

    catalog = DefinitionCatalog.from_definitions(
        nodes={
            "test.worker": _node_definition(
                outputs=(
                    PortDefinition(
                        name="cloud",
                        type_id=POINT_CLOUD_V1,
                    ),
                ),
            ),
        }
    )

    report = validate_system(
        system,
        catalog=catalog,
    )

    assert report.valid, report.errors
    assert not any(
        item.code == "SYS154"
        for item in report.diagnostics
    )


def test_graph_output_binding_rejects_contract_mismatch() -> None:
    system = _graph_system(
        outputs=(
            SystemPort(
                name="cloud",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        output_bindings=(
            SystemPortBinding(
                port="cloud",
                endpoint="pipeline/worker.cloud",
            ),
        ),
    )

    catalog = DefinitionCatalog.from_definitions(
        nodes={
            "test.worker": _node_definition(
                outputs=(
                    PortDefinition(
                        name="cloud",
                        type_id=IMAGE_V1,
                    ),
                ),
            ),
        }
    )

    report = validate_system(
        system,
        catalog=catalog,
    )

    mismatch = next(
        item
        for item in report.errors
        if item.code == "SYS154"
    )

    assert IMAGE_V1 in mismatch.message
    assert POINT_CLOUD_V1 in mismatch.message


def test_graph_input_binding_accepts_declared_compatible_version() -> None:
    system = _graph_system(
        inputs=(
            SystemPort(
                name="lidar",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        input_bindings=(
            SystemPortBinding(
                port="lidar",
                endpoint="pipeline/worker.lidar",
            ),
        ),
    )

    catalog = DefinitionCatalog.from_definitions(
        nodes={
            "test.worker": _node_definition(
                inputs=(
                    PortDefinition(
                        name="lidar",
                        type_id=POINT_CLOUD_V2,
                    ),
                ),
            ),
        },
        messages=(
            MessageDefinition(
                type_id=POINT_CLOUD_V2,
                version=2,
                python_type=bytes,
                compatible_versions=(1,),
            ),
        ),
    )

    report = validate_system(
        system,
        catalog=catalog,
    )

    assert report.valid, report.errors
    assert not any(
        item.code == "SYS153"
        for item in report.diagnostics
    )


def test_graph_boundary_without_catalog_is_structural_only() -> None:
    system = _graph_system(
        outputs=(
            SystemPort(
                name="cloud",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        output_bindings=(
            SystemPortBinding(
                port="cloud",
                endpoint="pipeline/worker.cloud",
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert report.valid, report.errors
    assert not any(
        item.code in {"SYS153", "SYS154"}
        for item in report.diagnostics
    )


def test_application_input_binding_warns_contract_unverified() -> None:
    system = SystemModel(
        name="application-input",
        inputs=(
            SystemPort(
                name="data",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        applications=(
            ApplicationInstance(
                name="worker",
                uses="external.worker",
            ),
        ),
        bindings=SystemBoundaryBindings(
            inputs=(
                SystemPortBinding(
                    port="data",
                    endpoint="worker.data",
                ),
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert report.valid, report.errors
    assert any(
        item.code == "SYS155"
        for item in report.warnings
    )


def test_application_output_binding_warns_contract_unverified() -> None:
    system = SystemModel(
        name="application-output",
        outputs=(
            SystemPort(
                name="data",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        applications=(
            ApplicationInstance(
                name="worker",
                uses="external.worker",
            ),
        ),
        bindings=SystemBoundaryBindings(
            outputs=(
                SystemPortBinding(
                    port="data",
                    endpoint="worker.data",
                ),
            ),
        ),
    )

    report = validate_system(
        system
    )

    assert report.valid, report.errors
    assert any(
        item.code == "SYS156"
        for item in report.warnings
    )


def test_missing_application_input_does_not_claim_unverified_contract() -> None:
    system = SystemModel(
        name="missing-input-app",
        inputs=(
            SystemPort(
                name="data",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        bindings=SystemBoundaryBindings(
            inputs=(
                SystemPortBinding(
                    port="data",
                    endpoint="missing.data",
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
    assert not any(
        item.code == "SYS155"
        for item in report.warnings
    )


def test_missing_application_output_does_not_claim_unverified_contract() -> None:
    system = SystemModel(
        name="missing-output-app",
        outputs=(
            SystemPort(
                name="data",
                type_id=POINT_CLOUD_V1,
            ),
        ),
        bindings=SystemBoundaryBindings(
            outputs=(
                SystemPortBinding(
                    port="data",
                    endpoint="missing.data",
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
    assert not any(
        item.code == "SYS156"
        for item in report.warnings
    )
