from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.model import RevisionRef
from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
)


runner = CliRunner()


def _write(
    path: Path,
    document: dict,
) -> None:
    path.write_text(
        yaml.safe_dump(
            document,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_system_show_resolves_project_child_alias_and_reports_source(
    tmp_path: Path,
) -> None:
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
    )

    _write(
        child.path,
        {
            "apiVersion": "nodrix.system/v1",
            "kind": "System",
            "name": "livox-mid360",
        },
    )

    _write(
        parent.path,
        {
            "apiVersion": "nodrix.system/v1",
            "kind": "System",
            "name": "robot",
            "systems": [
                {
                    "name": "lidar",
                    "uses": "livox-mid360",
                }
            ],
        },
    )

    result = runner.invoke(
        app,
        [
            "system",
            "show",
            str(parent.path),
            "--json",
            "--resolution",
        ],
    )

    assert result.exit_code == 0, result.output

    payload = json.loads(
        result.stdout
    )

    child_instance = payload[
        "system"
    ]["systems"][0]

    revision = RevisionRef.parse(
        child_instance["uses"]
    )

    assert revision.entity.kind == "system"
    assert (
        revision.entity.name
        == "livox-mid360"
    )

    assert payload[
        "resolution"
    ]["childSystemSources"] == [
        str(child.path.resolve())
    ]

    rendered = runner.invoke(
        app,
        [
            "system",
            "show",
            str(parent.path),
            "--resolution",
        ],
    )

    assert rendered.exit_code == 0, rendered.output
    assert "CHILD SYSTEM" in rendered.output
    assert "livox-mid360.yaml" in rendered.output


def test_system_validate_resolves_project_child_alias(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    child = add_project_resource(
        "system",
        "child",
        root=tmp_path,
    )

    parent = add_project_resource(
        "system",
        "parent",
        root=tmp_path,
    )

    _write(
        child.path,
        {
            "apiVersion": "nodrix.system/v1",
            "kind": "System",
            "name": "child",
        },
    )

    _write(
        parent.path,
        {
            "apiVersion": "nodrix.system/v1",
            "kind": "System",
            "name": "parent",
            "systems": [
                {
                    "name": "child",
                    "uses": "child",
                }
            ],
        },
    )

    result = runner.invoke(
        app,
        [
            "system",
            "validate",
            str(parent.path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "VALID" in result.output
