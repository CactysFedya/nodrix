from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import yaml

from nodrix import Message, SharedBufferPool
from nodrix.cv_types import EncodedFrame, Frame, ManagedBuffer, MediaCodec, PixelFormat
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.manifest import load_manifest
from nodrix.node import NodeContext
from nodrix.process_host import ProcessNodeProxy
from nodrix.recording import NdrxReader, NdrxWriter
from nodrix.shared_memory import descriptor_for_buffer, open_shared_buffer
from nodrix.viewer import FFmpegAccessUnitDecoder, LatestSlot


def test_shared_buffer_pool_descriptor_only_roundtrip() -> None:
    with SharedBufferPool(4096, 2) as pool:
        buffer = pool.acquire(128)
        buffer.memoryview()[:5] = b"NDRX8"
        descriptor = descriptor_for_buffer(buffer)
        assert descriptor is not None
        mapped = open_shared_buffer(descriptor)
        assert bytes(mapped.memoryview()[:5]) == b"NDRX8"
        assert mapped.memory_type.value == "shared"
        mapped.release()
        buffer.release()
        assert pool.stats()["in_use"] == 0


def _write_node(path: Path, source: str) -> str:
    path.write_text(source, encoding="utf-8")
    return f"{path}:Worker"


def test_process_node_uses_descriptor_without_input_copy(tmp_path: Path) -> None:
    reference = _write_node(tmp_path / "worker.py", """
from nodrix import Node
class Worker(Node):
    input_types = {"input": "core.bytes"}
    output_types = {}
    def process(self, inputs):
        assert bytes(inputs["input"].payload.memoryview()[:4]) == b"zero"
        return None
""")
    proxy = ProcessNodeProxy(
        name="worker", uses=reference, base_dir=tmp_path, parameters={},
        input_types={"input": "core.bytes"}, output_types={}, block_size=4096,
        capacity=2, threshold=16, failure_policy="stop_pipeline", max_restarts=0,
        backoff_ms=0, cpu_affinity=[],
    )
    proxy.open(NodeContext("worker", tmp_path, tmp_path, "offline"))
    with SharedBufferPool(4096, 1) as source_pool:
        payload = source_pool.acquire(128)
        payload.memoryview()[:4] = b"zero"
        proxy.process({"input": Message(type="core.bytes", payload=payload)})
        assert proxy.transport_report()["input_payload_copies"] == 0
        payload.release()
    proxy.close()


def test_process_node_restart_policy(tmp_path: Path) -> None:
    marker = tmp_path / "crashed"
    reference = _write_node(tmp_path / "restart.py", """
from pathlib import Path
import os
from nodrix import Message, Node
class Worker(Node):
    input_types = {"input": "core.object"}
    output_types = {"output": "core.object"}
    def process(self, inputs):
        marker = Path(self.parameters["marker"])
        if not marker.exists():
            marker.write_text("1")
            os._exit(17)
        return {"output": inputs["input"]}
""")
    proxy = ProcessNodeProxy(
        name="restart", uses=reference, base_dir=tmp_path, parameters={"marker": str(marker)},
        input_types={"input": "core.object"}, output_types={"output": "core.object"},
        block_size=4096, capacity=2, threshold=16, failure_policy="restart",
        max_restarts=1, backoff_ms=1, cpu_affinity=[],
    )
    proxy.open(NodeContext("restart", tmp_path, tmp_path, "offline"))
    output = proxy.process({"input": Message(type="core.object", payload={"ok": True})})
    assert output is not None and output["output"].payload == {"ok": True}
    assert proxy.transport_report()["restarts"] == 1
    proxy.close()


def test_ndrx_recording_preserves_typed_messages(tmp_path: Path) -> None:
    path = tmp_path / "experiment.ndrx"
    image = np.arange(64 * 48 * 3, dtype=np.uint8).reshape(48, 64, 3)
    frame = Frame.from_numpy(image, pixel_format=PixelFormat.BGR8)
    with NdrxWriter(path, metadata={"pipeline": "test"}) as writer:
        writer.write(Message(type="vision.frame", payload=frame, sequence=7, stream_id="/camera/raw"))
        writer.write(Message(type="core.object", payload={"value": 3}, sequence=8, stream_id="/metrics"))
    with NdrxReader(path) as reader:
        info = reader.info()
        messages = [message for _, message in reader.iter_messages()]
    assert info["messages"] == 2
    assert info["streams"]["/camera/raw"]["type"] == "vision.frame"
    assert np.array_equal(messages[0].payload.numpy(), image)
    assert messages[1].payload == {"value": 3}


