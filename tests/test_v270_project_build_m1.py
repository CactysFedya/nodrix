from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.local_dev import compile_local_project, reset_local_development_modules
from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
    resolve_project_resource,
)
from nodrix.system import Graph, NodeInstance, SystemModel, dump_system, load_system
from nodrix.workflow_execution import run_workflow


runner = CliRunner()


def test_project_registers_default_system(tmp_path: Path) -> None:
    create_progressive_project(tmp_path)
    resource = add_project_resource("system", "robot", root=tmp_path, make_default=True)

    project = yaml.safe_load((tmp_path / "nodrix.yaml").read_text(encoding="utf-8"))
    assert project["systems"] == {"robot": "systems/robot.yaml"}
    assert project["defaults"]["system"] == "robot"
    assert load_system(resource.path).name == "robot"
    assert resolve_project_resource("system", root=tmp_path).path == resource.path


def test_progressive_project_manifest_does_not_shadow_local_sdk(tmp_path: Path) -> None:
    create_progressive_project(tmp_path)
    components = tmp_path / "components"
    components.mkdir()
    (components / "nodes.py").write_text(
        "from plyctl import node\n\n"
        "@node\n"
        "def worker() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )

    try:
        compiled = compile_local_project(tmp_path)
        assert compiled.namespace == "local"
        assert "local.worker" in compiled.compiled.provider_runtime.nodes
    finally:
        reset_local_development_modules()


def test_system_plan_uses_registered_default_and_local_components(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_progressive_project(tmp_path)
    resource = add_project_resource("system", "robot", root=tmp_path, make_default=True)
    components = tmp_path / "components"
    components.mkdir()
    (components / "nodes.py").write_text(
        "from plyctl import node\n\n"
        "@node\n"
        "def worker() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )
    dump_system(
        SystemModel(
            name="robot",
            graphs=(
                Graph(
                    name="main",
                    nodes=(NodeInstance(name="worker", uses="local.worker"),),
                ),
            ),
        ),
        resource.path,
    )

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["system", "plan"])
    assert result.exit_code == 0, result.output
    assert "PLAN robot" in result.output
    assert "local.worker" in result.output


def test_workflow_step_cache_skips_unchanged_expensive_step(tmp_path: Path) -> None:
    create_progressive_project(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("v1\n", encoding="utf-8")
    workflow = add_project_resource("workflow", "build", root=tmp_path)
    workflow.path.write_text(
        "schema: nodrix.workflow/v1\n"
        "name: build\n"
        "steps:\n"
        "  - id: compile\n"
        "    run: |\n"
        "      python3 -c \"from pathlib import Path; p=Path('count.txt'); p.write_text(str(int(p.read_text()) + 1) if p.exists() else '1'); Path('out.txt').write_text('ok')\"\n"
        "    cache:\n"
        "      inputs: [source.txt]\n"
        "      outputs: [out.txt]\n",
        encoding="utf-8",
    )

    first = run_workflow("build", root=tmp_path)
    assert first.succeeded
    assert first.steps[0].status == "succeeded"
    assert (tmp_path / "count.txt").read_text() == "1"

    second = run_workflow("build", root=tmp_path)
    assert second.succeeded
    assert second.steps[0].status == "cached"
    assert (tmp_path / "count.txt").read_text() == "1"

    source.write_text("v2 and changed size\n", encoding="utf-8")
    third = run_workflow("build", root=tmp_path)
    assert third.succeeded
    assert third.steps[0].status == "succeeded"
    assert (tmp_path / "count.txt").read_text() == "2"

    forced = run_workflow("build", root=tmp_path, force=True)
    assert forced.succeeded
    assert forced.steps[0].status == "succeeded"
    assert (tmp_path / "count.txt").read_text() == "3"
