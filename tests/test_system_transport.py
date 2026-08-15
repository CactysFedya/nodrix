from __future__ import annotations

from pathlib import Path
import socket
import threading

import pytest

from nodrix.messages import Message
from nodrix.node import NodeContext
from nodrix.registry import load_node_class
from nodrix.system import (
    Graph,
    NodeInstance,
    SystemLink,
    SystemModel,
    Target,
    TransportRuntimeAdapter,
    backend_context_for_scope,
    lower_local_context,
    lower_transport_boundaries,
    plan_execution_scopes,
    plan_system,
    register_transport_runtime,
    registered_transport_runtimes,
    require_transport_runtime,
)


def _free_tcp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _context(tmp_path: Path, name: str) -> NodeContext:
    return NodeContext(
        name=name,
        run_dir=tmp_path,
        project_dir=tmp_path,
        runtime_mode="offline",
    )


def test_builtin_tcp_transport_is_registered_and_validates_parameters() -> None:
    assert "tcp" in registered_transport_runtimes()
    adapter = require_transport_runtime("tcp")
    assert adapter.sender_node == "core.transport_tcp_sink"
    assert adapter.receiver_node == "core.transport_tcp_source"

    adapter.validate({"host": "127.0.0.1", "port": 43001})

    with pytest.raises(ValueError, match="requires non-empty parameter 'host'"):
        adapter.validate({"port": 43001})
    with pytest.raises(ValueError, match="between 1 and 65535"):
        adapter.validate({"host": "127.0.0.1", "port": 0})


def test_transport_runtime_registry_rejects_duplicate_ids() -> None:
    adapter = TransportRuntimeAdapter(
        id="tcp",
        sender_node="example.sender",
        receiver_node="example.receiver",
        validate_parameters=lambda parameters: None,
    )
    with pytest.raises(ValueError, match="already registered"):
        register_transport_runtime(adapter)


def test_tcp_transport_moves_real_nodrix_message_over_loopback(tmp_path: Path) -> None:
    port = _free_tcp_port()
    source_cls = load_node_class("core.transport_tcp_source")
    sink_cls = load_node_class("core.transport_tcp_sink")

    source = source_cls(
        {
            "bind_host": "127.0.0.1",
            "host": "127.0.0.1",
            "port": port,
        }
    )
    sink = sink_cls(
        {
            "host": "127.0.0.1",
            "port": port,
            "connect_timeout_seconds": 2.0,
        }
    )
    source.open(_context(tmp_path, "receiver"))
    sink.open(_context(tmp_path, "sender"))

    received: list[Message] = []
    error: list[BaseException] = []

    def receive_one() -> None:
        try:
            produced = source.produce()
            received.append(next(produced)["output"])
        except BaseException as exc:  # pragma: no cover - asserted below
            error.append(exc)

    thread = threading.Thread(target=receive_one, daemon=True)
    thread.start()

    original = Message(
        type="core.object",
        payload={"value": 42, "transport": "tcp"},
        sequence=7,
        timestamp_ns=123456789,
        trace_id="trace-m4",
        stream_id="cross-scope",
        metadata={"origin": "sender"},
    )
    sink.process({"input": original})
    thread.join(timeout=3.0)

    try:
        assert not thread.is_alive(), "TCP receiver did not receive the message"
        assert not error, error
        assert len(received) == 1
        message = received[0]
        assert message.type == original.type
        assert message.payload == original.payload
        assert message.sequence == original.sequence
        assert message.timestamp_ns == original.timestamp_ns
        assert message.trace_id == original.trace_id
        assert message.stream_id == original.stream_id
        assert message.metadata == original.metadata
    finally:
        sink.close()
        source.close()


def test_transport_lowering_injects_sender_and_receiver_boundaries() -> None:
    port = 43002
    plan = plan_system(
        SystemModel(
            name="tcp-boundary",
            targets=(
                Target(
                    name="sender",
                    kind="host",
                    properties={"backend": "process"},
                ),
                Target(
                    name="receiver",
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
                        ),
                    ),
                ),
                Graph(
                    name="consumer",
                    nodes=(
                        NodeInstance(
                            name="sink",
                            uses="core.counter_sink",
                            target="receiver",
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
                        },
                    }
                ),
            ),
        )
    )
    scopes = plan_execution_scopes(plan)
    sender_scope = next(scope for scope in scopes if scope.target == "sender")
    receiver_scope = next(scope for scope in scopes if scope.target == "receiver")

    sender_context = backend_context_for_scope(plan, sender_scope)
    receiver_context = backend_context_for_scope(plan, receiver_scope)
    sender = lower_transport_boundaries(
        sender_context,
        lower_local_context(sender_context),
    ).manifest
    receiver = lower_transport_boundaries(
        receiver_context,
        lower_local_context(receiver_context),
    ).manifest

    assert sender.nodes["__nodrix_transport_out_0"].uses == "core.transport_tcp_sink"
    assert receiver.nodes["__nodrix_transport_in_0"].uses == "core.transport_tcp_source"
    assert any(
        edge.target == "__nodrix_transport_out_0.input"
        for edge in sender.edges
    )
    assert any(
        edge.source == "__nodrix_transport_in_0.output"
        for edge in receiver.edges
    )
