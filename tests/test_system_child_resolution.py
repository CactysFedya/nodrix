from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nodrix.model import RevisionRef
from nodrix.system import (
    SystemFormatError,
    load_system_details,
    loads_system,
)
from nodrix.system.definition import (
    system_definition_digest,
)


def _write(
    path: Path,
    document: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        yaml.safe_dump(
            document,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _system(
    name: str,
    **extra,
) -> dict:
    return {
        "apiVersion": "nodrix.system/v1",
        "kind": "System",
        "name": name,
        **extra,
    }


def test_child_system_path_resolves_to_pinned_revision(
    tmp_path: Path,
) -> None:
    child = tmp_path / "children" / "livox.yaml"

    _write(
        child,
        _system(
            "livox-mid360",
            metadata={
                "sensor": "MID-360",
            },
        ),
    )

    parent = tmp_path / "robot.yaml"

    _write(
        parent,
        _system(
            "robot",
            systems=[
                {
                    "name": "lidar",
                    "uses": "./children/livox.yaml",
                }
            ],
        ),
    )

    details = load_system_details(
        parent
    )

    instance = details.system.system(
        "lidar"
    )

    revision = RevisionRef.parse(
        instance.uses
    )

    assert revision.entity.kind == "system"
    assert revision.entity.name == "livox-mid360"

    assert details.canonical["systems"] == [
        {
            "name": "lidar",
            "uses": revision.canonical,
        }
    ]

    assert str(child) not in str(
        details.canonical
    )

    assert (
        details.resolution.child_system_sources
        == (child.resolve(),)
    )


def test_child_revision_uses_semantics_not_source_path(
    tmp_path: Path,
) -> None:
    first_child = tmp_path / "a" / "child.yaml"
    second_child = tmp_path / "b" / "renamed.yaml"

    document = _system(
        "shared-child",
        metadata={
            "mode": "same",
        },
    )

    _write(first_child, document)
    _write(second_child, document)

    first_parent = tmp_path / "a-parent.yaml"
    second_parent = tmp_path / "b-parent.yaml"

    _write(
        first_parent,
        _system(
            "parent",
            systems=[
                {
                    "name": "child",
                    "uses": "./a/child.yaml",
                }
            ],
        ),
    )

    _write(
        second_parent,
        _system(
            "parent",
            systems=[
                {
                    "name": "child",
                    "uses": "./b/renamed.yaml",
                }
            ],
        ),
    )

    first = load_system_details(
        first_parent
    )
    second = load_system_details(
        second_parent
    )

    assert (
        first.system.system("child").uses
        == second.system.system("child").uses
    )

    assert (
        system_definition_digest(first.system)
        == system_definition_digest(second.system)
    )


def test_child_semantic_change_changes_parent_identity(
    tmp_path: Path,
) -> None:
    child = tmp_path / "child.yaml"
    parent = tmp_path / "parent.yaml"

    _write(
        child,
        _system(
            "child",
            metadata={
                "version": 1,
            },
        ),
    )

    _write(
        parent,
        _system(
            "parent",
            systems=[
                {
                    "name": "child",
                    "uses": "./child.yaml",
                }
            ],
        ),
    )

    first = load_system_details(
        parent
    )

    _write(
        child,
        _system(
            "child",
            metadata={
                "version": 2,
            },
        ),
    )

    second = load_system_details(
        parent
    )

    assert (
        first.system.system("child").uses
        != second.system.system("child").uses
    )

    assert (
        system_definition_digest(first.system)
        != system_definition_digest(second.system)
    )


def test_pinned_child_reference_requires_no_child_file(
    tmp_path: Path,
) -> None:
    child = tmp_path / "child.yaml"

    _write(
        child,
        _system("child"),
    )

    temporary_parent = tmp_path / "temporary.yaml"

    _write(
        temporary_parent,
        _system(
            "parent",
            systems=[
                {
                    "name": "child",
                    "uses": "./child.yaml",
                }
            ],
        ),
    )

    resolved = load_system_details(
        temporary_parent
    )

    pinned = resolved.system.system(
        "child"
    ).uses

    parent = tmp_path / "pinned.yaml"

    _write(
        parent,
        _system(
            "parent",
            systems=[
                {
                    "name": "child",
                    "uses": pinned,
                }
            ],
        ),
    )

    child.unlink()

    loaded = load_system_details(
        parent
    )

    assert (
        loaded.system.system("child").uses
        == pinned
    )

    assert (
        loaded.resolution.child_system_sources
        == ()
    )


def test_loads_system_rejects_relative_child_without_source() -> None:
    text = yaml.safe_dump(
        _system(
            "parent",
            systems=[
                {
                    "name": "child",
                    "uses": "./child.yaml",
                }
            ],
        ),
        sort_keys=False,
    )

    with pytest.raises(
        SystemFormatError,
    ) as captured:
        loads_system(
            text,
            format="yaml",
        )

    assert captured.value.code == "SYSFMT009"
    assert (
        captured.value.location
        == "systems[0].uses"
    )


def test_missing_child_system_has_explicit_error(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent.yaml"

    _write(
        parent,
        _system(
            "parent",
            systems=[
                {
                    "name": "child",
                    "uses": "./missing.yaml",
                }
            ],
        ),
    )

    with pytest.raises(
        SystemFormatError,
        match="System file does not exist",
    ):
        load_system_details(
            parent
        )


def test_child_system_cycle_is_rejected(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"

    _write(
        first,
        _system(
            "first",
            systems=[
                {
                    "name": "second",
                    "uses": "./second.yaml",
                }
            ],
        ),
    )

    _write(
        second,
        _system(
            "second",
            systems=[
                {
                    "name": "first",
                    "uses": "./first.yaml",
                }
            ],
        ),
    )

    with pytest.raises(
        SystemFormatError,
    ) as captured:
        load_system_details(
            first
        )

    assert captured.value.code == "SYSFMT010"
    assert (
        "cyclic child System reference"
        in str(captured.value)
    )


def test_nested_child_systems_are_pinned_recursively(
    tmp_path: Path,
) -> None:
    sensor = tmp_path / "sensor.yaml"
    perception = tmp_path / "perception.yaml"
    robot = tmp_path / "robot.yaml"

    _write(
        sensor,
        _system("sensor"),
    )

    _write(
        perception,
        _system(
            "perception",
            systems=[
                {
                    "name": "sensor",
                    "uses": "./sensor.yaml",
                }
            ],
        ),
    )

    _write(
        robot,
        _system(
            "robot",
            systems=[
                {
                    "name": "perception",
                    "uses": "./perception.yaml",
                }
            ],
        ),
    )

    details = load_system_details(
        robot
    )

    parent_revision = RevisionRef.parse(
        details.system.system(
            "perception"
        ).uses
    )

    assert (
        parent_revision.entity.name
        == "perception"
    )

    assert set(
        details.resolution.child_system_sources
    ) == {
        perception.resolve(),
        sensor.resolve(),
    }


def test_project_child_system_alias_resolves_to_same_revision_as_path(
    tmp_path: Path,
) -> None:
    from nodrix.project_foundation import (
        add_project_resource,
        create_progressive_project,
    )
    from nodrix.project_system import (
        load_project_system_details,
    )

    create_progressive_project(
        tmp_path
    )

    child_resource = add_project_resource(
        "system",
        "livox-mid360",
        root=tmp_path,
    )

    parent_resource = add_project_resource(
        "system",
        "robot",
        root=tmp_path,
    )

    _write(
        child_resource.path,
        _system(
            "livox-mid360",
            metadata={
                "sensor": "MID-360",
            },
        ),
    )

    _write(
        parent_resource.path,
        _system(
            "robot",
            systems=[
                {
                    "name": "lidar",
                    "uses": "livox-mid360",
                }
            ],
        ),
    )

    aliased = load_project_system_details(
        parent_resource.path,
        root=tmp_path,
    )

    alias_revision = (
        aliased.system
        .system("lidar")
        .uses
    )

    _write(
        parent_resource.path,
        _system(
            "robot",
            systems=[
                {
                    "name": "lidar",
                    "uses": "./livox-mid360.yaml",
                }
            ],
        ),
    )

    by_path = load_project_system_details(
        parent_resource.path,
        root=tmp_path,
    )

    assert (
        alias_revision
        == by_path.system.system("lidar").uses
    )

    assert (
        system_definition_digest(
            aliased.system
        )
        == system_definition_digest(
            by_path.system
        )
    )

    assert (
        aliased.resolution.child_system_sources
        == (
            child_resource.path.resolve(),
        )
    )


def test_unknown_project_child_alias_is_explicit(
    tmp_path: Path,
) -> None:
    from nodrix.project_foundation import (
        add_project_resource,
        create_progressive_project,
    )
    from nodrix.project_system import (
        load_project_system_details,
    )

    create_progressive_project(
        tmp_path
    )

    parent_resource = add_project_resource(
        "system",
        "robot",
        root=tmp_path,
    )

    _write(
        parent_resource.path,
        _system(
            "robot",
            systems=[
                {
                    "name": "lidar",
                    "uses": "missing-lidar",
                }
            ],
        ),
    )

    with pytest.raises(
        SystemFormatError,
    ) as captured:
        load_project_system_details(
            parent_resource.path,
            root=tmp_path,
        )

    assert captured.value.code == "SYSFMT011"
    assert (
        captured.value.location
        == "systems[0].uses"
    )
    assert "missing-lidar" in str(
        captured.value
    )
