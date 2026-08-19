from __future__ import annotations

from pydantic import ValidationError
import pytest

import nodrix
from nodrix.system import (
    LocalBackend,
    BackendContext,
    BackendSystemLink,
    DefinitionCatalog,
    Graph,
    NodeInstance,
    ResourceInstance,
    SystemBoundaryBindings,
    SystemEndpointKind,
    SystemExecutionContext,
    SystemExecutionContextOverride,
    SystemInstance,
    SystemLink,
    SystemModel,
    SystemParameter,
    SystemParameterBinding,
    SystemParameterType,
    SystemPlanningError,
    SystemPort,
    SystemPortBinding,
    SystemResourceBinding,
    SystemResourceRequirement,
    SystemOrchestrator,
    Target,
    dumps_system,
    loads_system,
    lower_local_context,
    parse_system_endpoint,
    plan_execution_scopes,
    plan_system,
    system_to_canonical,
    child_system_execution_context,
    system_execution_context_digest,
    validate_system,
)
from nodrix.sdk import NodeDefinition, ParameterDefinition
from nodrix.system.definition import system_definition_record


POINT_CLOUD = "spatial.point_cloud/v1"
IMAGE = "image.rgb/v1"


def _revision(system: SystemModel) -> str:
    return system_definition_record(system).revision.canonical


def _resolver(*systems: SystemModel):
    definitions = {
        _revision(system): system
        for system in systems
    }
    return lambda requested: definitions.get(requested.canonical)


def _source_system(
    name: str = "sensor",
    *,
    type_id: str = POINT_CLOUD,
    bound: bool = True,
    target: str | None = None,
) -> SystemModel:
    return SystemModel(
        name=name,
        outputs=(
            SystemPort(
                name="cloud",
                type_id=type_id,
            ),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="source",
                        uses="demo.source",
                        target=target,
                    ),
                ),
            ),
        ),
        bindings=(
            SystemBoundaryBindings(
                outputs=(
                    SystemPortBinding(
                        port="cloud",
                        endpoint="main/source.cloud",
                    ),
                ),
            )
            if bound
            else SystemBoundaryBindings()
        ),
    )


def _sink_system(
    name: str = "mapping",
    *,
    type_id: str = POINT_CLOUD,
    target: str | None = None,
    optional_input: bool = False,
) -> SystemModel:
    return SystemModel(
        name=name,
        inputs=(
            SystemPort(
                name="cloud",
                type_id=type_id,
                optional=optional_input,
            ),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="sink",
                        uses="demo.sink",
                        target=target,
                    ),
                ),
            ),
        ),
        bindings=SystemBoundaryBindings(
            inputs=(
                SystemPortBinding(
                    port="cloud",
                    endpoint="main/sink.cloud",
                ),
            ),
        ),
    )


def test_system_endpoint_parser_preserves_all_namespaces() -> None:
    application = parse_system_endpoint(" driver.cloud ")
    graph = parse_system_endpoint("mapping/voxel.cloud")
    child = parse_system_endpoint("system:lidar.cloud")

    assert application.kind is SystemEndpointKind.APPLICATION
    assert (application.instance, application.port) == ("driver", "cloud")
    assert graph.kind is SystemEndpointKind.GRAPH
    assert (graph.scope, graph.instance, graph.port) == (
        "mapping",
        "voxel",
        "cloud",
    )
    assert child.kind is SystemEndpointKind.SYSTEM
    assert (child.instance, child.port) == ("lidar", "cloud")


def test_system_endpoint_rejects_incomplete_child_reference() -> None:
    with pytest.raises(ValueError):
        parse_system_endpoint("system:lidar")


@pytest.mark.parametrize(
    ("value_type", "accepted", "rejected"),
    [
        (SystemParameterType.STRING, "fast", 1),
        (SystemParameterType.INTEGER, 4, True),
        (SystemParameterType.NUMBER, 1.5, False),
        (SystemParameterType.BOOLEAN, True, 1),
        (SystemParameterType.OBJECT, {"leaf": 0.2}, [1]),
        (SystemParameterType.ARRAY, [1, 2], {"one": 1}),
    ],
)
def test_system_parameter_uses_portable_value_types(
    value_type: SystemParameterType,
    accepted: object,
    rejected: object,
) -> None:
    parameter = SystemParameter(
        name="value",
        type=value_type,
    )

    assert parameter.accepts(accepted)
    assert not parameter.accepts(rejected)


def test_system_parameter_rejects_wrong_default_type() -> None:
    with pytest.raises(ValidationError, match="default"):
        SystemParameter(
            name="rate",
            type="number",
            default="fast",
        )


