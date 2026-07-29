from __future__ import annotations

import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading

from pydantic import ValidationError
import pytest
import yaml

import nodrix
from nodrix import Message, Node, SinkNode, SourceNode
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.lockfile import verify_lock, write_lock
from nodrix.manifest import PipelineManifest, load_manifest
from nodrix.registry import BUILTINS
from nodrix.streams import StreamClient, StreamServer


class OptionalSource(SourceNode):
    output_types = {"out": "core.object"}

    def produce(self):
        yield {"out": Message("core.object", {"ok": True}, sequence=0)}


class OptionalProcessor(Node):
    input_types = {"required": "core.object", "side": "core.object"}
    optional_inputs = frozenset({"side"})
    output_types = {"out": "core.object"}

    def process(self, inputs):
        assert "side" not in inputs
        return {"out": inputs["required"]}


class OptionalSink(SinkNode):
    input_types = {"in": "core.object"}

    def process(self, inputs):
        return None


def _minimal_manifest() -> dict[str, object]:
    return {
        "apiVersion": "nodrix.dev/v1",
        "kind": "Pipeline",
        "metadata": {"name": "v151"},
        "nodes": {"source": {"uses": "core.synthetic_source", "parameters": {"count": 1}}},
        "edges": [],
    }


def test_v151_version() -> None:
    assert nodrix.__version__ == "1.6.0"


def test_manifest_rejects_unknown_fields_and_api_versions() -> None:
    raw = _minimal_manifest()
    raw["unknown"] = True
    with pytest.raises(ValidationError):
        PipelineManifest.model_validate(raw)

    raw = _minimal_manifest()
    raw["apiVersion"] = "nodrix.dev/v999"
    with pytest.raises(ValidationError):
        PipelineManifest.model_validate(raw)


def test_declared_optional_input_may_be_unconnected(tmp_path: Path) -> None:
    BUILTINS.update(
        {
            "v151.source": OptionalSource,
            "v151.processor": OptionalProcessor,
            "v151.sink": OptionalSink,
        }
    )
    raw = {
        "metadata": {"name": "optional"},
        "nodes": {
            "source": {"uses": "v151.source"},
            "processor": {
                "uses": "v151.processor",
                "synchronization": {"optional_inputs": ["side"]},
            },
            "sink": {"uses": "v151.sink"},
        },
        "edges": [
            {"from": "source.out", "to": "processor.required"},
            {"from": "processor.out", "to": "sink.in"},
        ],
    }
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    runtime = HybridPipelineRuntime(load_manifest(path), path, run_root=tmp_path / "runs")
    runtime.build()
    assert runtime.run_sync()["status"] == "completed"


def test_core_node_loads_without_numpy() -> None:
    root = Path(__file__).parents[1]
    code = (
        "import sys\n"
        "sys.modules['numpy'] = None\n"
        "from nodrix.registry import load_node_class\n"
        "assert load_node_class('core.identity').__name__ == 'IdentityNode'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env={"PYTHONPATH": str(root / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_lock_detects_dependency_drift(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(_minimal_manifest()), encoding="utf-8")
    lock_path = write_lock(path)
    locked = json.loads(lock_path.read_text(encoding="utf-8"))
    locked["dependencies"]["nodrix-fake-dependency"] = "1.0"
    lock_path.write_text(json.dumps(locked), encoding="utf-8")
    result = verify_lock(path)
    assert result["ok"] is False
    assert any("missing locked dependency" in issue for issue in result["issues"])


def test_fragmented_handshake_header_is_received_exactly() -> None:
    reader, writer = socket.socketpair()
    request = {"protocol": "nodrix-stream/1", "action": "subscribe", "stream": "/test"}
    encoded = json.dumps(request).encode("utf-8")
    packet = struct.pack("!I", len(encoded)) + encoded
    result: list[dict[str, object]] = []

    thread = threading.Thread(target=lambda: result.append(StreamServer._receive_json(reader)))
    thread.start()
    for byte in packet:
        writer.sendall(bytes((byte,)))
    thread.join(timeout=2)
    reader.close()
    writer.close()

    assert not thread.is_alive()
    assert result == [request]


def test_stream_token_in_uri_is_rejected() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        StreamClient("nodrix://127.0.0.1:7420/test?token=secret")


def test_safe_network_defaults() -> None:
    manifest = PipelineManifest.model_validate(_minimal_manifest())
    assert manifest.streams.bind_host == "127.0.0.1"


def test_builtin_parameter_contract_rejects_missing_uri(tmp_path: Path) -> None:
    raw = {
        "metadata": {"name": "parameters"},
        "nodes": {"source": {"uses": "media.ffmpeg_source"}},
        "edges": [],
    }
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    runtime = HybridPipelineRuntime(load_manifest(path), path)
    with pytest.raises(ValueError, match="requires parameter 'uri'"):
        runtime.build()


def test_run_persists_events_and_resolved_plan(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(_minimal_manifest()), encoding="utf-8")
    runtime = HybridPipelineRuntime(load_manifest(path), path, run_root=tmp_path / "runs")
    report = runtime.run_sync()
    run_dir = Path(report["run_dir"])
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    plan = json.loads((run_dir / "resolved-plan.json").read_text(encoding="utf-8"))
    assert events[0]["kind"] == "pipeline_starting"
    assert events[-1]["kind"] == "pipeline_stopped"
    assert plan["engine"] == "unified"
    assert "source" in plan["runtime_info"]
