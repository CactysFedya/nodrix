from __future__ import annotations

import asyncio
from pathlib import Path
import zipfile
from typing import ClassVar

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

import nodrix
from nodrix.cli import app
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.lifecycle import LifecycleState, LifecycleTracker
from nodrix.manifest import PipelineManifest, load_manifest, load_manifest_details
from nodrix.messages import Message
from nodrix.migration import migrate_manifest
from nodrix.node import Node, NodeContext
from nodrix.observability import EventTracer
from nodrix.packages import build_package, verify_package
from nodrix.project_templates import create_project
from nodrix.recording import NdrxReader
from nodrix.registry import BUILTINS, load_node_class
from nodrix.validation import validate_production


def _v2(
    *,
    name: str = "v2-pipeline",
    nodes: dict | None = None,
    edges: list[dict] | None = None,
    **sections: object,
) -> dict:
    document = {
        "apiVersion": "nodrix.dev/v2",
        "kind": "Pipeline",
        "metadata": {"name": name},
        "runtime": {"engine": "unified"},
        "nodes": nodes
        or {
            "source": {
                "uses": "core.synthetic_source",
                "parameters": {"count": 1},
            }
        },
        "fragments": {},
        "edges": edges or [],
        "streams": {},
        "recording": {},
        "security": {},
        "placement": {},
    }
    document.update(sections)
    return document


def _write_manifest(path: Path, document: dict) -> Path:
    path.write_text(
        yaml.safe_dump(document, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_v200_version_and_stable_public_api() -> None:
    assert nodrix.__version__ == "2.8.0"
    assert nodrix.PipelineManifest is PipelineManifest
    assert nodrix.load_manifest is load_manifest
    assert issubclass(nodrix.ManifestError, nodrix.NodrixError)
    assert nodrix.Message is Message


def test_manifest_v2_requires_all_sections_and_explicit_engine() -> None:
    missing = _v2()
    missing.pop("security")
    with pytest.raises(ValidationError, match="explicit sections: security"):
        PipelineManifest.model_validate(missing)

    implicit = _v2(runtime={})
    with pytest.raises(ValidationError, match="requires runtime.engine"):
        PipelineManifest.model_validate(implicit)

    manifest = PipelineManifest.model_validate(_v2())
    assert manifest.api_version == "nodrix.dev/v2"
    assert manifest.runtime.engine == "unified"

    legacy_policy = _v2()
    legacy_policy["nodes"]["source"]["failure"] = {"policy": "restart"}
    with pytest.raises(ValidationError, match="restart_node/isolate_branch"):
        PipelineManifest.model_validate(legacy_policy)


def test_manifest_v1_remains_loadable() -> None:
    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "legacy"},
            "nodes": {"source": {"uses": "core.synthetic_source"}},
            "edges": [],
        }
    )
    assert manifest.api_version == "plyctl.dev/v1"
    assert manifest.runtime.engine == "auto"


def test_migration_preserves_source_and_in_place_creates_backup(
    tmp_path: Path,
) -> None:
    source = _write_manifest(
        tmp_path / "pipeline.yaml",
        {
            "metadata": {"name": "legacy"},
            "runtime": {"engine": "auto"},
            "nodes": {
                "source": {
                    "uses": "core.synthetic_source",
                    "failure": {"policy": "restart"},
                }
            },
            "edges": [],
        },
    )
    original = source.read_bytes()
    result = migrate_manifest(source)
    destination = Path(result["destination"])
    assert source.read_bytes() == original
    assert destination.name == "pipeline.v2.yaml"
    assert load_manifest(destination).api_version == "plyctl.dev/v2"
    assert load_manifest(destination).nodes["source"].failure.policy == "restart_node"

    in_place = migrate_manifest(source, in_place=True)
    assert Path(in_place["backup"]).read_bytes() == original
    assert load_manifest(source).api_version == "plyctl.dev/v2"