def test_interface_contract_round_trips_with_instance_values() -> None:
    child = SystemModel(
        name="driver",
        parameters=(
            SystemParameter(
                name="rate",
                type="integer",
                required=True,
            ),
        ),
        resource_requirements=(
            SystemResourceRequirement(
                name="device",
                uses="livox.device",
            ),
        ),
        resources=(
            ResourceInstance(
                name="device",
                uses="livox.device",
            ),
        ),
        bindings=SystemBoundaryBindings(
            resources=(
                SystemResourceBinding(
                    resource="device",
                    instance="device",
                ),
            ),
        ),
    )
    parent = SystemModel(
        name="robot",
        resources=(
            ResourceInstance(
                name="mid360",
                uses="livox.device",
            ),
        ),
        systems=(
            SystemInstance(
                name="driver",
                uses=_revision(child),
                parameters={"rate": 10},
                resources={"device": "mid360"},
            ),
        ),
    )

    restored = loads_system(
        dumps_system(parent, format="yaml"),
        format="yaml",
    )
    assert restored == parent
    assert restored.system("driver").parameters == {"rate": 10}
    assert restored.system("driver").resources == {"device": "mid360"}

    child_document = system_to_canonical(child)
    assert list(child_document)[:6] == [
        "apiVersion",
        "kind",
        "name",
        "parameters",
        "resourceRequirements",
        "bindings",
    ]


def test_child_parameter_and_resource_bindings_validate_strictly() -> None:
    child = SystemModel(
        name="driver",
        parameters=(
            SystemParameter(
                name="rate",
                type="integer",
                required=True,
            ),
        ),
        resource_requirements=(
            SystemResourceRequirement(
                name="device",
                uses="livox.device",
            ),
        ),
    )
    parent = SystemModel(
        name="robot",
        resources=(
            ResourceInstance(
                name="mid360",
                uses="livox.device",
            ),
        ),
        systems=(
            SystemInstance(
                name="driver",
                uses=_revision(child),
                parameters={"rate": 10},
                resources={"device": "mid360"},
            ),
        ),
    )

    report = validate_system(
        parent,
        system_resolver=_resolver(child),
    )
    assert report.valid, report.errors

    invalid = parent.model_copy(
        update={
            "systems": (
                parent.system("driver").model_copy(
                    update={
                        "parameters": {"rate": "fast"},
                        "resources": {"unknown": "mid360"},
                    }
                ),
            ),
        }
    )
    invalid_report = validate_system(
        invalid,
        system_resolver=_resolver(child),
    )
    assert {item.code for item in invalid_report.errors} >= {
        "SYS173",
        "SYS174",
        "SYS175",
    }


def test_sibling_system_link_validates_direction_and_type() -> None:
    sensor = _source_system()
    mapping = _sink_system()
    parent = SystemModel(
        name="robot",
        systems=(
            SystemInstance(name="sensor", uses=_revision(sensor)),
            SystemInstance(name="mapping", uses=_revision(mapping)),
        ),
        links=(
            SystemLink(
                **{
                    "from": "system:sensor.cloud",
                    "to": "system:mapping.cloud",
                }
            ),
        ),
    )

    report = validate_system(
        parent,
        system_resolver=_resolver(sensor, mapping),
    )
    assert report.valid, report.errors

    wrong_type = parent.model_copy(
        update={
            "systems": (
                parent.system("sensor"),
                SystemInstance(
                    name="mapping",
                    uses=_revision(
                        _sink_system(type_id=IMAGE)
                    ),
                ),
            ),
        }
    )
    mismatched_mapping = _sink_system(type_id=IMAGE)
    mismatch = validate_system(
        wrong_type,
        system_resolver=_resolver(sensor, mismatched_mapping),
    )
    assert any(item.code == "SYS143" for item in mismatch.errors)


def test_parent_boundary_can_bind_directly_to_child_system_port() -> None:
    mapping = _sink_system()
    parent = SystemModel(
        name="mapping-stack",
        inputs=(
            SystemPort(name="cloud", type_id=POINT_CLOUD),
        ),
        systems=(
            SystemInstance(name="mapping", uses=_revision(mapping)),
        ),
        bindings=SystemBoundaryBindings(
            inputs=(
                SystemPortBinding(
                    port="cloud",
                    endpoint="system:mapping.cloud",
                ),
            ),
        ),
    )

    report = validate_system(
        parent,
        system_resolver=_resolver(mapping),
    )
    assert report.valid, report.errors


