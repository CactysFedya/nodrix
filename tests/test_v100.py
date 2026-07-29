from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest
import yaml

from nodrix import Message, Node, SinkNode, SourceNode
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.lockfile import verify_lock, write_lock
from nodrix.manifest import PipelineManifest
from nodrix.packages import build_package, install_package, resolve_package_node
from nodrix.registry import BUILTINS, load_node_class
from nodrix.streams import StreamClient, StreamServer
from nodrix.validation import validate_production


class Source(SourceNode):
    output_types = {"out": "core.object"}

    def produce(self):
        for value in range(3):
            yield {"out": Message("core.object", {"value": value}, sequence=value)}


class Pass(Node):
    input_types = {"in": "core.object"}
    output_types = {"out": "core.object"}

    def process(self, inputs):
        return {"out": inputs["in"]}


class Sink(SinkNode):
    input_types = {"in": "core.object"}

    def process(self, inputs):
        return None


def _manifest() -> PipelineManifest:
    BUILTINS.update({"v100.source": Source, "v100.pass": Pass, "v100.sink": Sink})
    return PipelineManifest.model_validate({
        "metadata": {"name": "production"},
        "runtime": {"metrics": {"enabled": True, "interval_ms": 100}},
        "nodes": {
            "source": {"uses": "v100.source"},
            "pass": {"uses": "v100.pass"},
            "sink": {"uses": "v100.sink"},
        },
        "edges": [
            {"from": "source.out", "to": "pass.in"},
            {"from": "pass.out", "to": "sink.in"},
        ],
    })


def test_production_run_artifacts_and_lifecycle(tmp_path: Path) -> None:
    manifest_path = tmp_path / "pipeline.yaml"
    manifest_path.write_text(yaml.safe_dump(_manifest().model_dump(by_alias=True)), encoding="utf-8")
    runtime = HybridPipelineRuntime(_manifest(), manifest_path, run_root=tmp_path / "runs")
    runtime.build()
    report = asyncio.run(runtime.run())
    assert report["status"] == "completed"
    for stats in report["nodes"].values():
        assert stats["health"]["state"] == "stopped"
        assert stats["health"]["ready"] is False
    run_dir = Path(report["run_dir"])
    for name in (
        "manifest.yaml", "resolved-manifest.yaml", "nodrix.lock", "runtime.json",
        "environment.json", "run.json", "summary.json",
    ):
        assert (run_dir / name).is_file(), name
    assert (run_dir / "logs").is_dir()
    assert (run_dir / "outputs").is_dir()


def test_lock_detects_changes(tmp_path: Path) -> None:
    manifest = tmp_path / "pipeline.yaml"
    node = tmp_path / "nodes.py"
    node.write_text("VALUE = 1\n", encoding="utf-8")
    manifest.write_text(yaml.safe_dump({
        "metadata": {"name": "locked"},
        "nodes": {"source": {"uses": "./nodes.py:Source"}},
        "edges": [],
    }), encoding="utf-8")
    lock_path = write_lock(manifest)
    assert verify_lock(manifest, lock_path)["ok"] is True
    node.write_text("VALUE = 2\n", encoding="utf-8")
    result = verify_lock(manifest, lock_path)
    assert result["ok"] is False
    assert any("checksum changed: nodes.py" in item for item in result["issues"])


def test_local_package_build_install_and_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NODRIX_HOME", str(tmp_path / "home"))
    package = tmp_path / "package"
    (package / "python").mkdir(parents=True)
    (package / "python" / "node.py").write_text(
        "from nodrix import Node\nclass Demo(Node):\n"
        " input_types={'input':'core.any'}\n output_types={'output':'core.any'}\n"
        " def process(self, inputs): return {'output': inputs['input']}\n",
        encoding="utf-8",
    )
    (package / "nodrix.package.yaml").write_text(yaml.safe_dump({
        "name": "demo-pack",
        "version": "1.0.0",
        "nodrix": ">=1.0,<2.0",
        "nodes": {"demo": {"python": "python/node.py:Demo"}},
    }), encoding="utf-8")
    archive = build_package(package, tmp_path / "demo.ndpkg")
    installed = install_package(archive)
    assert installed["name"] == "demo-pack"
    resolved = resolve_package_node("demo-pack/demo")
    assert resolved.endswith("python/node.py:Demo")
    cls = load_node_class("demo-pack/demo")
    assert issubclass(cls, Node)


def test_token_stream_rejects_unauthorized_and_accepts_token() -> None:
    server = StreamServer(host="127.0.0.1", port=0)
    server.register("/secure", "core.object", access_mode="token", token="secret")
    server.start()
    uri = f"nodrix://127.0.0.1:{server.port}/secure"
    bad = StreamClient(uri, token="wrong")
    with pytest.raises(LookupError):
        bad.connect()
    good = StreamClient(uri, token="secret")
    good.connect()
    server.publish("/secure", Message("core.object", {"ok": True}, sequence=1))
    received = good.receive()
    assert received.payload == {"ok": True}
    good.close()
    server.close()


def test_strict_validation_requires_auth_for_lan_export(tmp_path: Path) -> None:
    raw = _manifest().model_dump(by_alias=True)
    raw["streams"] = {
        "bind_host": "0.0.0.0",
        "exports": [{"name": "/open", "from": "source.out"}],
    }
    manifest = PipelineManifest.model_validate(raw)
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(manifest.model_dump(by_alias=True)), encoding="utf-8")
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    issues = validate_production(manifest, runtime.describe(), strict=True)
    assert any(item.code == "S101" and item.severity == "error" for item in issues)


