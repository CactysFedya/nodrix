from __future__ import annotations

from nodrix.sdk.definitions import MessageDefinition, NodeDefinition, PortDefinition
from nodrix.system import (
    ApplicationInstance,
    Artifact,
    Connection,
    DefinitionCatalog,
    Graph,
    NodeInstance,
    ResourceInstance,
    SystemExecutionPlan,
    SystemLink,
    SystemModel,
    SystemPlanningError,
    Target,
    plan_system,
)
from nodrix.system.planning import SYSTEM_EXECUTION_PLAN_SCHEMA


def _expect_planning_error(code: str, callback) -> SystemPlanningError:
    try:
        callback()
    except SystemPlanningError as exc:
        assert exc.code == code
        return exc
    raise AssertionError(f"expected {code}")


def test_planner_synthesizes_implicit_local_target() -> None:
    system = SystemModel(
        name="implicit-local",
        graphs=(
            Graph(
                name="main",
                nodes=(NodeInstance(name="worker", uses="demo.worker"),),
            ),
        ),
    )

    plan = plan_system(system)

    assert isinstance(plan, SystemExecutionPlan)
    assert plan.schema_id == SYSTEM_EXECUTION_PLAN_SCHEMA
    assert plan.targets[0].name == "local"
    assert plan.targets[0].backend == "local"
    assert plan.targets[0].implicit is True
    assert plan.graph("main").node("worker").target == "local"
    assert plan.graph("main").node("worker").backend == "local"


def test_single_target_becomes_default_and_resolves_backend() -> None:
    system = SystemModel(
        name="single-target",
        targets=(
            Target(
                name="raspberry_pi",
                kind="host",
                properties={"backend": "dora", "arch": "aarch64"},
            ),
        ),
        graphs=(
            Graph(
                name="perception",
                nodes=(NodeInstance(name="detector", uses="vision.detect"),),
            ),
        ),
    )

    plan = plan_system(system)
    node = plan.graph("perception").node("detector")

    assert node.target == "raspberry_pi"
    assert node.backend == "dora"
    assert plan.target("raspberry_pi").properties["arch"] == "aarch64"


def test_multiple_targets_require_explicit_placement() -> None:
    system = SystemModel(
        name="ambiguous",
        targets=(Target(name="pi"), Target(name="workstation")),
        graphs=(
            Graph(
                name="main",
                nodes=(NodeInstance(name="worker", uses="demo.worker"),),
            ),
        ),
    )

    exc = _expect_planning_error("PLAN201", lambda: plan_system(system))
    assert "multiple targets" in exc.message


def test_resource_dependencies_get_deterministic_order() -> None:
    system = SystemModel(
        name="resources",
        resources=(
            ResourceInstance(name="session", uses="driver.session"),
            ResourceInstance(
                name="camera",
                uses="camera.device",
                bindings={"session": "session"},
            ),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="source",
                        uses="camera.source",
                        resources={"camera": "camera"},
                    ),
                ),
            ),
        ),
    )

    plan = plan_system(system)

    assert plan.resource_order == ("session", "camera")


def test_resource_dependency_cycle_is_rejected() -> None:
    system = SystemModel(
        name="resource-cycle",
        resources=(
            ResourceInstance(name="a", uses="demo.a", bindings={"b": "b"}),
            ResourceInstance(name="b", uses="demo.b", bindings={"a": "a"}),
        ),
    )

    _expect_planning_error("PLAN303", lambda: plan_system(system))


def test_direct_resource_binding_cannot_cross_targets() -> None:
    system = SystemModel(
        name="resource-locality",
        targets=(Target(name="pi"), Target(name="workstation")),
        resources=(
            ResourceInstance(name="gpu", uses="compute.gpu", target="workstation"),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="detector",
                        uses="vision.detect",
                        target="pi",
                        resources={"gpu": "gpu"},
                    ),
                ),
            ),
        ),
    )

    _expect_planning_error("PLAN301", lambda: plan_system(system))