def test_manifest_accepts_process_isolation(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(yaml.safe_dump({
        "apiVersion": "nodrix.dev/v1", "kind": "Pipeline", "metadata": {"name": "isolated"},
        "runtime": {"memory": {"shared_pool": {"block_size": 1048576, "capacity": 4, "threshold": 1024}}},
        "nodes": {
            "source": {"uses": "core.synthetic_source", "parameters": {"count": 2}},
            "worker": {"uses": "core.identity", "execution": {"isolation": "process"},
                       "failure": {"policy": "restart", "max_restarts": 1}},
            "sink": {"uses": "core.counter_sink"},
        },
        "edges": [
            {"from": "source.output", "to": "worker.input"},
            {"from": "worker.output", "to": "sink.input"},
        ],
    }, sort_keys=False), encoding="utf-8")
    runtime = HybridPipelineRuntime(load_manifest(pipeline), pipeline)
    runtime.build()
    report = runtime.run_sync()
    assert report["nodes"]["worker"]["transport"]["isolation"] == "process"
    assert report["nodes"]["worker"]["messages"] == 2


def test_h264_access_unit_decoder_flushes_latest_frame(tmp_path: Path) -> None:
    raw_path = tmp_path / "test.h264"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        "testsrc=size=64x48:rate=10", "-frames:v", "5", "-c:v", "libx264",
        "-preset", "ultrafast", "-tune", "zerolatency", "-f", "h264", str(raw_path),
    ], check=True)
    raw = raw_path.read_bytes()
    encoded = EncodedFrame(ManagedBuffer.wrap(raw), MediaCodec.H264, 64, 48, 10)
    slot = LatestSlot()
    decoder = FFmpegAccessUnitDecoder(slot, encoded)
    decoder.write(Message(type="vision.encoded_frame", payload=encoded, sequence=1))
    decoder.finish()
    _, message = slot.wait_next(0, 0.5)
    assert message is not None
    assert message.payload.numpy().shape == (48, 64, 3)
    assert slot.overwritten >= 1


def test_ffmpeg_encoder_outputs_valid_annex_b(tmp_path: Path) -> None:
    from nodrix.media import FFmpegEncoder, probe_media

    encoder = FFmpegEncoder({"codec": "h264", "fps": 10, "read_timeout_ms": 30})
    encoder.open(NodeContext("encoder", tmp_path, tmp_path, "offline"))
    chunks: list[bytes] = []
    slot = LatestSlot()
    decoder = None
    version = 0
    live_frames = 0
    for sequence in range(20):
        image = np.full((48, 64, 3), sequence * 10, dtype=np.uint8)
        frame = Frame.from_numpy(image, pixel_format=PixelFormat.BGR8)
        output = encoder.process({"frame": Message(
            type="vision.frame", payload=frame, sequence=sequence, metadata={"fps": 10}
        )})
        if output:
            encoded_message = output["encoded"]
            chunks.append(bytes(encoded_message.payload.memoryview()))
            if decoder is None:
                decoder = FFmpegAccessUnitDecoder(slot, encoded_message.payload)
            decoder.write(encoded_message)
            next_version, decoded = slot.wait_next(version, 0.15)
            if decoded is not None:
                version = next_version
                live_frames += 1
    flushed = encoder.flush()
    if flushed:
        encoded_message = flushed["encoded"]
        chunks.append(bytes(encoded_message.payload.memoryview()))
        if decoder is None:
            decoder = FFmpegAccessUnitDecoder(slot, encoded_message.payload)
        decoder.write(encoded_message)
    encoder.close()
    assert decoder is not None
    decoder.finish()
    assert live_frames > 0
    path = tmp_path / "encoded.h264"
    path.write_bytes(b"".join(chunks))
    info = probe_media(str(path), input_format="h264")
    assert info["video"]["codec"] == "h264"
    assert info["video"]["width"] == 64
