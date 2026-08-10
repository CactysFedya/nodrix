from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.system import Graph, NodeInstance, SystemModel, Target, dump_system


runner = CliRunner()


def test_system_run_executes_process_scope(tmp_path: Path) -> None:
    system_path = tmp_path / "process.system.yaml"
    dump_system(
        SystemModel(
            name="process-cli",
            targets=(
                Target(
                    name="worker",
                    kind="host",
                    properties={"backend": "process"},
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="core.synthetic_source",
                            target="worker",
                            parameters={"count": 1},
                        ),
                        NodeInstance(
                            name="sink",
                            uses="core.counter_sink",
                            target="worker",
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
    assert "worker:process" in result.output
    assert "PREPARED" in result.output
    assert "STARTED" in result.output
    assert "COMPLETED" in result.output