def test_graph_connection_cannot_hide_cross_target_transport() -> None:
    system = SystemModel(
        name="explicit-boundary",
        targets=(Target(name="pi"), Target(name="workstation")),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(name="source", uses="demo.source", target="pi"),
                    NodeInstance(name="sink", uses="demo.sink", target="workstation"),
                ),
                connections=(
                    Connection(**{"from": "source.output", "to": "sink.input"}),
                ),
            ),
        ),
    )

    exc = _expect_planning_error("PLAN401", lambda: plan_system(system))
    assert "explicit SystemLink" in exc.message


def test_graph_topological_order_and_cycle_warning() -> None:
    acyclic = SystemModel(
        name="ordered",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(name="a", uses="demo.a"),
                    NodeInstance(name="b", uses="demo.b"),
                    NodeInstance(name="c", uses="demo.c"),
                ),
                connections=(
                    Connection(**{"from": "a.output", "to": "b.input"}),
                    Connection(**{"from": "b.output", "to": "c.input"}),
                ),
            ),
        ),
    )
    plan = plan_system(acyclic)
    assert plan.graph("main").topological_order == ("a", "b", "c")
    assert plan.graph("main").acyclic is True

    cyclic = SystemModel(
        name="feedback",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(name="a", uses="demo.a"),
                    NodeInstance(name="b", uses="demo.b"),
                ),
                connections=(
                    Connection(**{"from": "a.output", "to": "b.input"}),
                    Connection(**{"from": "b.output", "to": "a.input"}),
                ),
            ),
        ),
    )
    plan = plan_system(cyclic)
    assert plan.graph("main").acyclic is False
    assert any(item.code == "PLAN101" for item in plan.diagnostics)


def test_same_target_cross_graph_link_can_stay_backend_internal() -> None:
    system = SystemModel(
        name="cross-graph",
        graphs=(
            Graph(name="capture", nodes=(NodeInstance(name="source", uses="demo.source"),)),
            Graph(name="mapping", nodes=(NodeInstance(name="sink", uses="demo.sink"),)),
        ),
        links=(
            SystemLink(**{"from": "capture/source.output", "to": "mapping/sink.input"}),
        ),
    )

    plan = plan_system(system)
    link = plan.links[0]

    assert link.boundary == "cross_graph"
    assert link.transport_required is False
    assert link.source_target == link.target_target == "local"


def test_cross_target_link_requires_explicit_transport() -> None:
    base = dict(
        name="remote",
        targets=(Target(name="pi"), Target(name="workstation")),
        graphs=(
            Graph(name="capture", nodes=(NodeInstance(name="source", uses="demo.source", target="pi"),)),
            Graph(name="mapping", nodes=(NodeInstance(name="sink", uses="demo.sink", target="workstation"),)),
        ),
    )

    missing = SystemModel(
        **base,
        links=(SystemLink(**{"from": "capture/source.output", "to": "mapping/sink.input"}),),
    )
    _expect_planning_error("PLAN403", lambda: plan_system(missing))

    explicit = SystemModel(
        **base,
        links=(
            SystemLink(
                **{
                    "from": "capture/source.output",
                    "to": "mapping/sink.input",
                    "uses": "transport.dds",
                }
            ),
        ),
    )
    plan = plan_system(explicit)
    assert plan.links[0].boundary == "cross_target"
    assert plan.links[0].transport_required is True
    assert plan.links[0].transport_uses == "transport.dds"


def test_application_boundary_requires_integration_transport() -> None:
    system = SystemModel(
        name="application-boundary",
        applications=(ApplicationInstance(name="fastlio2", uses="ros2.fastlio2"),),
        graphs=(
            Graph(name="mapping", nodes=(NodeInstance(name="cloud", uses="mapping.cloud"),)),
        ),
        links=(
            SystemLink(**{"from": "fastlio2.output", "to": "mapping/cloud.input"}),
        ),
    )

    _expect_planning_error("PLAN402", lambda: plan_system(system))


