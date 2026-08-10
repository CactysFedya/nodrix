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
    ProcessBackend,
    SystemLink,
    SystemModel,
    SystemOrchestrator,
    Target,
    plan_execution_scopes,
    plan_system,
)


def _free_tcp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_two_process_scopes_exchange_messages_over_tcp(tmp_path: Path) -> None:
    port = _free_tcp_port()
    output = tmp_path / "received.jsonl"
    plan = plan_system(
        SystemModel(
            name="process-tcp-process",
            targets=(
                Target(
                    name="receiver",
                    kind="host",
                    properties={"backend": "process"},
                ),
                Target(
                    name="sender",
                    kind="host",
                    properties={"backend": "process"},
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
                                "payload": {"kind": "m4-cross-scope"},
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
        ExecutionScope(target="sender", backend="process"),
    )
    backends = {
        scope: ProcessBackend(
            working_directory=tmp_path,
            run_root=tmp_path / f"run-{scope.target}",
            scope_name=scope.target,
            startup_timeout_seconds=10.0,
            stop_timeout_seconds=2.0,
        )
        for scope in scopes
    }
    orchestrator = SystemOrchestrator(backends)

    validation = orchestrator.validate_plan(plan)
    assert validation.valid, validation.diagnostics
    prepared = orchestrator.prepare_plan(plan)

    manifests = {
        item.scope.target: item.prepared.payload.manifest_path
        for item in prepared.scopes
    }
    assert manifests["receiver"] != manifests["sender"]
    assert "__nodrix_transport_in_0" in manifests["receiver"].read_text(
        encoding="utf-8"
    )
    assert "__nodrix_transport_out_0" in manifests["sender"].read_text(
        encoding="utf-8"
    )

    handle = orchestrator.start(prepared, rollback_timeout_seconds=2.0)
    deadline = time.monotonic() + 15.0
    status = orchestrator.inspect(handle)
    while not status.terminal and time.monotonic() < deadline:
        time.sleep(0.05)
        status = orchestrator.inspect(handle)

    if not status.terminal:
        orchestrator.stop(handle, timeout_seconds=2.0)

    assert status.state is BackendExecutionState.COMPLETED, status
    assert all(item.status.state is BackendExecutionState.COMPLETED for item in status.scopes)
    assert output.exists()

    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 3
    assert [item["sequence"] for item in records] == [0, 1, 2]
    assert [item["payload"]["kind"] for item in records] == [
        "m4-cross-scope",
        "m4-cross-scope",
        "m4-cross-scope",
    ]
    assert [item["payload"]["sequence"] for item in records] == [0, 1, 2]