def test_fragment_expansion_rewrites_public_ports(tmp_path: Path) -> None:
    fragment = {
        "version": "1.2.0",
        "description": "Reusable identity stage",
        "inputs": {"input": "processor.input"},
        "outputs": {"output": "processor.output"},
        "nodes": {
            "processor": {
                "uses": "core.identity",
                "parameters": {},
            }
        },
        "edges": [],
        "hardware_requirements": [],
    }
    _write_manifest(tmp_path / "identity.fragment.yaml", fragment)
    pipeline = _v2(
        nodes={
            "source": {
                "uses": "core.synthetic_source",
                "parameters": {"count": 1},
            },
            "sink": {"uses": "core.counter_sink"},
        },
        edges=[
            {"from": "source.output", "to": "middle.input"},
            {"from": "middle.output", "to": "sink.input"},
        ],
        fragments={
            "middle": {
                "uses": "identity.fragment.yaml",
                "parameters": {"processor.marker": "expanded"},
            }
        },
    )
    path = _write_manifest(tmp_path / "pipeline.yaml", pipeline)
    details = load_manifest_details(path)
    assert "middle__processor" in details.manifest.nodes
    assert (
        details.manifest.nodes["middle__processor"].parameters["marker"]
        == "expanded"
    )
    assert [
        (edge.source, edge.target)
        for edge in details.manifest.edges
    ] == [
        ("source.output", "middle__processor.input"),
        ("middle__processor.output", "sink.input"),
    ]


def test_fragment_block_override_is_explicit(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path / "default.block.yaml",
        {"use": "core.identity"},
    )
    _write_manifest(
        tmp_path / "alternate.block.yaml",
        {"use": "core.delay", "milliseconds": 0},
    )
    _write_manifest(
        tmp_path / "stage.fragment.yaml",
        {
            "inputs": {"input": "worker.input"},
            "outputs": {"output": "worker.output"},
            "blocks": {"worker": "default.block.yaml"},
        },
    )
    path = _write_manifest(
        tmp_path / "pipeline.yaml",
        _v2(
            nodes={
                "source": {"uses": "core.synthetic_source"},
                "sink": {"uses": "core.counter_sink"},
            },
            fragments={
                "stage": {
                    "uses": "stage.fragment.yaml",
                    "blocks": {"worker": "alternate.block.yaml"},
                }
            },
            edges=[
                {"from": "source.output", "to": "stage.input"},
                {"from": "stage.output", "to": "sink.input"},
            ],
        ),
    )
    manifest = load_manifest(path)
    assert manifest.nodes["stage__worker"].uses == "core.delay"
    assert manifest.nodes["stage__worker"].parameters["milliseconds"] == 0


def test_lifecycle_has_stable_states_reason_and_timestamp() -> None:
    tracker = LifecycleTracker()
    created = tracker.snapshot()
    tracker.transition(LifecycleState.CONFIGURING, reason="loading model")
    configuring = tracker.snapshot()
    tracker.transition(LifecycleState.READY)
    ready = tracker.snapshot()
    assert configuring.state == "configuring"
    assert configuring.state_reason == "loading model"
    assert configuring.state_timestamp_ns >= created.state_timestamp_ns
    assert ready.state == "ready"
    assert ready.ready is True


def test_automatic_recording_adds_correlation_metadata(tmp_path: Path) -> None:
    manifest = PipelineManifest.model_validate(
        _v2(
            name="recorded",
            nodes={
                "source": {
                    "uses": "core.synthetic_source",
                    "parameters": {"count": 3},
                },
                "sink": {"uses": "core.counter_sink"},
            },
            edges=[{"from": "source.output", "to": "sink.input"}],
            recording={
                "enabled": True,
                "streams": ["source.output"],
                "checkpoint_records": 1,
            },
        )
    )
    source = _write_manifest(tmp_path / "pipeline.yaml", _v2())
    runtime = HybridPipelineRuntime(
        manifest,
        source,
        run_root=tmp_path / "runs",
    )
    runtime.build()
    report = asyncio.run(runtime.run())
    recording = Path(report["recording"]["path"])
    assert recording.is_file()
    with NdrxReader(recording) as reader:
        messages = [message for _, message in reader.iter_messages()]
    assert len(messages) == 3
    assert {message.pipeline_id for message in messages} == {"recorded"}
    assert {message.run_id for message in messages} == {
        Path(report["run_dir"]).name
    }
    assert {message.source_id for message in messages} == {"source.output"}


