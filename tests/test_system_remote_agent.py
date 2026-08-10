from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from nodrix.system import (
    BackendExecutionState,
    ExecutionScope,
    Graph,
    NodeInstance,
    RemoteAgentClient,
    RemoteAgentEndpoint,
    RemoteAgentError,
    RemoteAgentServer,
    RemoteProcessBackend,
    SystemModel,
    SystemOrchestrator,
    Target,
    plan_execution_scopes,
    plan_system,
)


TOKEN_ENV = "NODRIX_TEST_REMOTE_AGENT_TOKEN"


def _remote_plan(
    *,
    host: str,
    port: int,
    output: Path,
    count: int = 3,
) -> object:
    return plan_system(
        SystemModel(
            name="remote-agent-system",
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
                    name="remote_graph",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="core.synthetic_source",
                            target="robot",
                            parameters={
                                "count": count,
                                "payload": {"kind": "remote-m5"},
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
        )
    )


def _wait_terminal(orchestrator, handle, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    status = orchestrator.inspect(handle)
    while not status.terminal and time.monotonic() < deadline:
        time.sleep(0.05)
        status = orchestrator.inspect(handle)
    return status


def test_remote_agent_requires_valid_token(tmp_path: Path) -> None:
    with RemoteAgentServer(
        token="correct-token",
        working_directory=tmp_path / "agent",
    ) as server:
        host, port = server.address
        client = RemoteAgentClient(
            RemoteAgentEndpoint(
                host=host,
                port=port,
                token="wrong-token",
            )
        )
        with pytest.raises(RemoteAgentError, match="AGENT401"):
            client.ping()


def test_remote_agent_rejects_non_loopback_listener(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback-only"):
        RemoteAgentServer(
            host="0.0.0.0",
            token="secret",
            working_directory=tmp_path,
        )


def test_remote_process_backend_runs_scope_through_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "m5-agent-token"
    monkeypatch.setenv(TOKEN_ENV, token)
    output = tmp_path / "remote-output.jsonl"

    with RemoteAgentServer(
        token=token,
        working_directory=tmp_path / "agent-work",
        run_root=tmp_path / "agent-runs",
    ) as server:
        host, port = server.address
        plan = _remote_plan(host=host, port=port, output=output)
        scopes = plan_execution_scopes(plan)
        assert scopes == (ExecutionScope(target="robot", backend="process"),)

        backend = RemoteProcessBackend(working_directory=tmp_path)
        orchestrator = SystemOrchestrator({scopes[0]: backend})
        report = orchestrator.validate_plan(plan)
        assert report.valid, report.diagnostics

        prepared = orchestrator.prepare_plan(plan)
        assert prepared.scopes[0].prepared.metadata["remote"] is True
        handle = orchestrator.start(prepared)
        status = _wait_terminal(orchestrator, handle)

        assert status.state is BackendExecutionState.COMPLETED, status
        scope_status = status.scopes[0].status
        assert scope_status.backend == "process"
        assert scope_status.details["remote"] is True
        assert output.exists()

    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 3
    assert [record["payload"]["kind"] for record in records] == [
        "remote-m5",
        "remote-m5",
        "remote-m5",
    ]


def test_remote_process_backend_reports_unreachable_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(TOKEN_ENV, "unused-token")
    plan = _remote_plan(
        host="127.0.0.1",
        port=65534,
        output=tmp_path / "never.jsonl",
    )
    scope = plan_execution_scopes(plan)[0]
    backend = RemoteProcessBackend(working_directory=tmp_path)
    orchestrator = SystemOrchestrator({scope: backend})

    report = orchestrator.validate_plan(plan)
    assert report.valid, report.diagnostics
    with pytest.raises(RemoteAgentError, match="AGENT503"):
        orchestrator.prepare_plan(plan)
