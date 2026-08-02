from __future__ import annotations

import socket
import threading
from pathlib import Path

import numpy as np

import nodrix
from nodrix import Message
from nodrix.vision import Detections, Frame
from nodrix.discovery import discover_streams
from nodrix.manifest import load_manifest
from nodrix.project_templates import create_project
from nodrix.streams import StreamClient, StreamPublisher, StreamServer
from nodrix.wire import encode_message, recv_message, send_packet


def test_only_node_api_is_public() -> None:
    assert hasattr(nodrix, "Node")
    assert not hasattr(nodrix, "FastNode")


def test_init_creates_populated_runnable_project(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    created = create_project(project, "core")
    assert len(created) >= 14
    assert (project / "nodes/source.py").read_text().strip()
    assert (project / "nodes/transform.py").read_text().strip()
    assert (project / "nodes/sink.py").read_text().strip()
    assert (project / "tests/test_nodes.py").read_text().strip()
    manifest = load_manifest(project / "pipeline.yaml")
    assert manifest.api_version == "plyctl.dev/v2"
    assert manifest.streams.exports[0].name == "/demo/values"


def _roundtrip(message: Message) -> Message:
    left, right = socket.socketpair()
    try:
        packet = encode_message(message)
        sender = threading.Thread(target=send_packet, args=(left, packet))
        sender.start()
        result = recv_message(right)
        sender.join(timeout=2)
        return result
    finally:
        left.close()
        right.close()


def test_wire_roundtrip_frame_without_payload_repack() -> None:
    array = np.arange(8 * 6 * 3, dtype=np.uint8).reshape(6, 8, 3)
    message = Message(type="vision.frame", payload=Frame.from_numpy(array), sequence=7)
    result = _roundtrip(message)
    assert result.sequence == 7
    assert isinstance(result.payload, Frame)
    np.testing.assert_array_equal(result.payload.numpy(), array)


def test_wire_roundtrip_detections() -> None:
    detections = Detections(
        boxes=np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=np.float32),
        scores=np.array([0.9, 0.8], dtype=np.float32),
        class_ids=np.array([2, 4], dtype=np.int32),
    )
    result = _roundtrip(Message(type="vision.detections", payload=detections))
    assert isinstance(result.payload, Detections)
    np.testing.assert_array_equal(result.payload.boxes, detections.boxes)
    np.testing.assert_array_equal(result.payload.class_ids, detections.class_ids)


def test_direct_stream_server_client() -> None:
    server = StreamServer(host="127.0.0.1")
    server.register("/test/events", "core.object", capacity=2, policy="latest")
    server.start()
    client = StreamClient(f"nodrix://127.0.0.1:{server.port}/test/events")
    try:
        client.connect()
        server.publish("/test/events", Message(type="core.object", payload={"ok": True}, sequence=3))
        received = client.receive()
        assert received.type == "core.object"
        assert received.sequence == 3
        assert received.payload == {"ok": True}
    finally:
        client.close()
        server.close()


def test_zero_configuration_discovery() -> None:
    publisher = StreamPublisher(
        "discovery-test",
        [{
            "name": "/test/discovery",
            "source": "source.output",
            "type": "core.object",
            "capacity": 1,
            "policy": "latest",
        }],
    )
    publisher.start()
    try:
        streams = discover_streams(timeout=1.5, name="/test/discovery")
        assert any(item.name == "/test/discovery" for item in streams)
    finally:
        publisher.close()


def test_process_local_discovery_survives_blocked_multicast(
    monkeypatch,
) -> None:
    import nodrix.discovery as discovery

    monkeypatch.setattr(
        discovery.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("discovery must not depend on hostname DNS")
        ),
    )
    monkeypatch.setattr(
        discovery,
        "_send_multicast",
        lambda _sock, _interfaces, _data: None,
    )
    publisher = StreamPublisher(
        "local-discovery-test",
        [{
            "name": "/test/local-discovery",
            "source": "source.output",
            "type": "core.object",
        }],
    )
    publisher.start()
    try:
        streams = discover_streams(
            timeout=0.05,
            name="/test/local-discovery",
        )
        assert len(streams) == 1
        assert streams[0].endpoint.startswith(
            "nodrix://127.0.0.1:"
        )
    finally:
        publisher.close()
    assert discover_streams(
        timeout=0.05,
        name="/test/local-discovery",
    ) == []


def test_custom_type_codegen_python_cpp_and_wire(tmp_path: Path) -> None:
    schema = tmp_path / "tracked.yaml"
    schema.write_text(
        """
name: cobra.TrackedVehicle
version: 1
fields:
  object_id: uint64
  class_id: uint16
  confidence: float32
  bbox: float32[4]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    from nodrix.type_codegen import generate_type
    import importlib.util
    import sys

    generated = generate_type(schema, tmp_path / "generated")
    assert "static_assert(sizeof(TrackedVehicle) == 30);" in generated["cpp"].read_text()
    spec = importlib.util.spec_from_file_location("tracked_generated", generated["python"])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    value = module.TrackedVehicle(7, 2, 0.75, (1.0, 2.0, 3.0, 4.0))
    restored = module.TrackedVehicle.from_bytes(value.to_bytes())
    assert restored == value
    roundtrip = _roundtrip(Message(type="cobra.TrackedVehicle", payload=value))
    assert roundtrip.payload == value
