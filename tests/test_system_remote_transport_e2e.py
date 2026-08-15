from __future__ import annotations

import json
from pathlib import Path
import socket
import time

from nodrix.system import (
    BackendExecutionState,
    ExecutionScope,
    Graph,
    NodeInstance,
    RemoteAgentServer,
    RemoteProcessBackend,
    SystemLink,
    SystemModel,
    SystemOrchestrator,
    Target,
    TransportLocalBackend,
    plan_execution_scopes,
    plan_system,
)


TOKEN_ENV = "NODRIX_TEST_REMOTE_TRANSPORT_TOKEN"


def _free_tcp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_local_scope_streams_to_remote_process_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "remote-transport-token"
    monkeypatch.setenv(TOKEN_ENV, token)
    output = tmp_path / "remote-received.jsonl"
    data_port = _free_tcp_port()

    with RemoteAgentServer(
        token=token,
        working_directory=tmp_path / "agent-work",
        run_root=tmp_path / "agent-runs",
    ) as agent:
        agent_host, agent_port = agent.address
        plan = plan_system(
            SystemModel(
                name="local-to-remote",
                targets=(
                    Target(
                        name="receiver",
                        kind="host",
                        properties={
                            "backend": "process",
                            "agent": {
                                "host": agent_host,
                                "port": agent_port,
                                "token_env": TOKEN_ENV,
                            },
                        },
                    ),
                    Target(
                        name="sender",
                        kind="host",
                        properties={"backend": "local"},
                    ),
                ),
                graphs=(
                    Graph(
                        name="producer",
                        nodes=(
                            NodeInstance(
                                name="source",
                                uses="core.synthetic_source",
                                target="sender",
                                parameters={
                                    "count": 3,
                                    "payload": {"kind": "remote-data-plane"},
                                },
                            ),
                        ),
                    ),
                    Graph(
                        name="consumer",
                        nodes=(
                            NodeInstance(
                                name="sink",
                                uses="sink.jsonl",
                                target="receiver",
                                parameters={"path": str(output)},
                            ),
                        ),
                    ),
                ),
                links=(
                    SystemLink(
                        **{
                            "from": "producer/source.output",
                            "to": "consumer/sink.input",
                            "uses": "tcp",
                            "parameters": {
                                "host": "127.0.0.1",
                                "bind_host": "127.0.0.1",
                                "port": data_port,
                                "connect_timeout_seconds": 5.0,
                            },
                        }
                    ),
                ),
            )
        )

        scopes = plan_execution_scopes(plan)
        assert scopes == (
            ExecutionScope(target="receiver", backend="process"),
            ExecutionScope(target="sender", backend="local"),
        )
        orchestrator = SystemOrchestrator(
            {
                scopes[0]: RemoteProcessBackend(working_directory=tmp_path),
                scopes[1]: TransportLocalBackend(
                    working_directory=tmp_path,
                    run_root=tmp_path / "sender-run",
                    scope_name="sender",
                    stop_timeout_seconds=2.0,
                ),
            }
        )
        validation = orchestrator.validate_plan(plan)
        assert validation.valid, validation.diagnostics
        prepared = orchestrator.prepare_plan(plan)

        remote_prepared = prepared.scopes[0].prepared
        local_prepared = prepared.scopes[1].prepared
        assert remote_prepared.metadata["remote"] is True
        assert remote_prepared.metadata["remote_metadata"]["transport_links"] == 1
        assert local_prepared.metadata["transport_links"] == 1

        handle = orchestrator.start(prepared, rollback_timeout_seconds=2.0)
        deadline = time.monotonic() + 15.0
        status = orchestrator.inspect(handle)
        while not status.terminal and time.monotonic() < deadline:
            time.sleep(0.05)
            status = orchestrator.inspect(handle)

        if not status.terminal:
            status = orchestrator.stop(handle, timeout_seconds=2.0)

        assert status.state is BackendExecutionState.COMPLETED, status
        assert status.scopes[0].status.details["remote"] is True

    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 3
    assert [record["payload"]["sequence"] for record in records] == [0, 1, 2]
    assert all(
        record["payload"]["kind"] == "remote-data-plane"
        for record in records
    )
