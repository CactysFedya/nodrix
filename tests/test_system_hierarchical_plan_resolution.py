from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner
import yaml

from nodrix.cli import app
from nodrix.model import RevisionRef
from nodrix.system import (
    load_system_details,
)
from nodrix.system.definition import (
    system_definition_digest,
)


runner = CliRunner()


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


def test_load_details_retains_exact_child_definition(
    tmp_path: Path,
) -> None:
    child = tmp_path / "livox.yaml"

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
                    "uses": "./livox.yaml",
                }
            ],
        ),
    )

    details = load_system_details(
        parent
    )

    revision = RevisionRef.parse(
        details.system.system(
            "lidar"
        ).uses
    )

    resolved = (
        details.resolution
        .child_system_definitions[
            revision.canonical
        ]
    )

    assert resolved.name == "livox-mid360"

    assert (
        system_definition_digest(
            resolved
        )
        == revision.digest
    )


def test_nested_child_definitions_are_retained_recursively(
    tmp_path: Path,
) -> None:
    sensor = tmp_path / "sensor.yaml"

    _write(
        sensor,
        _system(
            "sensor",
        ),
    )

    perception = tmp_path / "perception.yaml"

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

    robot = tmp_path / "robot.yaml"

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

    definitions = (
        details.resolution
        .child_system_definitions
    )

    assert {
        system.name
        for system in definitions.values()
    } == {
        "perception",
        "sensor",
    }


def test_pinned_child_without_source_has_no_fake_definition(
    tmp_path: Path,
) -> None:
    child = tmp_path / "child.yaml"

    _write(
        child,
        _system(
            "child",
        ),
    )

    temporary = tmp_path / "temporary.yaml"

    _write(
        temporary,
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
        temporary
    )

    pinned = (
        first.system
        .system("child")
        .uses
    )

    canonical = tmp_path / "canonical.yaml"

    _write(
        canonical,
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
        canonical
    )

    assert (
        loaded.resolution
        .child_system_definitions
        == {}
    )


def test_cli_plan_resolves_relative_child_automatically(
    tmp_path: Path,
) -> None:
    child = tmp_path / "livox.yaml"

    _write(
        child,
        _system(
            "livox-mid360",
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
                    "uses": "./livox.yaml",
                }
            ],
        ),
    )

    result = runner.invoke(
        app,
        [
            "system",
            "plan",
            str(parent),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output

    payload = json.loads(
        result.stdout
    )

    assert payload["system"] == "robot"

    assert (
        payload["systems"][0]["name"]
        == "lidar"
    )

    assert (
        payload["systems"][0]["plan"]["system"]
        == "livox-mid360"
    )


def test_cli_plan_resolves_project_child_alias_automatically(
    tmp_path: Path,
) -> None:
    from nodrix.project_foundation import (
        add_project_resource,
        create_progressive_project,
    )

    create_progressive_project(
        tmp_path
    )

    child = add_project_resource(
        "system",
        "livox-mid360",
        root=tmp_path,
    )

    parent = add_project_resource(
        "system",
        "robot",
        root=tmp_path,
        make_default=True,
    )

    _write(
        child.path,
        _system(
            "livox-mid360",
        ),
    )

    _write(
        parent.path,
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

    result = runner.invoke(
        app,
        [
            "system",
            "plan",
            str(parent.path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output

    payload = json.loads(
        result.stdout
    )

    assert payload["system"] == "robot"

    child_plan = (
        payload["systems"][0]
        ["plan"]
    )

    assert (
        child_plan["system"]
        == "livox-mid360"
    )