def test_planner_keeps_child_boundaries_without_flattening() -> None:
    sensor = _source_system()
    mapping = _sink_system()
    parent = SystemModel(
        name="robot",
        systems=(
            SystemInstance(name="sensor", uses=_revision(sensor)),
            SystemInstance(name="mapping", uses=_revision(mapping)),
        ),
        links=(
            SystemLink(
                **{
                    "from": "system:sensor.cloud",
                    "to": "system:mapping.cloud",
                }
            ),
        ),
    )

    plan = plan_system(
        parent,
        system_resolver=_resolver(sensor, mapping),
    )

    assert plan.graphs == ()
    assert len(plan.systems) == 2
    assert plan.child("sensor").plan.bindings.output("cloud").endpoint == (
        "main/source.cloud"
    )
    link = plan.links[0]
    assert link.boundary == "system"
    assert link.transport_required is False
    assert link.source_target == "local"
    assert link.target_target == "local"
    assert link.type_id == POINT_CLOUD
    assert plan_execution_scopes(plan) == ()


def test_local_backend_requires_transport_across_system_runtime_boundaries(
    tmp_path,
) -> None:
    sensor = _source_system()
    mapping = _sink_system()
    parent = SystemModel(
        name="robot",
        systems=(
            SystemInstance(name="sensor", uses=_revision(sensor)),
            SystemInstance(name="mapping", uses=_revision(mapping)),
        ),
        links=(
            SystemLink(
                **{
                    "from": "system:sensor.cloud",
                    "to": "system:mapping.cloud",
                }
            ),
        ),
    )
    plan = plan_system(
        parent,
        system_resolver=_resolver(sensor, mapping),
    )
    backend = LocalBackend(working_directory=tmp_path)
    report = SystemOrchestrator(
        {("local", "local"): backend}
    ).validate_plan(plan)

    unsupported = [
        item
        for item in report.errors
        if item.code == "LOCAL103"
    ]
    assert {item.path for item in unsupported} == {
        "systems.sensor.system_links[0].uses",
        "systems.mapping.system_links[0].uses",
    }


def test_local_backend_lowers_transport_backed_system_link() -> None:
    sensor = _source_system()
    mapping = _sink_system()
    parent = SystemModel(
        name="robot",
        systems=(
            SystemInstance(name="sensor", uses=_revision(sensor)),
            SystemInstance(name="mapping", uses=_revision(mapping)),
        ),
        links=(
            SystemLink(
                **{
                    "from": "system:sensor.cloud",
                    "to": "system:mapping.cloud",
                    "uses": "demo.transport",
                }
            ),
        ),
    )
    plan = plan_system(
        parent,
        system_resolver=_resolver(sensor, mapping),
    )
    link = plan.links[0]
    system_link = BackendSystemLink(
        link=link,
        direction="outbound",
        local_endpoint="main/source.cloud",
        remote_endpoint="main/sink.cloud",
        local_system_path=("sensor",),
        remote_system_path=("mapping",),
    )
    context = BackendContext.from_plan(
        plan.child("sensor").plan,
        "local",
        system_outbound_links=(system_link,),
    )

    report = LocalBackend().validate(context)
    lowering = lower_local_context(context)

    assert report.valid, report.errors
    assert len(lowering.manifest.links) == 1
    lowered = lowering.manifest.links[0]
    assert lowered.source == "source.cloud"
    assert lowered.target == (
        "source.__nodrix_remote__mapping__main__sink__cloud"
    )
    assert lowered.uses == "demo.transport"


def test_planner_rejects_child_port_without_concrete_boundary() -> None:
    sensor = _source_system(bound=False)
    mapping = _sink_system()
    parent = SystemModel(
        name="robot",
        systems=(
            SystemInstance(name="sensor", uses=_revision(sensor)),
            SystemInstance(name="mapping", uses=_revision(mapping)),
        ),
        links=(
            SystemLink(
                **{
                    "from": "system:sensor.cloud",
                    "to": "system:mapping.cloud",
                }
            ),
        ),
    )

    with pytest.raises(SystemPlanningError) as exc_info:
        plan_system(
            parent,
            system_resolver=_resolver(sensor, mapping),
        )

    assert exc_info.value.code == "PLAN410"


