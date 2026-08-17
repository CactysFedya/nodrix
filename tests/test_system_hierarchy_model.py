from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

import nodrix
from nodrix.model import (
    EntityRef,
    RevisionRef,
)
from nodrix.system import (
    SystemInstance,
    SystemModel,
    SystemPlanningError,
    dumps_system,
    loads_system,
    plan_system,
    system_json_schema,
    system_to_canonical,
    validate_system,
)
from nodrix.system.definition import (
    system_definition_digest,
)


def _revision(
    *,
    name: str = "livox-mid360",
    digest: str = "a" * 64,
) -> RevisionRef:
    return RevisionRef.from_sha256(
        EntityRef(
            kind="system",
            namespace="project",
            name=name,
        ),
        digest,
    )


def _instance(
    *,
    name: str = "lidar",
    revision: RevisionRef | None = None,
) -> SystemInstance:
    selected = (
        _revision()
        if revision is None
        else revision
    )

    return SystemInstance(
        name=name,
        uses=selected.canonical,
    )


def test_system_instance_pins_exact_system_revision() -> None:
    revision = _revision()

    instance = SystemInstance(
        name="lidar",
        uses=f"  {revision.canonical}  ",
    )

    assert instance.name == "lidar"
    assert instance.uses == revision.canonical
    assert instance.revision == revision
    assert instance.entity == revision.entity
    assert instance.entity.kind == "system"


@pytest.mark.parametrize(
    "uses",
    (
        "./systems/livox-mid360.yaml",
        "livox-mid360",
        "nodrix://system/project/livox-mid360",
    ),
)
def test_system_instance_rejects_unpinned_authoring_references(
    uses: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match="canonical immutable System RevisionRef",
    ):
        SystemInstance(
            name="lidar",
            uses=uses,
        )


def test_system_instance_rejects_non_system_revision() -> None:
    component = EntityRef(
        kind="component",
        namespace="project",
        name="livox-driver",
    )

    revision = RevisionRef.from_sha256(
        component,
        "b" * 64,
    )

    with pytest.raises(
        ValidationError,
        match="kind 'system'",
    ):
        SystemInstance(
            name="lidar",
            uses=revision.canonical,
        )


def test_system_model_contains_canonical_child_instances() -> None:
    instance = _instance()

    system = SystemModel(
        name="robot",
        systems=(
            instance,
        ),
    )

    assert system.system("lidar") == instance

    with pytest.raises(KeyError):
        system.system("missing")


def test_system_hierarchy_yaml_round_trip_is_canonical() -> None:
    revision = _revision()

    system = SystemModel(
        name="robot",
        systems=(
            _instance(
                revision=revision,
            ),
        ),
    )

    serialized = dumps_system(
        system,
        format="yaml",
    )

    assert "systems:" in serialized
    assert revision.canonical in serialized

    restored = loads_system(
        serialized,
        format="yaml",
    )

    assert restored == system
    assert (
        restored.system("lidar").revision
        == revision
    )

    canonical = system_to_canonical(
        restored
    )

    assert canonical["systems"] == [
        {
            "name": "lidar",
            "uses": revision.canonical,
        }
    ]


def test_duplicate_system_instance_names_are_invalid() -> None:
    system = SystemModel(
        name="robot",
        systems=(
            _instance(
                name="lidar",
                revision=_revision(
                    digest="a" * 64,
                ),
            ),
            _instance(
                name="lidar",
                revision=_revision(
                    digest="b" * 64,
                ),
            ),
        ),
    )

    report = validate_system(
        system
    )

    diagnostic = next(
        item
        for item in report.errors
        if item.code == "SYS001"
        and item.path == "systems.lidar"
    )

    assert (
        diagnostic.message
        == "duplicate system name"
    )


def test_child_revision_is_part_of_parent_system_identity() -> None:
    first_revision = _revision(
        digest="a" * 64,
    )
    second_revision = _revision(
        digest="b" * 64,
    )

    first = SystemModel(
        name="robot",
        systems=(
            _instance(
                revision=first_revision,
            ),
        ),
    )

    same = SystemModel(
        name="robot",
        systems=(
            _instance(
                revision=first_revision,
            ),
        ),
    )

    changed = SystemModel(
        name="robot",
        systems=(
            _instance(
                revision=second_revision,
            ),
        ),
    )

    assert (
        system_definition_digest(first)
        == system_definition_digest(same)
    )

    assert (
        system_definition_digest(first)
        != system_definition_digest(changed)
    )


def test_empty_systems_preserve_existing_canonical_shape() -> None:
    system = SystemModel(
        name="legacy-flat-system"
    )

    canonical = system_to_canonical(
        system
    )

    assert "systems" not in canonical

    # The new default-empty field therefore contributes no bytes to the
    # pre-existing canonical representation/digest.
    assert json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_system_schema_exposes_system_instances() -> None:
    schema = system_json_schema()

    assert "systems" in schema["properties"]
    assert "SystemInstance" in schema["$defs"]

    system_instance = schema[
        "$defs"
    ]["SystemInstance"]

    assert "name" in system_instance["properties"]
    assert "uses" in system_instance["properties"]


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


def test_planner_requires_exact_child_system_definition() -> None:
    system = SystemModel(
        name="robot",
        systems=(
            _instance(),
        ),
    )

    with pytest.raises(
        SystemPlanningError,
    ) as captured:
        plan_system(
            system
        )

    assert captured.value.code == "PLAN404"
    assert (
        captured.value.path
        == "systems[0].uses"
    )
    assert (
        "SystemDefinitionResolver"
        in captured.value.message
    )


def test_system_instance_is_exported_from_public_api() -> None:
    assert nodrix.SystemInstance is SystemInstance
