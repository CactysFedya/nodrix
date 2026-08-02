from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import threading
import time

import pytest
import yaml

from nodrix import Message, SinkNode, SourceNode
from nodrix.cv_types import ManagedBuffer, MemoryType, TypeRegistry
from nodrix.errors import ManifestError, RuntimeGraphError
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.manifest import PipelineManifest, load_manifest
from nodrix.process_host import _decode_ipc_message, _encode_ipc_message
from nodrix.queueing import PythonBoundedQueue
from nodrix.recording import AsyncNdrxWriter, NdrxReader
from nodrix.registry import BUILTINS
from nodrix.shared_memory import SharedBufferDescriptor, descriptor_for_buffer


class _Lease:
    def __init__(self, descriptor: SharedBufferDescriptor | None = None) -> None:
        self.descriptor = descriptor
        self.releases = 0

    def release(self) -> None:
        self.releases += 1


def test_fanout_buffers_release_independently_without_copy() -> None:
    storage = bytearray(b"nodrix")
    lease = _Lease()
    buffer = ManagedBuffer.wrap(storage, readonly=False)
    buffer.lease = lease
    message = Message("core.bytes", buffer)

    first = message.fork()
    second = message.fork()
    assert first.payload.owner is storage
    assert second.payload.owner is storage
    assert first.payload.readonly is True

    first.payload.release()
    assert bytes(second.payload.memoryview()) == b"nodrix"
    assert lease.releases == 0
    buffer.release()
    assert lease.releases == 0
    second.payload.release()
    assert lease.releases == 1


def test_shared_descriptor_survives_buffer_fanout() -> None:
    descriptor = SharedBufferDescriptor(
        "nodrix-descriptor",
        6,
        readonly=True,
        generation=3,
    )
    buffer = ManagedBuffer(
        owner=bytearray(b"nodrix"),
        readonly=True,
        memory_type=MemoryType.SHARED,
        lease=_Lease(descriptor),
    )
    delivery = Message("core.bytes", buffer).fork()
    assert descriptor_for_buffer(delivery.payload) == descriptor
    buffer.release()
    delivery.payload.release()


def test_message_envelope_and_nested_metadata_are_immutable() -> None:
    payload = {"items": [1]}
    message = Message(
        "core.object",
        payload,
        metadata={"nested": {"items": [1]}},
    )
    payload["items"].append(2)
    assert message.payload["items"] == [1, 2]
    assert message.metadata["nested"]["items"] == (1,)
    with pytest.raises(TypeError):
        message.metadata["nested"]["items"] += (2,)

    delivery = message.fork()
    delivery.payload["items"].append(3)
    assert message.payload["items"] == [1, 2]


def test_python_queue_close_unblocks_blocked_producer_and_consumer() -> None:
    queue = PythonBoundedQueue(1, "block")
    assert queue.put("first")
    producer_result: list[bool] = []
    producer = threading.Thread(
        target=lambda: producer_result.append(queue.put("second"))
    )
    producer.start()
    time.sleep(0.02)
    queue.close()
    producer.join(timeout=1.0)
    assert producer_result == [False]
    assert queue.get() == "first"
    assert queue.get() is None

    empty = PythonBoundedQueue(1, "block")
    consumer_result: list[object] = []
    consumer = threading.Thread(target=lambda: consumer_result.append(empty.get()))
    consumer.start()
    time.sleep(0.02)
    empty.close()
    consumer.join(timeout=1.0)
    assert consumer_result == [None]


class _DynamicSource(SourceNode):
    output_types = {"output": "core.any"}

    def produce(self):
        yield {"output": Message("core.object", {"wrong": True})}


class _FrameSink(SinkNode):
    input_types = {"input": "vision.frame"}

    def process(self, inputs):
        raise AssertionError("wrongly typed message reached the sink")


def test_dynamic_core_any_is_checked_at_the_target_edge(tmp_path: Path) -> None:
    BUILTINS.update(
        {
            "test.v220.dynamic_source": _DynamicSource,
            "test.v220.frame_sink": _FrameSink,
        }
    )
    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "dynamic-type-check"},
            "nodes": {
                "source": {"uses": "test.v220.dynamic_source"},
                "sink": {"uses": "test.v220.frame_sink"},
            },
            "edges": [{"from": "source.output", "to": "sink.input"}],
        }
    )
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(manifest.model_dump(by_alias=True)))
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    with pytest.raises(RuntimeGraphError, match="cannot enter"):
        runtime.run_sync()


