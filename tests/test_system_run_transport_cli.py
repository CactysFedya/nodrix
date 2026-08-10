from __future__ import annotations

import json
from pathlib import Path
import socket

from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.system import (
    Graph,
    NodeInstance,
    SystemLink,
    SystemModel,
    Target,
    dump_system,
)


runner = CliRunner()


def _free_tcp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _transport_system(
    *,
    output: Path,
    port: int,
    sender_backend: str,
    receiver_backend: str,
    payload_kind: str,
    count: int,
) -> SystemModel:
    return SystemModel(
        name="transport-cli",
        targets=(
            Target(
                name="receiver",
                kind="host",
                properties={"backend": receiver_backend},
            ),
            Target(
                name="sender",
                kind="host",
                properties={"backend": sender_backend},
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
                            "count": count,
                            "payload": {"kind": payload_kind},
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


def _run_system(system_path: Path):
    return runner.invoke(
        app,
        [
            "system",
            "run",
            str(system_path),
            "--stop-timeout",
            "2",
        ],
    )


def _records(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_system_run_moves_messages_between_process_scopes_over_tcp(
    tmp_path: Path,
) -> None:
    output = tmp_path / "cli-received.jsonl"
    system_path = tmp_path / "transport.system.yaml"
    dump_system(
        _transport_system(
            output=output,
            port=_free_tcp_port(),
            sender_backend="process",
            receiver_backend="process",
            payload_kind="cli-tcp",
            count=2,
        ),
        system_path,
    )

    result = _run_system(system_path)

    assert result.exit_code == 0, result.output
    assert "receiver:process" in result.output
    assert "sender:process" in result.output
    assert "scopes=2" in result.output
    assert result.output.count("COMPLETED") >= 2
    assert output.exists()
    records = _records(output)
    assert len(records) == 2
    assert [item["payload"]["kind"] for item in records] == [
        "cli-tcp",
        "cli-tcp",
    ]


def test_system_run_moves_messages_from_local_to_process_over_tcp(
    tmp_path: Path,
) -> None:
    output = tmp_path / "cli-mixed-received.jsonl"
    system_path = tmp_path / "transport-mixed.system.yaml"
    dump_system(
        _transport_system(
            output=output,
            port=_free_tcp_port(),
            sender_backend="local",
            receiver_backend="process",
            payload_kind="cli-mixed",
            count=3,
        ),
        system_path,
    )

    result = _run_system(system_path)

    assert result.exit_code == 0, result.output
    assert "receiver:process" in result.output
    assert "sender:local" in result.output
    assert "scopes=2" in result.output
    assert result.output.count("COMPLETED") >= 2
    records = _records(output)
    assert len(records) == 3
    assert [item["payload"]["kind"] for item in records] == [
        "cli-mixed",
        "cli-mixed",
        "cli-mixed",
    ]
