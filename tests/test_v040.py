from __future__ import annotations

from pathlib import Path
import time

import numpy as np
import pytest

from nodrix import BufferPool, Message, Node, SinkNode, SourceNode
from nodrix.vision import Detections, Frame
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.manifest import PipelineManifest
from nodrix.registry import BUILTINS


def _runtime(tmp_path: Path, manifest_data: dict) -> HybridPipelineRuntime:
    manifest = PipelineManifest.model_validate(manifest_data)
    path = tmp_path / "pipeline.yaml"
    path.write_text("metadata: {name: placeholder}\nnodes: {}\nedges: []\n")
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    return runtime


def test_native_buffer_pool_reuses_storage() -> None:
    pool = BufferPool(4096, max_cached=2)
    first = pool.acquire()
    assert first.nbytes == 4096
    owner = first.owner
    owner.release()
    second = pool.acquire()
    stats = pool.stats()
    assert stats["native"] is True
    assert stats["allocations"] == 1
    assert stats["reuses"] == 1
    second.owner.release()


def test_standard_detection_contract_rejects_invalid_shape() -> None:
    with pytest.raises(ValueError):
        Detections(boxes=[[1, 2, 3]], scores=[0.9], class_ids=[0])


def test_legacy_numpy_frame_is_wrapped_without_copy(tmp_path: Path) -> None:
    class Source(SourceNode):
        output_types = {"frame": "vision.frame"}

        def open(self, context):
            super().open(context)
            self.array = np.zeros((8, 8, 3), dtype=np.uint8)

        def produce(self):
            yield {"frame": Message(type="vision.frame", payload=self.array, sequence=1)}

    class Sink(SinkNode):
        input_types = {"frame": "vision.frame"}

        def open(self, context):
            super().open(context)
            self.owner_id = None

        def process(self, inputs):
            frame = inputs["frame"].payload
            assert isinstance(frame, Frame)
            self.owner_id = id(frame.buffer.owner)

    BUILTINS["test.v040_source"] = Source
    BUILTINS["test.v040_sink"] = Sink
    runtime = _runtime(tmp_path, {
        "metadata": {"name": "legacy-frame"},
        "runtime": {"engine": "unified", "type_validation": "always"},
        "nodes": {
            "source": {"uses": "test.v040_source"},
            "sink": {"uses": "test.v040_sink"},
        },
        "edges": [{"from": "source.frame", "to": "sink.frame"}],
    })
    source = runtime.nodes["source"].node
    sink = runtime.nodes["sink"].node
    report = runtime.run_sync()
    assert report["status"] == "completed"
    assert sink.owner_id == id(source.array)


def test_approximate_timestamp_synchronization(tmp_path: Path) -> None:
    base = time.time_ns()

    class A(SourceNode):
        output_types = {"out": "core.object"}
        def produce(self):
            yield {"out": Message(type="core.object", payload="a", sequence=1, timestamp_ns=base)}

    class B(SourceNode):
        output_types = {"out": "core.object"}
        def produce(self):
            yield {"out": Message(type="core.object", payload="b", sequence=99, timestamp_ns=base + 5_000_000)}

    class Join(SinkNode):
        input_types = {"a": "core.object", "b": "core.object"}
        def open(self, context): super().open(context); self.values = []
        def process(self, inputs): self.values.append((inputs["a"].payload, inputs["b"].payload))

    BUILTINS.update({"test.sync_a": A, "test.sync_b": B, "test.sync_join": Join})
    runtime = _runtime(tmp_path, {
        "metadata": {"name": "approx-sync"},
        "runtime": {"engine": "unified"},
        "nodes": {
            "a": {"uses": "test.sync_a"},
            "b": {"uses": "test.sync_b"},
            "join": {
                "uses": "test.sync_join",
                "synchronization": {"policy": "approximate_timestamp", "tolerance_ms": 10},
            },
        },
        "edges": [
            {"from": "a.out", "to": "join.a"},
            {"from": "b.out", "to": "join.b"},
        ],
    })
    join = runtime.nodes["join"].node
    report = runtime.run_sync()
    assert report["status"] == "completed"
    assert join.values == [("a", "b")]


def test_telemetry_reports_percentiles(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, {
        "metadata": {"name": "telemetry"},
        "runtime": {"engine": "unified"},
        "nodes": {
            "source": {"uses": "core.synthetic_source", "parameters": {"count": 20}},
            "delay": {"uses": "core.delay", "parameters": {"milliseconds": 0.1}},
            "sink": {"uses": "core.counter_sink"},
        },
        "edges": [
            {"from": "source.output", "to": "delay.input"},
            {"from": "delay.output", "to": "sink.input"},
        ],
    })
    report = runtime.run_sync()
    stats = report["nodes"]["delay"]
    assert stats["p95_ms"] >= 0
    assert stats["processing"]["sample_count"] == 20
    assert stats["queue_wait"]["count"] == 20
    assert stats["end_to_end"]["count"] == 20


def test_latest_available_reuses_side_input(tmp_path: Path) -> None:
    class Frames(SourceNode):
        output_types = {"out": "core.object"}
        def produce(self):
            for sequence in range(3):
                yield {"out": Message(type="core.object", payload=f"f{sequence}", sequence=sequence)}

    class Model(SourceNode):
        output_types = {"out": "core.object"}
        def produce(self):
            yield {"out": Message(type="core.object", payload="detection", sequence=0)}

    class Join(SinkNode):
        input_types = {"frame": "core.object", "detections": "core.object"}
        def open(self, context): super().open(context); self.values = []
        def process(self, inputs):
            self.values.append((inputs["frame"].payload, inputs["detections"].payload))

    BUILTINS.update({"test.latest_frames": Frames, "test.latest_model": Model, "test.latest_join": Join})
    runtime = _runtime(tmp_path, {
        "metadata": {"name": "latest-side-input"},
        "runtime": {"engine": "unified"},
        "nodes": {
            "frames": {"uses": "test.latest_frames"},
            "model": {"uses": "test.latest_model"},
            "join": {
                "uses": "test.latest_join",
                "synchronization": {"policy": "latest_available", "trigger_port": "frame"},
            },
        },
        "edges": [
            {"from": "frames.out", "to": "join.frame"},
            {"from": "model.out", "to": "join.detections"},
        ],
    })
    join = runtime.nodes["join"].node
    report = runtime.run_sync()
    assert report["status"] == "completed"
    assert join.values == [("f0", "detection"), ("f1", "detection"), ("f2", "detection")]