def _encoded_bytes() -> dict[str, object]:
    encoded, leases, _ = _encode_ipc_message(
        Message("core.bytes", b"data"),
        pool=None,
        threshold=1024,
    )
    assert leases == []
    return encoded


def test_ipc_rejects_invalid_slot_index_and_stale_generation() -> None:
    slot_descriptor = SharedBufferDescriptor(
        "nodrix-test-slot",
        16,
        readonly=False,
        generation=7,
    )
    slot = ManagedBuffer(
        owner=bytearray(16),
        readonly=False,
        memory_type=MemoryType.SHARED,
        lease=_Lease(slot_descriptor),
    )
    invalid_index = _encoded_bytes()
    invalid_index["payload"] = {
        "shared": asdict(slot_descriptor),
        "slot": 2,
        "unlink": False,
    }
    with pytest.raises(ValueError, match="slot index"):
        _decode_ipc_message(invalid_index, output_slot_buffers=[slot])

    stale = _encoded_bytes()
    stale_descriptor = SharedBufferDescriptor(
        slot_descriptor.name,
        4,
        readonly=True,
        generation=6,
    )
    stale["payload"] = {
        "shared": asdict(stale_descriptor),
        "slot": 0,
        "unlink": False,
    }
    with pytest.raises(ValueError, match="generation"):
        _decode_ipc_message(stale, output_slot_buffers=[slot])
    slot.release()


def test_compact_manifest_and_fragment_overrides_reject_typos(
    tmp_path: Path,
) -> None:
    compact = tmp_path / "compact.yaml"
    compact.write_text(
        "name: typo\nnods: {}\nnodes:\n  source:\n    use: core.synthetic_source\n"
        "flow: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="Unknown compact manifest fields"):
        load_manifest(compact)

    fragment = tmp_path / "fragment.yaml"
    fragment.write_text(
        "nodes:\n  worker:\n    use: core.identity\n"
        "parameters:\n  missing.value: 1\n",
        encoding="utf-8",
    )
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        "metadata: {name: fragment-typo}\n"
        "nodes: {source: {uses: core.synthetic_source}}\n"
        "edges: []\n"
        "fragments:\n  stage:\n    uses: fragment.yaml\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="unknown node"):
        load_manifest(pipeline)


def test_configured_plugin_security_is_enforced_by_runtime_api(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "plugin.py"
    plugin.write_text(
        "from nodrix import SourceNode\n"
        "class Demo(SourceNode):\n output_types={'out':'core.object'}\n"
        " def produce(self): return iter(())\n",
        encoding="utf-8",
    )
    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "secure-api"},
            "security": {"require_signed_plugins": True},
            "nodes": {"source": {"uses": f"{plugin}:Demo"}},
            "edges": [],
        }
    )
    path = tmp_path / "secure.yaml"
    path.write_text(yaml.safe_dump(manifest.model_dump(by_alias=True)))
    runtime = HybridPipelineRuntime(manifest, path)
    with pytest.raises(RuntimeGraphError, match="P504"):
        runtime.build()


def test_async_recording_drains_before_close(tmp_path: Path) -> None:
    path = tmp_path / "events.ndrx"
    writer = AsyncNdrxWriter(
        path,
        durable=False,
        checkpoint_records=2,
        queue_capacity=2,
    )
    for sequence in range(5):
        writer.write(Message("core.object", {"value": sequence}, sequence=sequence))
    writer.close()
    assert writer.report()["messages"] == 5
    with NdrxReader(path) as reader:
        assert [message.sequence for _, message in reader.iter_messages()] == list(
            range(5)
        )


def test_type_registry_registration_is_thread_safe() -> None:
    registry = TypeRegistry()
    threads = [
        threading.Thread(target=registry.register, args=(f"test.type.{index}",))
        for index in range(32)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(registry.names()) == 32
