from __future__ import annotations

from pathlib import Path

import yaml

from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
)
from nodrix.workflow_execution import (
    load_workflow,
)


def test_created_workflow_is_self_describing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"

    create_progressive_project(
        root
    )

    resource = add_project_resource(
        "workflow",
        "hello",
        root=root,
    )

    text = resource.path.read_text(
        encoding="utf-8"
    )

    assert "# Nodrix Workflow" in text

    assert (
        "#   A Workflow is a finite "
        "engineering operation"
        in text
    )

    assert (
        "plyctl workflow run hello"
        in text
    )

    assert (
        "from nodrix.sdk import Workflow"
        in text
    )

    assert (
        "workflow = Workflow('hello')"
        in text
    )

    assert (
        "workflow.run("
        in text
    )

    assert (
        "# Optional workflow binding:"
        in text
    )

    assert (
        "# implements: robot.flash"
        in text
    )

    assert (
        "# Optional step fields:"
        in text
    )

    assert (
        "#   timeout_seconds: 60"
        in text
    )

    assert (
        "#   cache:"
        in text
    )


def test_workflow_scaffold_remains_clean_canonical_yaml(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"

    create_progressive_project(
        root
    )

    resource = add_project_resource(
        "workflow",
        "hello",
        root=root,
    )

    document = yaml.safe_load(
        resource.path.read_text(
            encoding="utf-8"
        )
    )

    assert document == {
        "schema": "nodrix.workflow/v1",
        "name": "hello",
        "steps": [
            {
                "id": "hello",
                "run": (
                    "echo "
                    '"Hello from Nodrix '
                    'workflow hello"'
                ),
            }
        ],
    }


def test_created_workflow_is_immediately_loadable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"

    create_progressive_project(
        root
    )

    resource = add_project_resource(
        "workflow",
        "hello",
        root=root,
    )

    document, path, project_root = (
        load_workflow(
            "hello",
            root=root,
        )
    )

    assert path == resource.path
    assert project_root == root.resolve()

    assert (
        document["schema"]
        == "nodrix.workflow/v1"
    )

    assert (
        document["name"]
        == "hello"
    )

    assert (
        document["steps"][0]["id"]
        == "hello"
    )


def test_non_workflow_resource_keeps_plain_yaml(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"

    create_progressive_project(
        root
    )

    resource = add_project_resource(
        "profile",
        "development",
        root=root,
    )

    text = resource.path.read_text(
        encoding="utf-8"
    )

    assert not text.startswith(
        "# Nodrix Workflow"
    )

    assert yaml.safe_load(text) == {
        "schema": "nodrix.profile/v1",
        "name": "development",
        "variables": {},
    }


def test_created_system_is_self_describing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"

    create_progressive_project(
        root
    )

    resource = add_project_resource(
        "system",
        "robot",
        root=root,
    )

    text = resource.path.read_text(
        encoding="utf-8"
    )

    assert "# Nodrix System" in text

    assert (
        "canonical definition of the whole "
        "executable system"
        in text
    )

    assert (
        "plyctl system validate "
        "systems/robot.yaml"
        in text
    )

    assert (
        "plyctl system plan "
        "systems/robot.yaml"
        in text
    )

    assert (
        "plyctl system run "
        "systems/robot.yaml"
        in text
    )

    assert (
        "plyctl system show "
        "systems/robot.yaml"
        in text
    )


def test_system_scaffold_preserves_canonical_document(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"

    create_progressive_project(
        root
    )

    resource = add_project_resource(
        "system",
        "main",
        root=root,
    )

    document = yaml.safe_load(
        resource.path.read_text(
            encoding="utf-8"
        )
    )

    assert document == {
        "apiVersion": "nodrix.system/v1",
        "kind": "System",
        "name": "main",
    }


def test_created_environment_is_self_describing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"

    create_progressive_project(
        root
    )

    resource = add_project_resource(
        "environment",
        "development",
        root=root,
    )

    text = resource.path.read_text(
        encoding="utf-8"
    )

    assert "# Nodrix Environment" in text

    assert (
        "shell setup files, environment "
        "variables and checks"
        in text
    )

    assert "plyctl env show" in text
    assert "plyctl env check" in text
    assert "plyctl env export" in text

    assert (
        "plyctl project add environment "
        "development --default"
        in text
    )


def test_environment_scaffold_preserves_canonical_document(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"

    create_progressive_project(
        root
    )

    resource = add_project_resource(
        "environment",
        "development",
        root=root,
    )

    document = yaml.safe_load(
        resource.path.read_text(
            encoding="utf-8"
        )
    )

    assert document == {
        "schema": "nodrix.environment/v1",
        "name": "development",
        "shell": {
            "source": [],
        },
        "environment": {},
        "checks": [],
    }