def test_fallback_node_retries_current_message(tmp_path: Path) -> None:
    class FailingNode(Node):
        input_types: ClassVar = {"input": "core.any"}
        output_types: ClassVar = {"output": "core.any"}

        def process(self, inputs):
            raise RuntimeError("injected primary failure")

    class FallbackNode(Node):
        input_types: ClassVar = {"input": "core.any"}
        output_types: ClassVar = {"output": "core.any"}

        def process(self, inputs):
            return {"output": inputs["input"]}

    BUILTINS["test.v200_failing"] = FailingNode
    BUILTINS["test.v200_fallback"] = FallbackNode
    manifest = PipelineManifest.model_validate(
        _v2(
            name="fallback",
            nodes={
                "source": {
                    "uses": "core.synthetic_source",
                    "parameters": {"count": 2},
                },
                "worker": {
                    "uses": "test.v200_failing",
                    "failure": {
                        "policy": "fallback_node",
                        "fallback_uses": "test.v200_fallback",
                    },
                },
                "sink": {"uses": "core.counter_sink"},
            },
            edges=[
                {"from": "source.output", "to": "worker.input"},
                {"from": "worker.output", "to": "sink.input"},
            ],
        )
    )
    source = _write_manifest(tmp_path / "pipeline.yaml", _v2())
    runtime = HybridPipelineRuntime(
        manifest,
        source,
        run_root=tmp_path / "runs",
    )
    runtime.build()
    report = asyncio.run(runtime.run())
    assert report["status"] == "completed"
    assert report["nodes"]["sink"]["messages"] == 2
    assert runtime.nodes["worker"].fallback_active is True
    assert report["nodes"]["worker"]["health"]["status"] == "degraded"
    assert (
        report["nodes"]["worker"]["runtime_info"]["fallback"]
        == "test.v200_fallback"
    )
    events = (Path(report["run_dir"]) / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"kind": "node_fallback"' in events


def test_production_gate_rejects_legacy_and_accepts_safe_v2(
    tmp_path: Path,
) -> None:
    legacy = PipelineManifest.model_validate(
        {
            "metadata": {"name": "legacy"},
            "nodes": {"source": {"uses": "core.synthetic_source"}},
            "edges": [],
        }
    )
    legacy_codes = {
        issue.code
        for issue in validate_production(
            legacy,
            {"edges": []},
            strict=True,
            production=True,
        )
    }
    assert {"P200", "P201", "P501"} <= legacy_codes

    debug = PipelineManifest.model_validate(
        _v2(
            runtime={
                "engine": "unified",
                "logging": {"level": "debug"},
            }
        )
    )
    assert "P505" in {
        issue.code
        for issue in validate_production(
            debug,
            {"edges": []},
            strict=True,
            production=True,
        )
    }

    safe_document = _v2(
        nodes={
            "source": {
                "uses": "core.synthetic_source",
                "parameters": {"count": 1},
                "health": {"timeout_ms": 1000},
            }
        }
    )
    path = _write_manifest(tmp_path / "safe.yaml", safe_document)
    runtime = HybridPipelineRuntime(
        load_manifest(path),
        path,
        run_root=tmp_path / "runs",
    )
    runtime.build()
    errors = [
        issue
        for issue in validate_production(
            runtime.manifest,
            runtime.describe(),
            strict=True,
            production=True,
        )
        if issue.severity == "error"
    ]
    assert errors == []


def test_package_checksums_and_ed25519_signature(tmp_path: Path) -> None:
    cryptography = pytest.importorskip("cryptography")
    del cryptography
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    package_root = tmp_path / "plugin"
    package_root.mkdir()
    _write_manifest(
        package_root / "nodrix.package.yaml",
        {
            "format": "nodrix-package/1",
            "name": "test-signed",
            "version": "1.0.0",
            "nodrix": ">=2.0,<3.0",
            "abi": 2,
            "platforms": ["any"],
            "hardware": [],
            "sandbox": "in_process",
            "nodes": {
                "identity": {
                    "python": "identity.py:Identity",
                }
            },
        },
    )
    (package_root / "identity.py").write_text(
        "from nodrix import Node\nclass Identity(Node):\n    pass\n",
        encoding="utf-8",
    )
    private = Ed25519PrivateKey.generate()
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    archive = build_package(
        package_root,
        tmp_path / "test-signed.ndpkg",
        signing_key=private_path,
    )
    verified = verify_package(
        archive,
        public_key=public_path,
        require_signature=True,
    )
    assert verified["signature_verified"] is True
    assert verified["checksums"] == "verified"

    tampered = tmp_path / "tampered.ndpkg"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(
        tampered,
        "w",
    ) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "identity.py":
                content += b"# tampered\n"
            target.writestr(item, content)
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_package(tampered, public_key=public_path)


def test_ros2_adapter_is_lazy_and_reports_missing_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_class = load_node_class("ros2.source")
    source = source_class(
        {
            "topic": "/camera",
            "message_type": "sensor_msgs.msg.Image",
        }
    )
    import nodrix.ros2_adapter as adapter

    original_import = adapter.importlib.import_module

    def controlled_import(name: str):
        if name == "rclpy":
            raise ModuleNotFoundError("rclpy")
        return original_import(name)

    monkeypatch.setattr(adapter.importlib, "import_module", controlled_import)
    context = NodeContext(
        name="ros-source",
        run_dir=tmp_path,
        project_dir=tmp_path,
        runtime_mode="offline",
    )
    with pytest.raises(RuntimeError, match="ROS 2 adapters require"):
        source.open(context)


def test_tracing_is_zero_cost_when_disabled_and_validates_otlp() -> None:
    tracer = EventTracer(
        enabled=False,
        exporter="none",
        endpoint=None,
        service_name="test",
    )
    tracer.emit("ignored", {"value": 1})
    tracer.close()
    with pytest.raises(ValidationError, match="tracing.endpoint"):
        PipelineManifest.model_validate(
            _v2(
                runtime={
                    "engine": "unified",
                    "tracing": {
                        "enabled": True,
                        "exporter": "otlp",
                    },
                }
            )
        )


def test_cli_surface_ci_matrix_and_generated_v2_template(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    for command in (["migrate", "--help"], ["fragment", "--help"], ["plugin", "--help"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output

    project = tmp_path / "generated"
    create_project(project, "core")
    generated = load_manifest(project / "pipeline.yaml")
    assert generated.api_version == "plyctl.dev/v2"

    root = Path(__file__).resolve().parents[1]
    ci_path = root / ".github/workflows/ci.yml"
    publish_path = root / ".github/workflows/publish.yml"
    if not ci_path.is_file() or not publish_path.is_file():
        return
    ci = ci_path.read_text(encoding="utf-8")
    publish = publish_path.read_text(
        encoding="utf-8"
    )
    assert "ubuntu-24.04-arm" in ci
    assert "macos-latest" in ci
    assert "windows-latest" in ci
    assert "windows-latest" in publish


def test_message_correlation_metadata_is_wire_stable() -> None:
    from nodrix.wire import decode_packet_parts, encode_message

    original = Message(
        "core.object",
        {"value": 1},
        sequence=7,
        pipeline_id="pipe",
        run_id="run",
        source_id="camera",
        trace_id="trace",
        span_id="span",
    )
    packet = encode_message(original)
    restored = decode_packet_parts(
        packet.header,
        packet.type_name,
        packet.metadata,
        b"".join(packet.payload_parts),
    )
    assert (
        restored.pipeline_id,
        restored.run_id,
        restored.source_id,
        restored.trace_id,
        restored.span_id,
    ) == ("pipe", "run", "camera", "trace", "span")