def test_strict_validation_rejects_inline_stream_token(tmp_path: Path) -> None:
    raw = _manifest().model_dump(by_alias=True)
    raw["streams"] = {
        "bind_host": "0.0.0.0",
        "exports": [{
            "name": "/secure",
            "from": "source.out",
            "access": {"mode": "token", "token": "inline-secret"},
        }],
    }
    manifest = PipelineManifest.model_validate(raw)
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(manifest.model_dump(by_alias=True)), encoding="utf-8")
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    issues = validate_production(manifest, runtime.describe(), strict=True)
    assert any(item.code == "S102" and item.severity == "error" for item in issues)


def test_token_env_is_not_required_for_static_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _manifest().model_dump(by_alias=True)
    raw["streams"] = {
        "bind_host": "0.0.0.0",
        "exports": [{
            "name": "/secure",
            "from": "source.out",
            "access": {"mode": "token", "token_env": "NODRIX_TEST_TOKEN"},
        }],
    }
    manifest = PipelineManifest.model_validate(raw)
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(manifest.model_dump(by_alias=True)), encoding="utf-8")
    monkeypatch.delenv("NODRIX_TEST_TOKEN", raising=False)
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    assert runtime.describe()["streams"][0]["token_env"] == "NODRIX_TEST_TOKEN"
    assert not validate_production(manifest, runtime.describe(), strict=True)
    with pytest.raises(Exception, match="NODRIX_TEST_TOKEN"):
        runtime.run_sync()


def test_watchdog_restarts_hung_isolated_node(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    module = tmp_path / "hung.py"
    module.write_text(
        "from pathlib import Path\nimport time\nfrom nodrix import Node\n"
        "class HungOnce(Node):\n"
        " input_types={'input':'core.object'}\n output_types={'output':'core.object'}\n"
        " def process(self, inputs):\n"
        "  marker=Path(self.parameters['marker'])\n"
        "  if not marker.exists(): marker.write_text('1'); time.sleep(5)\n"
        "  return {'output': inputs['input']}\n",
        encoding="utf-8",
    )
    BUILTINS.update({"v100.source": Source, "v100.sink": Sink})
    manifest = PipelineManifest.model_validate({
        "metadata": {"name": "watchdog"},
        "runtime": {"shutdown": {"timeout_ms": 3000}},
        "nodes": {
            "source": {"uses": "v100.source"},
            "worker": {
                "uses": f"{module}:HungOnce",
                "parameters": {"marker": str(marker)},
                "execution": {"isolation": "process"},
                "failure": {"policy": "restart", "max_restarts": 3, "backoff_ms": 10},
                "health": {"timeout_ms": 200, "on_timeout": "restart"},
            },
            "sink": {"uses": "v100.sink"},
        },
        "edges": [
            {"from": "source.out", "to": "worker.input"},
            {"from": "worker.output", "to": "sink.in"},
        ],
    })
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(manifest.model_dump(by_alias=True)), encoding="utf-8")
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    report = runtime.run_sync()
    assert report["status"] == "completed"
    assert report["nodes"]["worker"]["transport"]["restarts"] >= 1
    assert report["nodes"]["sink"]["messages"] == 3


class Flaky(Node):
    input_types = {"input": "core.object"}
    output_types = {"output": "core.object"}

    def process(self, inputs):
        message = inputs["input"]
        if message.sequence == 1:
            raise ValueError("expected test failure")
        return {"output": message}


def test_skip_message_failure_policy(tmp_path: Path) -> None:
    BUILTINS.update({"v100.source": Source, "v100.flaky": Flaky, "v100.sink": Sink})
    manifest = PipelineManifest.model_validate({
        "metadata": {"name": "skip"},
        "nodes": {
            "source": {"uses": "v100.source"},
            "flaky": {"uses": "v100.flaky", "failure": {"policy": "skip_message"}},
            "sink": {"uses": "v100.sink"},
        },
        "edges": [
            {"from": "source.out", "to": "flaky.input"},
            {"from": "flaky.output", "to": "sink.in"},
        ],
    })
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(manifest.model_dump(by_alias=True)), encoding="utf-8")
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    report = runtime.run_sync()
    assert report["status"] == "completed"
    assert report["nodes"]["flaky"]["errors"] == 1
    assert report["nodes"]["sink"]["messages"] == 2


def test_resolved_manifest_redacts_stream_token(tmp_path: Path) -> None:
    raw = _manifest().model_dump(by_alias=True)
    raw["streams"] = {
        "bind_host": "127.0.0.1",
        "exports": [{
            "name": "/secure", "from": "source.out",
            "access": {"mode": "token", "token": "top-secret"},
        }],
    }
    manifest = PipelineManifest.model_validate(raw)
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    report = runtime.run_sync()
    run_dir = Path(report["run_dir"])
    source_copy = (run_dir / "manifest.yaml").read_text(encoding="utf-8")
    resolved = (run_dir / "resolved-manifest.yaml").read_text(encoding="utf-8")
    assert "top-secret" not in source_copy
    assert "REDACTED" in source_copy
    assert "top-secret" not in resolved
    assert "REDACTED" in resolved
    assert all("token" not in stream for stream in runtime.describe()["streams"])
