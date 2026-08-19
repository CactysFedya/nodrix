from __future__ import annotations

from nodrix.system import (
    ApplicationInstance,
    BackendContext,
    BackendSystemLink,
    Graph,
    NodeInstance,
    PlannedLink,
    SystemBoundaryBindings,
    SystemInstance,
    SystemLink,
    SystemModel,
    SystemPort,
    SystemPortBinding,
    lower_local_context,
    plan_system,
    validate_system,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.definition import (
    system_definition_record,
)


TYPE_ID = "demo.data/v1"


def _revision(
    system: SystemModel,
) -> str:
    return (
        system_definition_record(
            system
        )
        .revision
        .canonical
    )


def _resolver(
    *systems: SystemModel,
):
    definitions = {
        system_definition_record(
            system
        ).revision: system
        for system in systems
    }

    return definitions.get


def _sink_system(
    name: str = "sink",
) -> SystemModel:
    return SystemModel(
        name=name,
        inputs=(
            SystemPort(
                name="input",
                type_id=TYPE_ID,
            ),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="sink",
                        uses="demo.sink",
                    ),
                ),
            ),
        ),
        bindings=SystemBoundaryBindings(
            inputs=(
                SystemPortBinding(
                    port="input",
                    endpoint="main/sink.input",
                ),
            ),
        ),
    )


def test_child_required_input_must_be_satisfied() -> None:
    child = _sink_system(
        "mapper"
    )

    parent = SystemModel(
        name="robot",
        systems=(
            SystemInstance(
                name="mapper",
                uses=_revision(child),
            ),
        ),
    )

    report = validate_system(
        parent,
        system_resolver=_resolver(
            child
        ),
    )

    assert not report.valid
    assert any(
        item.code == "SYS177"
        for item in report.errors
    )


def test_child_required_input_can_be_delegated_by_parent_input() -> None:
    child = _sink_system(
        "mapper"
    )

    parent = SystemModel(
        name="mapping-stack",
        inputs=(
            SystemPort(
                name="cloud",
                type_id=TYPE_ID,
            ),
        ),
        systems=(
            SystemInstance(
                name="mapper",
                uses=_revision(child),
            ),
        ),
        bindings=SystemBoundaryBindings(
            inputs=(
                SystemPortBinding(
                    port="cloud",
                    endpoint="system:mapper.input",
                ),
            ),
        ),
    )

    report = validate_system(
        parent,
        system_resolver=_resolver(
            child
        ),
    )

    assert report.valid, report.errors


def test_application_to_child_system_is_system_boundary() -> None:
    child = _sink_system(
        "mapper"
    )

    parent = SystemModel(
        name="robot",
        applications=(
            ApplicationInstance(
                name="driver",
                uses="demo.driver",
            ),
        ),
        systems=(
            SystemInstance(
                name="mapper",
                uses=_revision(child),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "driver.cloud",
                    "to": "system:mapper.input",
                    "type_id": TYPE_ID,
                    "uses": "demo.transport",
                }
            ),
        ),
    )

    plan = plan_system(
        parent,
        system_resolver=_resolver(
            child
        ),
    )

    assert len(plan.links) == 1
    assert (
        plan.links[0].boundary
        == "system"
    )


def test_canonical_planner_supports_nested_system_resolution() -> None:
    child = SystemModel(
        name="child"
    )

    parent = SystemModel(
        name="parent",
        systems=(
            SystemInstance(
                name="child",
                uses=_revision(child),
            ),
        ),
    )

    record = plan_canonical_system(
        parent,
        system_resolver=_resolver(
            child
        ),
    )

    assert (
        record.payload
        .child("child")
        .plan
        .system
        == "child"
    )


def test_local_lowering_does_not_merge_equal_ordinals_from_different_systems() -> None:
    local_system = SystemModel(
        name="middle",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="source",
                        uses="demo.source",
                    ),
                    NodeInstance(
                        name="recv",
                        uses="demo.recv",
                    ),
                ),
            ),
        ),
    )

    plan = plan_system(
        local_system
    )

    link = PlannedLink(
        ordinal=0,
        **{
            "from": "main/source.output",
            "to": "main/recv.input",
        },
        type_id=TYPE_ID,
        source_target="local",
        target_target="local",
        source_backend="local",
        target_backend="local",
        boundary="system",
        transport_required=True,
        transport_uses="demo.transport",
    )

    # Link owned by the child System itself.
    outbound = BackendSystemLink(
        link=link,
        direction="outbound",
        local_endpoint="main/source.output",
        remote_endpoint="main/sink.input",
        owner_system_path=("middle",),
        local_system_path=("middle",),
        remote_system_path=(
            "middle",
            "grandchild",
        ),
    )

    # Different link owned by the parent System.
    # It intentionally has the same plan-local ordinal=0.
    inbound = BackendSystemLink(
        link=link,
        direction="inbound",
        local_endpoint="main/recv.input",
        remote_endpoint="main/upstream.output",
        owner_system_path=(),
        local_system_path=("middle",),
        remote_system_path=(),
    )

    context = BackendContext.from_plan(
        plan,
        "local",
        system_inbound_links=(
            inbound,
        ),
        system_outbound_links=(
            outbound,
        ),
    )

    lowering = lower_local_context(
        context
    )

    # Before the fix the two independent links were grouped by ordinal=0
    # and silently collapsed into:
    #
    #   source.output -> recv.input
    #
    # They must remain two separate transport links.
    assert (
        len(lowering.manifest.links)
        == 2
    )

    assert not any(
        link.source == "source.output"
        and link.target == "recv.input"
        for link in lowering.manifest.links
    )
