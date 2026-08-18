from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

import nodrix
from nodrix.model import EntityRef, RevisionRef
from nodrix.system import (
    PlannedSystemDependency,
    SystemDependency,
    SystemDependencyCondition,
    SystemInstance,
    SystemModel,
    SystemPlanningError,
    dumps_system,
    loads_system,
    system_json_schema,
    system_to_canonical,
    plan_system,
    validate_system,
)
from nodrix.system.definition import system_definition_record


def _instance(name: str, digest: str) -> SystemInstance:
    revision = RevisionRef.from_sha256(
        EntityRef(
            kind="system",
            namespace="project",
            name=name,
        ),
        digest,
    )
    return SystemInstance(
        name=name,
        uses=revision.canonical,
    )


def _dependency(**overrides) -> SystemDependency:
    values = {
        "system": "localization",
        "requires": "sensor",
        "condition": "ready",
        "timeoutSeconds": 30,
    }
    values.update(overrides)
    return SystemDependency.model_validate(values)


def _system(*dependencies: SystemDependency) -> SystemModel:
    return SystemModel(
        name="mapping",
        systems=(
            _instance("sensor", "a" * 64),
            _instance("localization", "b" * 64),
        ),
        dependencies=dependencies,
    )


def _planning_system(
    *dependencies: SystemDependency,
    order: tuple[str, ...] = (
        "sensor",
        "monitoring",
        "localization",
        "mapping",
    ),
):
    definitions = {
        name: SystemModel(name=name)
        for name in order
    }
    instances = tuple(
        SystemInstance(
            name=name,
            uses=system_definition_record(
                definitions[name]
            ).revision.canonical,
        )
        for name in order
    )
    by_revision = {
        system_definition_record(definition).revision.canonical: definition
        for definition in definitions.values()
    }

    return (
        SystemModel(
            name="robot",
            systems=instances,
            dependencies=dependencies,
        ),
        lambda revision: by_revision.get(
            revision.canonical
        ),
    )


def test_system_dependency_is_strict_and_backend_neutral() -> None:
    dependency = _dependency()

    assert dependency.system == "localization"
    assert dependency.requires == "sensor"
    assert dependency.condition is SystemDependencyCondition.READY
    assert dependency.timeout_seconds == 30

    with pytest.raises(ValidationError):
        _dependency(backend="local")


@pytest.mark.parametrize("timeout", (0, -1, float("inf"), float("nan")))
def test_system_dependency_requires_finite_positive_timeout(timeout: float) -> None:
    with pytest.raises(ValidationError):
        _dependency(timeoutSeconds=timeout)


@pytest.mark.parametrize("condition", ("started", "ready", "healthy"))
def test_system_dependency_accepts_supported_conditions(condition: str) -> None:
    dependency = _dependency(condition=condition)

    assert dependency.condition.value == condition


def test_system_dependencies_round_trip_canonically() -> None:
    system = _system(_dependency())

    serialized = dumps_system(system, format="yaml")
    restored = loads_system(serialized, format="yaml")

    assert restored == system
    assert "dependencies:" in serialized
    assert "timeoutSeconds: 30.0" in serialized
    assert system_to_canonical(system)["dependencies"] == [
        {
            "system": "localization",
            "requires": "sensor",
            "condition": "ready",
            "timeoutSeconds": 30.0,
        }
    ]


@pytest.mark.parametrize(
    ("dependency", "code", "path"),
    (
        (_dependency(system="missing"), "SYS061", "dependencies[0].system"),
        (_dependency(requires="missing"), "SYS062", "dependencies[0].requires"),
        (
            _dependency(system="sensor", requires="sensor"),
            "SYS063",
            "dependencies[0]",
        ),
    ),
)
def test_system_dependency_references_only_distinct_siblings(
    dependency: SystemDependency,
    code: str,
    path: str,
) -> None:
    report = validate_system(_system(dependency))

    assert any(
        item.code == code and item.path == path
        for item in report.errors
    )


def test_duplicate_system_dependency_edge_is_invalid() -> None:
    report = validate_system(
        _system(
            _dependency(),
            _dependency(condition="healthy", timeoutSeconds=60),
        )
    )

    assert any(
        item.code == "SYS064" and item.path == "dependencies[1]"
        for item in report.errors
    )


def test_empty_dependencies_preserve_existing_canonical_shape() -> None:
    assert "dependencies" not in system_to_canonical(SystemModel(name="minimal"))


def test_planner_compiles_deterministic_system_startup_topology() -> None:
    system, resolver = _planning_system(
        _dependency(),
        _dependency(
            system="mapping",
            requires="localization",
            condition="healthy",
            timeoutSeconds=60,
        ),
    )

    plan = plan_system(
        system,
        system_resolver=resolver,
    )
    startup = plan.system_startup

    assert startup is not None
    assert startup.roots == (
        "sensor",
        "monitoring",
    )
    assert startup.order == (
        "sensor",
        "monitoring",
        "localization",
        "mapping",
    )
    assert startup.dependencies == (
        PlannedSystemDependency(
            ordinal=0,
            system="localization",
            requires="sensor",
            condition="ready",
            timeout_seconds=30,
        ),
        PlannedSystemDependency(
            ordinal=1,
            system="mapping",
            requires="localization",
            condition="healthy",
            timeout_seconds=60,
        ),
    )
    assert plan.summary["dependencies"] == 2


def test_planner_rejects_system_dependency_cycle() -> None:
    system, resolver = _planning_system(
        _dependency(
            system="localization",
            requires="mapping",
        ),
        _dependency(
            system="mapping",
            requires="localization",
        ),
    )

    with pytest.raises(SystemPlanningError) as captured:
        plan_system(
            system,
            system_resolver=resolver,
        )

    assert captured.value.code == "PLAN406"
    assert captured.value.path == "dependencies"


def test_plan_omits_startup_topology_when_no_dependencies_exist() -> None:
    system, resolver = _planning_system()

    plan = plan_system(
        system,
        system_resolver=resolver,
    )

    assert plan.system_startup is None
    assert "dependencies" not in plan.summary


def test_system_schema_exposes_dependencies_and_matches_snapshot() -> None:
    schema = system_json_schema()

    assert "dependencies" in schema["properties"]
    assert "SystemDependency" in schema["$defs"]
    assert "SystemDependencyCondition" in schema["$defs"]

    root = Path(__file__).resolve().parents[1]
    checked = json.loads(
        (root / "src/nodrix/schemas/system-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert checked == schema


def test_system_dependency_is_exported_from_public_api() -> None:
    from plyctl import SystemDependency as PublicSystemDependency

    assert nodrix.SystemDependency is SystemDependency
    assert PublicSystemDependency is SystemDependency
