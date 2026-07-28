from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from nodrix import Node, SinkNode, SourceNode, Message
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.manifest import PipelineManifest
from nodrix.registry import BUILTINS


class ArraySource(SourceNode):
    output_types = {"frame": "vision.frame"}

    def open(self, context):
        super().open(context)
        self.frame = np.zeros((32, 32, 3), dtype=np.uint8)

    def produce(self):
        yield {"frame": Message(type="vision.frame", payload=self.frame, sequence=1)}


class PassThrough(Node):
    input_types = {"frame": "vision.frame"}
    output_types = {"frame": "vision.frame"}

    def process(self, inputs):
        return {"frame": inputs["frame"]}


class IdSink(SinkNode):
    input_types = {"frame": "vision.frame"}

    def open(self, context):
        super().open(context)
        self.payload_ids = []

    def process(self, inputs):
        payload = inputs["frame"].payload
        self.payload_ids.append(id(payload.buffer.owner))


def test_hybrid_runtime_uses_native_queue_and_zero_copy(tmp_path: Path) -> None:
    BUILTINS["test.array_source"] = ArraySource
    BUILTINS["test.pass"] = PassThrough
    BUILTINS["test.id_sink"] = IdSink
    manifest = PipelineManifest.model_validate({
        "metadata": {"name": "zero-copy"},
        "runtime": {"engine": "unified"},
        "nodes": {
            "source": {"uses": "test.array_source"},
            "pass": {"uses": "test.pass"},
            "sink": {"uses": "test.id_sink"},
        },
        "edges": [
            {"from": "source.frame", "to": "pass.frame"},
            {"from": "pass.frame", "to": "sink.frame"},
        ],
    })
    path = tmp_path / "pipeline.yaml"
    path.write_text("metadata: {name: unused}\nnodes: {}\nedges: []\n")
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    source = runtime.nodes["source"].node
    sink = runtime.nodes["sink"].node
    report = asyncio.run(runtime.run())
    assert report["status"] == "completed"
    assert report["native_queue"] is True
    assert sink.payload_ids == [id(source.frame)]


def test_native_queue_handles_backpressure() -> None:
    from nodrix._native_queue import BoundedQueue
    import threading

    queue = BoundedQueue(8, "block")
    received = []

    def producer():
        for value in range(5000):
            assert queue.put(value)
        queue.put_control("done")

    def consumer():
        while True:
            value = queue.get()
            if value == "done":
                return
            received.append(value)

    a = threading.Thread(target=producer)
    b = threading.Thread(target=consumer)
    a.start(); b.start()
    a.join(timeout=5); b.join(timeout=5)
    assert not a.is_alive() and not b.is_alive()
    assert received == list(range(5000))


def test_hybrid_runtime_keeps_async_node_compatibility(tmp_path: Path) -> None:
    class AsyncPass(Node):
        input_types = {"input": "core.object"}
        output_types = {"output": "core.object"}

        async def process(self, inputs):
            await asyncio.sleep(0)
            return {"output": inputs["input"]}

    BUILTINS["test.async_pass"] = AsyncPass
    manifest = PipelineManifest.model_validate({
        "metadata": {"name": "async-compatibility"},
        "runtime": {"engine": "unified"},
        "nodes": {
            "source": {"uses": "core.synthetic_source", "parameters": {"count": 5}},
            "async": {"uses": "test.async_pass"},
            "sink": {"uses": "core.counter_sink"},
        },
        "edges": [
            {"from": "source.output", "to": "async.input"},
            {"from": "async.output", "to": "sink.input"},
        ],
    })
    path = tmp_path / "pipeline.yaml"
    path.write_text("metadata: {name: unused}\nnodes: {}\nedges: []\n")
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    report = asyncio.run(runtime.run())
    assert report["nodes"]["async"]["messages"] == 5
