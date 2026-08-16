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
