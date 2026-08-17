from __future__ import annotations

from collections.abc import Callable

import pytest

from nodrix.model import RevisionRef
from nodrix.system import (
    Graph,
    NodeInstance,
    SystemInstance,
    SystemModel,
    SystemPlanningError,
    plan_system,
)
from nodrix.system.definition import (
    system_definition_record,
)
from nodrix.system.planning import (
    PlannedSystemInstance,
)


def _revision(
    system: SystemModel,
) -> RevisionRef:
    return system_definition_record(
        system
    ).revision


def _instance(
    name: str,
    system: SystemModel,
) -> SystemInstance:
    return SystemInstance(
        name=name,
        uses=_revision(system).canonical,
    )


def _resolver(
    *systems: SystemModel,
) -> Callable[
    [RevisionRef],
    SystemModel | None,
]:
    definitions = {
        _revision(system).canonical: system
        for system in systems
    }

    def resolve(
        revision: RevisionRef,
    ) -> SystemModel | None:
        return definitions.get(
            revision.canonical
        )

    return resolve


def _leaf(
    name: str,
) -> SystemModel:
    return SystemModel(
        name=name,
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses=f"{name}.worker",
                    ),
                ),
            ),
        ),
    )


def test_hierarchical_planner_requires_definition_resolver() -> None:
    child = _leaf(
        "livox-mid360"
    )

    parent = SystemModel(
        name="robot",
        systems=(
            _instance(
                "lidar",
                child,
            ),
        ),
    )

    with pytest.raises(
        SystemPlanningError,
    ) as captured:
        plan_system(
            parent
        )

    assert captured.value.code == "PLAN404"
    assert (
        captured.value.path
        == "systems[0].uses"
    )


def test_hierarchical_plan_contains_exact_child_revision() -> None:
    child = _leaf(
        "livox-mid360"
    )

    parent = SystemModel(
        name="robot",
        systems=(
            _instance(
                "lidar",
                child,
            ),
        ),
    )

    plan = plan_system(
        parent,
        system_resolver=_resolver(
            child
        ),
    )

    planned = plan.child(
        "lidar"
    )

    assert isinstance(
        planned,
        PlannedSystemInstance,
    )

    assert (
        planned.revision
        == _revision(child).canonical
    )

    assert (
        planned.plan.system
        == "livox-mid360"
    )

    assert (
        planned.plan.system_sha256
        == _revision(child).digest
    )


def test_nested_child_plan_equals_standalone_plan() -> None:
    child = _leaf(
        "livox-mid360"
    )

    resolver = _resolver(
        child
    )

    standalone = plan_system(
        child,
        system_resolver=resolver,
    )

    parent = SystemModel(
        name="robot",
        systems=(
            _instance(
                "lidar",
                child,
            ),
        ),
    )

    nested = plan_system(
        parent,
        system_resolver=resolver,
    ).child(
        "lidar"
    ).plan

    assert nested == standalone


def test_hierarchical_plan_preserves_instance_order_and_alias() -> None:
    lidar = _leaf(
        "livox-mid360"
    )

    localization = _leaf(
        "fast-livo2"
    )

    mapping = _leaf(
        "voxel-mapping"
    )

    parent = SystemModel(
        name="robot",
        systems=(
            _instance(
                "lidar",
                lidar,
            ),
            _instance(
                "localization",
                localization,
            ),
            _instance(
                "mapping",
                mapping,
            ),
        ),
    )

    plan = plan_system(
        parent,
        system_resolver=_resolver(
            lidar,
            localization,
            mapping,
        ),
    )

    assert [
        item.name
        for item in plan.systems
    ] == [
        "lidar",
        "localization",
        "mapping",
    ]

    assert [
        item.ordinal
        for item in plan.systems
    ] == [
        0,
        1,
        2,
    ]

    assert plan.summary["systems"] == 3


def test_hierarchical_planning_is_recursive() -> None:
    sensor = _leaf(
        "livox-mid360"
    )

    perception = SystemModel(
        name="perception",
        systems=(
            _instance(
                "sensor",
                sensor,
            ),
        ),
    )

    robot = SystemModel(
        name="robot",
        systems=(
            _instance(
                "perception",
                perception,
            ),
        ),
    )

    plan = plan_system(
        robot,
        system_resolver=_resolver(
            sensor,
            perception,
        ),
    )

    nested = (
        plan
        .child("perception")
        .plan
        .child("sensor")
        .plan
    )

    assert nested.system == "livox-mid360"


def test_resolved_definition_must_match_pinned_revision() -> None:
    child = _leaf(
        "livox-mid360"
    )

    changed = child.model_copy(
        update={
            "metadata": {
                "changed": True,
            },
        }
    )

    parent = SystemModel(
        name="robot",
        systems=(
            _instance(
                "lidar",
                child,
            ),
        ),
    )

    def wrong_resolver(
        _: RevisionRef,
    ) -> SystemModel:
        return changed

    with pytest.raises(
        SystemPlanningError,
    ) as captured:
        plan_system(
            parent,
            system_resolver=wrong_resolver,
        )

    assert captured.value.code == "PLAN405"
    assert (
        captured.value.path
        == "systems[0].uses"
    )


def test_hierarchical_plan_serializes_recursive_structure() -> None:
    child = _leaf(
        "livox-mid360"
    )

    parent = SystemModel(
        name="robot",
        systems=(
            _instance(
                "lidar",
                child,
            ),
        ),
    )

    plan = plan_system(
        parent,
        system_resolver=_resolver(
            child
        ),
    )

    payload = plan.model_dump(
        by_alias=True,
        mode="json",
    )

    assert (
        payload["systems"][0]["name"]
        == "lidar"
    )

    assert (
        payload["systems"][0]["revision"]
        == _revision(child).canonical
    )

    assert (
        payload["systems"][0]["plan"]["system"]
        == "livox-mid360"
    )