def test_planner_records_effective_child_parameter_values() -> None:
    base = _sink_system(
        name="mapper",
        optional_input=True,
    )
    child = base.model_copy(
        update={
            "parameters": (
                SystemParameter(
                    name="leaf",
                    type="number",
                    required=True,
                ),
            ),
            "bindings": base.bindings.model_copy(
                update={
                    "parameters": (
                        SystemParameterBinding(
                            parameter="leaf",
                            targets=("node:main/sink.leaf",),
                        ),
                    ),
                }
            ),
        }
    )
    parent = SystemModel(
        name="robot",
        systems=(
            SystemInstance(
                name="mapper",
                uses=_revision(child),
                parameters={"leaf": 0.25},
            ),
        ),
    )

    plan = plan_system(
        parent,
        system_resolver=_resolver(child),
    )

    child_plan = plan.child("mapper").plan
    assert child_plan.parameters[0].configured is True
    assert child_plan.parameters[0].value == 0.25
    assert plan.child("mapper").parameters == {"leaf": 0.25}
    assert child_plan.bindings.parameter("leaf").targets == (
        "node:main/sink.leaf",
    )
    assert child_plan.bindings.parameter("leaf").value == 0.25
    assert child_plan.graph("main").node("sink").parameters == {
        "leaf": 0.25
    }


def test_public_parameter_can_bind_through_child_system_boundary() -> None:
    base = _sink_system(
        name="mapper",
        optional_input=True,
    )
    child = base.model_copy(
        update={
            "parameters": (
                SystemParameter(
                    name="leaf",
                    type="number",
                    required=True,
                ),
            ),
            "bindings": base.bindings.model_copy(
                update={
                    "parameters": (
                        SystemParameterBinding(
                            parameter="leaf",
                            targets=("node:main/sink.leaf",),
                        ),
                    ),
                }
            ),
        }
    )
    parent = SystemModel(
        name="mapping-stack",
        parameters=(
            SystemParameter(
                name="voxel_size",
                type="number",
                default=0.3,
            ),
        ),
        systems=(
            SystemInstance(name="mapper", uses=_revision(child)),
        ),
        bindings=SystemBoundaryBindings(
            parameters=(
                SystemParameterBinding(
                    parameter="voxel_size",
                    targets=("system:mapper.leaf",),
                ),
            ),
        ),
    )

    report = validate_system(
        parent,
        system_resolver=_resolver(child),
    )
    plan = plan_system(
        parent,
        system_resolver=_resolver(child),
    )

    assert report.valid, report.errors
    assert plan.child("mapper").parameters == {"leaf": 0.3}
    assert plan.child("mapper").plan.graph("main").node("sink").parameters == {
        "leaf": 0.3
    }

    mismatch = parent.model_copy(
        update={
            "parameters": (
                SystemParameter(
                    name="voxel_size",
                    type="string",
                    default="large",
                ),
            ),
        }
    )
    mismatch_report = validate_system(
        mismatch,
        system_resolver=_resolver(child),
    )
    assert any(item.code == "SYS179" for item in mismatch_report.errors)


def _resource_child(
    *,
    bind_boundary: bool = True,
    target: str | None = None,
) -> SystemModel:
    return SystemModel(
        name="driver",
        targets=(
            (
                Target(
                    name=target,
                    kind="host",
                ),
            )
            if target is not None
            else ()
        ),
        resource_requirements=(
            SystemResourceRequirement(
                name="device",
                uses="livox.device",
            ),
        ),
        resources=(
            ResourceInstance(
                name="internal-device",
                uses="livox.device",
                target=target,
            ),
        ),
        bindings=(
            SystemBoundaryBindings(
                resources=(
                    SystemResourceBinding(
                        resource="device",
                        instance="internal-device",
                    ),
                ),
            )
            if bind_boundary
            else SystemBoundaryBindings()
        ),
    )


def test_planner_compiles_parent_resource_into_child_boundary() -> None:
    child = _resource_child()
    parent = SystemModel(
        name="robot",
        resources=(
            ResourceInstance(
                name="mid360",
                uses="livox.device",
                parameters={"address": "192.168.1.42"},
            ),
        ),
        systems=(
            SystemInstance(
                name="driver",
                uses=_revision(child),
                resources={"device": "mid360"},
            ),
        ),
    )

    plan = plan_system(
        parent,
        system_resolver=_resolver(child),
    )

    binding = plan.child("driver").resource_bindings[0]
    assert binding.requirement == "device"
    assert binding.parent_resource == "mid360"
    assert binding.child_resource == "internal-device"
    assert binding.parameters == {"address": "192.168.1.42"}
    assert (binding.target, binding.backend) == ("local", "local")


def test_planner_rejects_child_resource_without_concrete_boundary() -> None:
    child = _resource_child(bind_boundary=False)
    parent = SystemModel(
        name="robot",
        resources=(
            ResourceInstance(name="mid360", uses="livox.device"),
        ),
        systems=(
            SystemInstance(
                name="driver",
                uses=_revision(child),
                resources={"device": "mid360"},
            ),
        ),
    )

    with pytest.raises(SystemPlanningError) as exc_info:
        plan_system(parent, system_resolver=_resolver(child))

    assert exc_info.value.code == "PLAN413"


