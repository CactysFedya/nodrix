from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import yaml

from nodrix import ManagedBuffer, Message, MemoryRequirement, MemoryType, plan_memory
from nodrix.cv_types import Tensor
from nodrix.device import device_doctor, dmabuf_from_fds
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.manifest import load_manifest
from nodrix.node import NodeContext
from nodrix.process_host import ProcessNodeProxy
from nodrix.project_templates import create_project


def _write_worker(path: Path, body: str, class_name: str = "Worker") -> str:
    path.write_text(body, encoding="utf-8")
    return f"{path}:{class_name}"


def test_tensor_dlpack_roundtrip_is_zero_copy() -> None:
    source = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    tensor = Tensor.from_dlpack(source)
    assert tensor.buffer.memory_type == MemoryType.CPU
    restored = np.from_dlpack(tensor)
    assert np.shares_memory(source, restored)
    assert np.array_equal(source, restored)


def test_device_only_buffer_refuses_hidden_cpu_copy() -> None:
    class FakeCuda:
        def __dlpack_device__(self):
            return 2, 0
        def __dlpack__(self, stream=None):
            return object()

    buffer = ManagedBuffer.from_dlpack(FakeCuda(), nbytes=4096)
    assert buffer.memory_type == MemoryType.CUDA
    assert not buffer.host_accessible
    with pytest.raises(TypeError, match="device-only"):
        buffer.memoryview()


def test_dmabuf_descriptor_duplicates_file_descriptor() -> None:
    if not hasattr(os, "memfd_create"):
        pytest.skip("Linux memfd is unavailable")
    fd = os.memfd_create("nodrix-dmabuf-test")
    try:
        os.ftruncate(fd, 4096)
        handle = dmabuf_from_fds([fd], lengths=[4096], width=64, height=64, format="gray8")
        assert handle.planes[0].fd != fd
        assert handle.nbytes == 4096
        buffer = ManagedBuffer.from_dmabuf(handle)
        assert buffer.memory_type == MemoryType.DMA_BUF
        assert buffer.nbytes == 4096
        assert not buffer.host_accessible
        buffer.release()
    finally:
        os.close(fd)


def test_memory_planner_exposes_transfers() -> None:
    direct = plan_memory(MemoryRequirement(("cuda",)), MemoryRequirement(("cuda",)))
    assert direct.copies == 0
    upload = plan_memory(MemoryRequirement(("cpu",)), MemoryRequirement(("cuda",)))
    assert upload.copies == 1
    assert upload.transfers == ("host_to_cuda",)
    forbidden = plan_memory(
        MemoryRequirement(("cuda",)), MemoryRequirement(("dma_buf",)), allow_copy=False
    )
    assert not forbidden.runtime_supported


def test_isolated_node_executor_owned_output_has_zero_copy(tmp_path: Path) -> None:
    reference = _write_worker(tmp_path / "output_worker.py", '''
from nodrix import Message, Node
class Worker(Node):
    input_types = {"input": "core.object"}
    output_types = {"output": "core.bytes"}
    output_memory = {"output": "shared"}
    def process(self, inputs):
        output = self.allocate_output(262144)
        output.memoryview()[:4] = b"NDRX"
        output.readonly = True
        return {"output": Message(type="core.bytes", payload=output, sequence=inputs["input"].sequence)}
''')
    proxy = ProcessNodeProxy(
        name="worker", uses=reference, base_dir=tmp_path, parameters={},
        input_types={"input": "core.object"}, output_types={"output": "core.bytes"},
        block_size=524288, capacity=2, output_block_size=524288, output_capacity=2,
        threshold=1024, failure_policy="stop_pipeline", max_restarts=0,
        backoff_ms=0, cpu_affinity=[],
    )
    proxy.open(NodeContext("worker", tmp_path, tmp_path, "offline"))
    output = proxy.process({"input": Message(type="core.object", payload={"value": 1}, sequence=7)})
    assert output is not None
    assert bytes(output["output"].payload.memoryview()[:4]) == b"NDRX"
    report = proxy.transport_report()
    assert report["output_payload_copies"] == 0
    assert report["zero_copy_outputs"] == 1
    output["output"].payload.release()
    proxy.close()


def test_process_isolated_source_and_device_template(tmp_path: Path) -> None:
    project = tmp_path / "device-project"
    create_project(project, "device")
    runtime = HybridPipelineRuntime(load_manifest(project / "pipeline.yaml"), project / "pipeline.yaml")
    runtime.build()
    description = runtime.describe()
    plan = description["edges"][0]["memory"]
    assert plan["selected_memory"] == "shared"
    assert plan["planned_copies"] == 0
    report = runtime.run_sync()
    assert report["status"] == "completed"
    assert report["nodes"]["source"]["transport"]["output_payload_copies"] == 0
    assert report["nodes"]["source"]["transport"]["zero_copy_outputs"] == 32


def test_manifest_can_forbid_implicit_memory_copies(tmp_path: Path) -> None:
    source = tmp_path / "nodes.py"
    source.write_text('''
from nodrix import SourceNode, SinkNode
class Source(SourceNode):
    output_types={"out":"core.bytes"}
    output_memory={"out":"cuda"}
    def produce(self):
        return iter(())
class Sink(SinkNode):
    input_types={"in":"core.bytes"}
    input_memory={"in":"cpu"}
    def process(self, inputs):
        pass
''', encoding="utf-8")
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(yaml.safe_dump({
        "metadata": {"name": "memory-error"},
        "runtime": {"memory": {"forbid_implicit_copies": True}},
        "nodes": {
            "source": {"uses": f"{source}:Source"},
            "sink": {"uses": f"{source}:Sink"},
        },
        "edges": [{"from": "source.out", "to": "sink.in"}],
    }, sort_keys=False), encoding="utf-8")
    with pytest.raises(Exception, match="Unsupported memory path"):
        HybridPipelineRuntime(load_manifest(pipeline), pipeline).build()


def test_native_device_doctor_is_available() -> None:
    info = device_doctor()
    assert info["native_extension"] is True
    assert info["dma_buf_descriptor"] is True


def test_device_doctor_cli_json():
    from typer.testing import CliRunner
    from nodrix.cli import app

    result = CliRunner().invoke(app, ["device", "doctor", "--json"])
    assert result.exit_code == 0, result.output
    assert '"native_extension"' in result.output
