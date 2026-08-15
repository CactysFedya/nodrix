from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.system import (
    ApplicationInstance,
    Artifact,
    Graph,
    NodeInstance,
    ResourceInstance,
    SystemLink,
    SystemModel,
    Target,
    dump_system,
)


runner = CliRunner()


def test_system_help_lists_plan_command() -> None:
    result = runner.invoke(app, ["system", "--help"])

    assert result.exit_code == 0, result.output
    assert "plan" in result.output


def test_system_plan_human_output_shows_execution_topology(
    tmp_path: Path,
) -> None:
    path = tmp_path / "robot.yaml"
    dump_system(
        SystemModel(
            name="robot",
            targets=(
                Target(
                    name="pi",
                    kind="host",
                    properties={"backend": "local"},
                ),
                Target(
                    name="worker",
                    kind="host",
                    properties={"backend": "remote"},
                ),
            ),
            resources=(
                ResourceInstance(
                    name="camera",
                    uses="demo.camera",
                    target="pi",
                ),
            ),
            applications=(
                ApplicationInstance(
                    name="driver",
                    uses="demo.driver",
                    target="pi",
                ),
            ),
            graphs=(
                Graph(
                    name="capture",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="demo.source",
                            target="pi",
                            resources={"camera": "camera"},
                        ),
                    ),
                ),
                Graph(
                    name="mapping",
                    nodes=(
                        NodeInstance(
                            name="sink",
                            uses="demo.sink",
                            target="worker",
                        ),
                    ),
                ),
            ),
            links=(
                SystemLink(
                    **{
                        "from": "capture/source.output",
                        "to": "mapping/sink.input",
                        "uses": "demo.transport",
                    }
                ),
            ),
            artifacts=(
                Artifact(
                    name="map",
                    kind="map",
                    producer="mapping/sink.output",
                    path="maps/map.bin",
                ),
            ),
        ),
        path,
    )

    result = runner.invoke(app, ["system", "plan", str(path)])

    assert result.exit_code == 0, result.output
    assert "PLAN robot" in result.output
    assert "BACKENDS" in result.output
    assert "local" in result.output
    assert "remote" in result.output
    assert "capture" in result.output
    assert "mapping" in result.output
    assert "cross_target" in result.output
    assert "demo.transport" in result.output
    assert "map" in result.output


def test_system_plan_json_returns_execution_plan(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    dump_system(
        SystemModel(
            name="json-plan",
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="source", uses="demo.source"),
                        NodeInstance(name="sink", uses="demo.sink"),
                    ),
                    connections=(
                        {"from": "source.output", "to": "sink.input"},
                    ),
                ),
            ),
        ),
        path,
    )

    result = runner.invoke(
        app,
        ["system", "plan", str(path), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema"] == "nodrix.system-execution-plan/v1"
    assert payload["system"] == "json-plan"
    assert payload["targets"][0]["name"] == "local"
    assert payload["targets"][0]["implicit"] is True
    assert payload["summary"]["nodes"] == 2
    assert payload["graphs"][0]["topological_order"] == ["source", "sink"]


def test_system_plan_reports_planning_error(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.yaml"
    dump_system(
        SystemModel(
            name="ambiguous",
            targets=(
                Target(name="a", kind="host"),
                Target(name="b", kind="host"),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(NodeInstance(name="worker", uses="demo.worker"),),
                ),
            ),
        ),
        path,
    )

    result = runner.invoke(app, ["system", "plan", str(path)])

    assert result.exit_code == 1
    assert "System planning failed" in result.output
    assert "PLAN201" in result.output


def test_system_plan_json_error_is_machine_readable(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.yaml"
    dump_system(
        SystemModel(
            name="ambiguous",
            targets=(
                Target(name="a", kind="host"),
                Target(name="b", kind="host"),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(NodeInstance(name="worker", uses="demo.worker"),),
                ),
            ),
        ),
        path,
    )

    result = runner.invoke(
        app,
        ["system", "plan", str(path), "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "PLAN201" in payload["error"]


def test_system_plan_surfaces_cycle_warning(tmp_path: Path) -> None:
    path = tmp_path / "cycle.yaml"
    dump_system(
        SystemModel(
            name="cycle",
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="a", uses="demo.a"),
                        NodeInstance(name="b", uses="demo.b"),
                    ),
                    connections=(
                        {"from": "a.output", "to": "b.input"},
                        {"from": "b.output", "to": "a.input"},
                    ),
                ),
            ),
        ),
        path,
    )

    result = runner.invoke(app, ["system", "plan", str(path)])

    assert result.exit_code == 0, result.output
    assert "DIAGNOSTICS" in result.output
    assert "PLAN101" in result.output

    strict = runner.invoke(
        app,
        ["system", "plan", str(path), "--warnings-as-errors"],
    )
    assert strict.exit_code == 1
    assert "PLAN101" in strict.output


def test_system_plan_with_project_uses_typed_validation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    components = project / "components"
    components.mkdir(parents=True)

    (components / "types.py").write_text(
        "from dataclasses import dataclass\n"
        "from plyctl import message\n\n"
        "@message\n"
        "@dataclass(frozen=True)\n"
        "class Frame:\n"
        "    value: int\n",
        encoding="utf-8",
    )
    (components / "nodes.py").write_text(
        "from plyctl import node\n"
        "from components.types import Frame\n\n"
        "@node\n"
        "def source() -> Frame:\n"
        "    return Frame(1)\n\n"
        "@node\n"
        "def sink(image: Frame) -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )

    path = project / "system.yaml"
    dump_system(
        SystemModel(
            name="typed",
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="source", uses="local.source"),
                        NodeInstance(name="sink", uses="local.sink"),
                    ),
                    connections=(
                        {
                            "from": "source.output",
                            "to": "sink.missing",
                        },
                    ),
                ),
            ),
        ),
        path,
    )

    result = runner.invoke(
        app,
        [
            "system",
            "plan",
            str(path),
            "--project",
            str(project),
        ],
    )

    assert result.exit_code == 1
    assert "PLAN100" in result.output
    assert "SYS132" in result.output
