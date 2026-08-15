from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.system import Graph, NodeInstance, SystemModel, Target, dump_system


runner = CliRunner()


def test_system_run_executes_two_real_local_scopes(tmp_path: Path) -> None:
    system_path = tmp_path / "multi-local.system.yaml"
    dump_system(
        SystemModel(
            name="multi-local-real",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={"backend": "local"},
                ),
                Target(
                    name="workstation",
                    kind="host",
                    properties={"backend": "local"},
                ),
            ),
            graphs=(
                Graph(
                    name="robot_graph",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="core.synthetic_source",
                            target="robot",
                            parameters={"count": 2},
                        ),
                        NodeInstance(
                            name="sink",
                            uses="core.counter_sink",
                            target="robot",
                        ),
                    ),
                    connections=(
                        {"from": "source.output", "to": "sink.input"},
                    ),
                ),
                Graph(
                    name="workstation_graph",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="core.synthetic_source",
                            target="workstation",
                            parameters={"count": 2},
                        ),
                        NodeInstance(
                            name="sink",
                            uses="core.counter_sink",
                            target="workstation",
                        ),
                    ),
                    connections=(
                        {"from": "source.output", "to": "sink.input"},
                    ),
                ),
            ),
        ),
        system_path,
    )

    result = runner.invoke(app, ["system", "run", str(system_path)])

    assert result.exit_code == 0, result.output
    assert "scopes=2" in result.output
    assert "robot:local" in result.output
    assert "workstation:local" in result.output
    assert result.output.count("COMPLETED") >= 2

    generated = tmp_path / ".nodrix" / "system-generated"
    robot_manifests = tuple(generated.glob("*-robot-local.yaml"))
    workstation_manifests = tuple(generated.glob("*-workstation-local.yaml"))

    assert len(robot_manifests) == 1
    assert len(workstation_manifests) == 1
    assert robot_manifests[0] != workstation_manifests[0]