def test_planner_rejects_cross_scope_direct_child_resource() -> None:
    child = _resource_child(target="sensor-host")
    parent = SystemModel(
        name="robot",
        targets=(Target(name="robot-host", kind="host"),),
        resources=(
            ResourceInstance(
                name="mid360",
                uses="livox.device",
                target="robot-host",
            ),
        ),
        systems=(
            SystemInstance(
                name="driver",
                uses=_revision(child),
                resources={"device": "mid360"},
            ),
        ),
    )

    with pytest.raises(SystemPlanningError) as exc_info:
        plan_system(parent, system_resolver=_resolver(child))

    assert exc_info.value.code == "PLAN412"


def test_orchestrator_rejects_inherited_resource_for_legacy_local_backend(
    tmp_path,
) -> None:
    child = _resource_child()
    parent = SystemModel(
        name="robot",
        resources=(
            ResourceInstance(name="mid360", uses="livox.device"),
        ),
        systems=(
            SystemInstance(
                name="driver",
                uses=_revision(child),
                resources={"device": "mid360"},
            ),
        ),
    )
    plan = plan_system(parent, system_resolver=_resolver(child))
    backend = LocalBackend(working_directory=tmp_path)
    orchestrator = SystemOrchestrator({("local", "local"): backend})

    report = orchestrator.validate_plan(plan)

    assert any(
        item.code == "BACKEND104"
        and item.path == "systems.driver.inherited_resources"
        for item in report.errors
    )


def test_parameter_binding_rejects_explicit_target_value_conflict() -> None:
    system = SystemModel(
        name="mapper",
        parameters=(
            SystemParameter(name="leaf", type="number"),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="sink",
                        uses="demo.sink",
                        parameters={"leaf": 0.5},
                    ),
                ),
            ),
        ),
        bindings=SystemBoundaryBindings(
            parameters=(
                SystemParameterBinding(
                    parameter="leaf",
                    targets=("node:main/sink.leaf",),
                ),
            ),
        ),
    )

    report = validate_system(system)
    assert any(item.code == "SYS178" for item in report.errors)


def test_parameter_binding_validates_portable_type_against_sdk_annotation() -> None:
    definition = NodeDefinition(
        name="demo.sink",
        inputs=(),
        outputs=(),
        parameters=(
            ParameterDefinition(
                name="leaf",
                annotation=float,
                required=True,
            ),
        ),
        dependencies=(),
        implementation=lambda: None,
    )
    catalog = DefinitionCatalog.from_definitions(
        nodes={"demo.sink": definition},
    )

    def system(value_type: str) -> SystemModel:
        return SystemModel(
            name="mapper",
            parameters=(
                SystemParameter(name="leaf", type=value_type),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="sink", uses="demo.sink"),
                    ),
                ),
            ),
            bindings=SystemBoundaryBindings(
                parameters=(
                    SystemParameterBinding(
                        parameter="leaf",
                        targets=("node:main/sink.leaf",),
                    ),
                ),
            ),
        )

    assert validate_system(system("number"), catalog=catalog).valid
    mismatch = validate_system(system("string"), catalog=catalog)
    assert any(item.code == "SYS179" for item in mismatch.errors)


def test_planner_binds_each_child_to_derived_execution_context() -> None:
    child = _source_system()
    parent = SystemModel(
        name="robot",
        systems=(
            SystemInstance(name="sensor", uses=_revision(child)),
        ),
    )
    context = SystemExecutionContext(
        variables={"ROS_DISTRO": "jazzy", "MODE": "root"},
        systems={
            "sensor": SystemExecutionContextOverride(
                variables={"MODE": "sensor"},
            ),
        },
    )

    plan = plan_system(
        parent,
        execution_context=context,
        system_resolver=_resolver(child),
    )
    child_context = child_system_execution_context(context, "sensor")

    assert child_context is not None
    assert plan.execution_context_sha256 == (
        system_execution_context_digest(context)
    )
    assert plan.child("sensor").plan.execution_context_sha256 == (
        system_execution_context_digest(child_context)
    )


def test_interface_types_are_public_sdk() -> None:
    assert nodrix.SystemParameter is SystemParameter
    assert nodrix.SystemResourceRequirement is SystemResourceRequirement
    assert nodrix.SystemEndpointKind is SystemEndpointKind
    assert nodrix.BackendSystemLink is BackendSystemLink
