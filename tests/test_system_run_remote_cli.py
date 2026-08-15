from __future__ import annotations

import json
from pathlib import Path

from typer.main import get_command
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.system import (
    Graph,
    NodeInstance,
    RemoteAgentServer,
    SystemModel,
    Target,
    dump_system,
)


runner = CliRunner()
TOKEN_ENV = "NODRIX_TEST_REMOTE_CLI_TOKEN"


def test_agent_serve_help_exposes_safe_m5a_options() -> None:
    result = runner.invoke(app, ["agent", "serve", "--help"])
    assert result.exit_code == 0, result.output

    root = get_command(app)
    agent = root.commands["agent"]
    serve = agent.commands["serve"]
    options = {
        option
        for parameter in serve.params
        for option in getattr(parameter, "opts", ())
    }
    assert {
        "--host",
        "--port",
        "--token-env",
        "--working-directory",
    } <= options


def test_system_run_executes_remote_process_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "remote-cli-token"
    monkeypatch.setenv(TOKEN_ENV, token)
    output = tmp_path / "remote-cli-output.jsonl"

    with RemoteAgentServer(
        token=token,
        working_directory=tmp_path / "agent-work",
        run_root=tmp_path / "agent-runs",
    ) as server:
        host, port = server.address
        system_path = tmp_path / "remote.system.yaml"
        dump_system(
            SystemModel(
                name="remote-cli",
                targets=(
                    Target(
                        name="robot",
                        kind="host",
                        properties={
                            "backend": "process",
                            "agent": {
                                "host": host,
                                "port": port,
                                "token_env": TOKEN_ENV,
                            },
                        },
                    ),
                ),
                graphs=(
                    Graph(
                        name="main",
                        nodes=(
                            NodeInstance(
                                name="source",
                                uses="core.synthetic_source",
                                target="robot",
                                parameters={
                                    "count": 2,
                                    "payload": {"kind": "remote-cli"},
                                },
                            ),
                            NodeInstance(
                                name="sink",
                                uses="sink.jsonl",
                                target="robot",
                                parameters={"path": str(output)},
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

        result = runner.invoke(
            app,
            ["system", "run", str(system_path), "--stop-timeout", "2"],
        )

    assert result.exit_code == 0, result.output
    assert "robot:process" in result.output
    assert "agent=127.0.0.1:" in result.output
    assert "STARTED" in result.output
    assert "COMPLETED" in result.output
    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 2
    assert all(record["payload"]["kind"] == "remote-cli" for record in records)
