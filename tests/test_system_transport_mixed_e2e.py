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
    SystemLink,
    SystemModel,
    SystemOrchestrator,
    Target,
    TransportLocalBackend,
    TransportProcessBackend,
    plan_execution_scopes,
    plan_system,
)


def _free_tcp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_local_sender_reaches_process_receiver_over_tcp(tmp_path: Path) -> None:
    port = _free_tcp_port()
    output = tmp_path / "mixed-received.jsonl"
    plan = plan_system(
        SystemModel(
            name="local-tcp-process",
            targets=(
                Target(
                    name="receiver",
                    kind="host",
                    properties={"backend": "process"},
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
                                "count": 4,
                                "payload": {"kind": "mixed-backend"},
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
                            "port": port,
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
    backends = {
        scopes[0]: TransportProcessBackend(
            working_directory=tmp_path,
            run_root=tmp_path / "run-receiver",
            scope_name="receiver",
            startup_timeout_seconds=10.0,
            stop_timeout_seconds=2.0,
        ),
        scopes[1]: TransportLocalBackend(
            working_directory=tmp_path,
            run_root=tmp_path / "run-sender",
            scope_name="sender",
            stop_timeout_seconds=2.0,
        ),
    }
    orchestrator = SystemOrchestrator(backends)

    validation = orchestrator.validate_plan(plan)
    assert validation.valid, validation.diagnostics
    prepared = orchestrator.prepare_plan(plan)
    handle = orchestrator.start(prepared, rollback_timeout_seconds=2.0)

    deadline = time.monotonic() + 15.0
    status = orchestrator.inspect(handle)
    while not status.terminal and time.monotonic() < deadline:
        time.sleep(0.05)
        status = orchestrator.inspect(handle)

    if not status.terminal:
        orchestrator.stop(handle, timeout_seconds=2.0)

    assert status.state is BackendExecutionState.COMPLETED, status
    assert output.exists()
    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 4
    assert [record["payload"]["sequence"] for record in records] == [0, 1, 2, 3]
    assert all(record["payload"]["kind"] == "mixed-backend" for record in records)
