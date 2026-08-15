from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from nodrix.build_recipes import (
    available_build_recipes,
    compile_project_build_workflow,
)
from nodrix.cli import app
from nodrix.project_foundation import add_project_resource, create_progressive_project
from nodrix.workflow_execution import list_workflows, load_workflow


runner = CliRunner()


def _set_build(tmp_path: Path, value: dict) -> None:
    path = tmp_path / "nodrix.yaml"
    project = yaml.safe_load(path.read_text(encoding="utf-8"))
    project["build"] = value
    path.write_text(yaml.safe_dump(project, sort_keys=False), encoding="utf-8")


def test_build_recipes_compile_to_dependency_ordered_workflow(tmp_path: Path) -> None:
    create_progressive_project(tmp_path)
    (tmp_path / "sources" / "Livox-SDK2").mkdir(parents=True)
    (tmp_path / "sources" / "Livox-SDK2" / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\n",
        encoding="utf-8",
    )
    (tmp_path / "workspaces" / "livox_ws" / "src").mkdir(parents=True)
    _set_build(
        tmp_path,
        {
            "livox-sdk2": {
                "uses": "cmake.release",
                "source": "sources/Livox-SDK2",
                "install": True,
            },
            "livox-driver": {
                "uses": "ros2.colcon",
                "workspace": "workspaces/livox_ws",
                "depends_on": ["livox-sdk2"],
                "packages": ["livox_ros_driver2"],
            },
        },
    )

    compiled = compile_project_build_workflow(tmp_path)
    assert compiled is not None
    workflow, path = compiled
    assert path == tmp_path / ".nodrix" / "generated" / "build.workflow.yaml"
    assert [step["id"] for step in workflow["steps"]] == [
        "livox-sdk2",
        "livox-driver",
    ]
    assert workflow["steps"][0]["recipe"] == "cmake.release"
    assert "cmake --build" in workflow["steps"][0]["run"]
    assert workflow["steps"][0]["cache"]["inputs"] == ["sources/Livox-SDK2"]
    assert workflow["steps"][1]["recipe"] == "ros2.colcon"
    assert "colcon build" in workflow["steps"][1]["run"]
    assert "CMAKE_PREFIX_PATH" in workflow["steps"][1]["run"]
    assert workflow["steps"][1]["depends_on"] == ["livox-sdk2"]


def test_load_workflow_build_prefers_project_recipes(tmp_path: Path) -> None:
    create_progressive_project(tmp_path)
    (tmp_path / "native").mkdir()
    _set_build(
        tmp_path,
        {"core": {"uses": "cmake.release", "source": "native"}},
    )

    workflow, path, root = load_workflow("build", root=tmp_path)
    assert root == tmp_path
    assert path == tmp_path / ".nodrix" / "generated" / "build.workflow.yaml"
    assert workflow["generated"]["schema"] == "nodrix.build-recipes/v1"
    assert list_workflows(tmp_path)["build"] == "nodrix.yaml#build"


def test_build_recipe_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    create_progressive_project(tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _set_build(
        tmp_path,
        {
            "a": {"uses": "cmake.release", "source": "a", "depends_on": "b"},
            "b": {"uses": "cmake.release", "source": "b", "depends_on": "a"},
        },
    )

    with pytest.raises(ValueError, match="dependency cycle"):
        compile_project_build_workflow(tmp_path)


def test_legacy_build_workflow_remains_fallback(tmp_path: Path) -> None:
    create_progressive_project(tmp_path)
    resource = add_project_resource("workflow", "build", root=tmp_path)
    workflow, path, _ = load_workflow("build", root=tmp_path)
    assert path == resource.path
    assert workflow["schema"] == "nodrix.workflow/v1"
    assert "generated" not in workflow


def test_build_cli_dry_run_uses_high_level_recipes(tmp_path: Path, monkeypatch) -> None:
    create_progressive_project(tmp_path)
    (tmp_path / "native").mkdir()
    (tmp_path / "native" / "CMakeLists.txt").write_text("project(demo)\n", encoding="utf-8")
    _set_build(
        tmp_path,
        {"native": {"uses": "cmake.release", "source": "native"}},
    )

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["build", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "PLANNED" in result.output
    assert "native" in result.output


def test_project_recipes_command_lists_builtin_sdk(tmp_path: Path, monkeypatch) -> None:
    create_progressive_project(tmp_path)
    names = {item.name for item in available_build_recipes()}
    assert {"cmake.release", "cmake.debug", "ros2.colcon", "python.editable"} <= names

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["project", "recipes"])
    assert result.exit_code == 0, result.output
    assert "cmake.release" in result.output
    assert "ros2.colcon" in result.output