def test_catalog_resolves_node_and_connection_contracts_and_artifact_placement() -> None:
    type_id = "vision.frame/v1"
    message = MessageDefinition(type_id=type_id, version=1, python_type=object)
    source = NodeDefinition(
        name="vision.source",
        inputs=(),
        outputs=(PortDefinition("output", type_id),),
        parameters=(),
        dependencies=(),
        implementation=lambda: None,
    )
    sink = NodeDefinition(
        name="vision.sink",
        inputs=(PortDefinition("image", type_id),),
        outputs=(),
        parameters=(),
        dependencies=(),
        implementation=lambda: None,
    )
    catalog = DefinitionCatalog(
        nodes={"vision.source": source, "vision.sink": sink},
        messages={type_id: message},
    )
    system = SystemModel(
        name="typed",
        graphs=(
            Graph(
                name="vision",
                nodes=(
                    NodeInstance(name="source", uses="vision.source"),
                    NodeInstance(name="sink", uses="vision.sink"),
                ),
                connections=(
                    Connection(**{"from": "source.output", "to": "sink.image"}),
                ),
            ),
        ),
        artifacts=(
            Artifact(name="frame", kind="message", producer="vision/source.output"),
        ),
    )

    plan = plan_system(system, catalog=catalog)

    assert plan.graph("vision").node("source").outputs == {"output": type_id}
    assert plan.graph("vision").node("sink").inputs == {"image": type_id}
    assert plan.graph("vision").connections[0].type_id == type_id
    assert plan.artifacts[0].target == "local"
    assert plan.artifacts[0].backend == "local"


def test_system_validation_errors_are_rejected_before_planning() -> None:
    system = SystemModel(
        name="bad-reference",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(name="worker", uses="demo.worker", target="missing"),
                ),
            ),
        ),
    )

    exc = _expect_planning_error("PLAN100", lambda: plan_system(system))
    assert "SYS011" in exc.message


def test_source_hash_is_deterministic_and_legacy_extensions_survive() -> None:
    first = SystemModel(
        name="stable",
        metadata={"b": 2, "a": 1},
        policies={"mode": "realtime"},
        extensions={"legacy_pipeline": {"runtime": {"engine": "unified"}}},
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                        extensions={"legacy": {"failure": {"policy": "restart_node"}}},
                    ),
                ),
            ),
        ),
    )
    second = first.model_copy(update={"metadata": {"a": 1, "b": 2}})

    first_plan = plan_system(first)
    second_plan = plan_system(second)

    assert first_plan.system_sha256 == second_plan.system_sha256
    assert first_plan.policies["mode"] == "realtime"
    assert first_plan.extensions["legacy_pipeline"]["runtime"]["engine"] == "unified"
    assert (
        first_plan.graph("main").node("worker").extensions["legacy"]["failure"]["policy"]
        == "restart_node"
    )
    assert first_plan.model_dump(by_alias=True)["schema"] == SYSTEM_EXECUTION_PLAN_SCHEMA


def test_pipeline_execution_plan_schema_remains_separate() -> None:
    from nodrix.execution_plan import EXECUTION_PLAN_SCHEMA

    assert EXECUTION_PLAN_SCHEMA == "nodrix.execution-plan/v1"
    assert SYSTEM_EXECUTION_PLAN_SCHEMA == "nodrix.system-execution-plan/v1"
    assert EXECUTION_PLAN_SCHEMA != SYSTEM_EXECUTION_PLAN_SCHEMA


def test_planner_is_exposed_through_plyctl_public_api() -> None:
    from plyctl import SystemExecutionPlan as PublicSystemExecutionPlan
    from plyctl import plan_system as public_plan_system

    assert PublicSystemExecutionPlan is SystemExecutionPlan
    assert public_plan_system is plan_system
