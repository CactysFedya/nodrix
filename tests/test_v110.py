from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from nodrix import Message, SinkNode, SourceNode
from nodrix.cli import app
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.manifest import load_manifest, load_manifest_details
from nodrix.media import select_encoder
from nodrix.metrics import prometheus_text
from nodrix.registry import BUILTINS


class Counter(SourceNode):
    output_types = {"out": "core.object"}

    def produce(self):
        for value in range(20):
            yield {"out": Message("core.object", {"value": value}, sequence=value)}


class Sink(SinkNode):
    input_types = {"in": "core.object"}

    def process(self, inputs):
        return None


def test_compact_manifest_profile_and_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RTSP_URL", "rtsp://camera/live")
    path = tmp_path / "pipeline.yaml"
    path.write_text(
        yaml.safe_dump({
            "name": "preview",
            "profile": "realtime-low-latency",
            "nodes": {
                "camera": {"use": "media.ffmpeg_source", "uri": "${RTSP_URL}"},
                "encoder": {"use": "media.ffmpeg_encoder"},
            },
            "flow": ["camera.frame -> encoder.frame"],
            "publish": {
                "/camera/h264": {"from": "encoder.encoded", "access": "token"},
            },
        }, sort_keys=False),
        encoding="utf-8",
    )
    manifest = load_manifest(path)
    assert manifest.metadata.name == "preview"
    assert manifest.runtime.profile == "realtime-low-latency"
    assert manifest.runtime.mode == "realtime"
    assert manifest.nodes["camera"].parameters["uri"] == "rtsp://camera/live"
    assert manifest.nodes["camera"].parameters["low_latency"] is True
    assert manifest.nodes["encoder"].parameters["encoder"] == "auto"
    assert manifest.edges[0].queue.policy == "latest"
    assert manifest.edges[0].queue.capacity == 1
    assert manifest.streams.listen_port == 7420
    assert manifest.streams.exports[0].access.token_env == "NODRIX_STREAM_TOKEN"


def test_cli_override_short_node_parameter_path(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump({
        "name": "override",
        "profile": "realtime-low-latency",
        "nodes": {
            "source": {"use": "core.synthetic_source", "count": 1},
            "sink": {"use": "core.counter_sink"},
        },
        "flow": ["source.output -> sink.input"],
    }), encoding="utf-8")
    details = load_manifest_details(path, overrides=["nodes.source.count=7", "runtime.metrics.interval_ms=250"])
    assert details.manifest.nodes["source"].parameters["count"] == 7
    assert details.manifest.runtime.metrics.interval_ms == 250
    assert details.sources["nodes.source.parameters.count"] == "CLI --set"


def test_config_cli_resolved_and_explain(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump({
        "name": "config",
        "profile": "maximum-throughput",
        "nodes": {
            "source": {"use": "core.synthetic_source", "count": 1},
            "sink": {"use": "core.counter_sink"},
        },
        "flow": ["source.output -> sink.input"],
    }), encoding="utf-8")
    runner = CliRunner()
    shown = runner.invoke(app, ["config", "show", str(path)])
    assert shown.exit_code == 0, shown.output
    assert "maximum-throughput" in shown.output
    explained = runner.invoke(app, ["config", "explain", "nodes.source.count", "--pipeline", str(path)])
    assert explained.exit_code == 0, explained.output
    assert "nodes.source.parameters.count" in explained.output


def test_runtime_resource_telemetry_and_prometheus(tmp_path: Path) -> None:
    BUILTINS.update({"v110.counter": Counter, "v110.sink": Sink})
    raw = {
        "metadata": {"name": "resources"},
        "runtime": {"metrics": {"enabled": False}},
        "nodes": {"source": {"uses": "v110.counter"}, "sink": {"uses": "v110.sink"}},
        "edges": [{"from": "source.out", "to": "sink.in"}],
    }
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    manifest = load_manifest(path)
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    report = asyncio.run(runtime.run())
    resources = report["nodes"]["sink"]["resources"]
    assert resources["scope"] == "executor_shared"
    assert "cpu_percent" in resources
    assert "executor_rss_bytes" in resources
    metrics = prometheus_text(report)
    assert "nodrix_node_cpu_percent" in metrics
    assert "nodrix_node_executor_rss_bytes" in metrics


def test_auto_encoder_selection_uses_first_passing_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    import nodrix.media as media

    media.select_encoder.cache_clear()
    monkeypatch.setattr(media, "_encoder_candidates", lambda codec: ["hardware", "libx264"])
    monkeypatch.setattr(media, "probe_encoder", lambda encoder, codec: (encoder == "libx264", "ok"))
    result = select_encoder("h264", "auto")
    assert result["selected"] == "libx264"
    assert len(result["attempts"]) == 2


def test_isolated_node_reports_exact_process_resources(tmp_path: Path) -> None:
    BUILTINS.update({"v110.counter": Counter, "v110.sink": Sink})
    module = tmp_path / "worker.py"
    module.write_text(
        "import time\nfrom nodrix import Node\n"
        "class Worker(Node):\n"
        " input_types={'in':'core.object'}\n output_types={'out':'core.object'}\n"
        " def process(self, inputs): time.sleep(0.02); return {'out': inputs['in']}\n",
        encoding="utf-8",
    )
    raw = {
        "metadata": {"name": "isolated-resources"},
        "runtime": {"metrics": {"enabled": True, "interval_ms": 100}},
        "nodes": {
            "source": {"uses": "v110.counter"},
            "worker": {"uses": f"{module}:Worker", "execution": {"isolation": "process"}},
            "sink": {"uses": "v110.sink"},
        },
        "edges": [
            {"from": "source.out", "to": "worker.in"},
            {"from": "worker.out", "to": "sink.in"},
        ],
    }
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    manifest = load_manifest(path)
    runtime = HybridPipelineRuntime(manifest, path, run_root=tmp_path / "runs")
    runtime.build()
    report = asyncio.run(runtime.run())
    resources = report["nodes"]["worker"]["resources"]
    assert resources["scope"] == "isolated_process"
    assert int(resources.get("pid", 0)) > 0
    assert int(resources.get("rss_bytes", 0)) > 0


def test_locked_run_rejects_runtime_overrides(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump({
        "metadata": {"name": "locked-conflict"},
        "nodes": {
            "source": {"uses": "core.synthetic_source", "parameters": {"count": 1}},
            "sink": {"uses": "core.counter_sink"},
        },
        "edges": [{"from": "source.output", "to": "sink.input"}],
    }), encoding="utf-8")
    result = CliRunner().invoke(app, ["run", str(path), "--locked", "--profile", "debug"])
    assert result.exit_code == 2
    assert "cannot be combined" in result.output


def test_final_report_includes_profile_and_system(tmp_path: Path) -> None:
    BUILTINS.update({"v110.counter": Counter, "v110.sink": Sink})
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump({
        "name": "report-profile",
        "profile": "maximum-throughput",
        "nodes": {
            "source": {"use": "v110.counter"},
            "sink": {"use": "v110.sink"},
        },
        "flow": ["source.out -> sink.in"],
    }), encoding="utf-8")
    runtime = HybridPipelineRuntime(load_manifest(path), path, run_root=tmp_path / "runs")
    runtime.build()
    report = asyncio.run(runtime.run())
    assert report["profile"] == "maximum-throughput"
    assert "memory_total_bytes" in report["system"]


def test_config_explain_scalar_has_no_yaml_document_marker(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump({
        "name": "explain-scalar",
        "nodes": {
            "source": {"use": "core.synthetic_source", "count": 3},
            "sink": {"use": "core.counter_sink"},
        },
        "flow": ["source.output -> sink.input"],
    }), encoding="utf-8")
    result = CliRunner().invoke(app, ["config", "explain", "nodes.source.count", "--pipeline", str(path)])
    assert result.exit_code == 0, result.output
    assert "Value: 3" in result.output
    assert "..." not in result.output


def test_viewer_publisher_metrics_summary_and_default_url() -> None:
    from nodrix.viewer import PublisherMetrics, _default_metrics_url

    assert _default_metrics_url("nodrix://192.168.1.50:7420/camera/front/h264") == "http://192.168.1.50:9464/metrics.json"
    assert _default_metrics_url("rtsp://camera/live") is None

    metrics = PublisherMetrics("http://example.invalid/metrics.json")
    metrics.bitrate_mbps = 3.25
    metrics.snapshot = {
        "streams": {
            "/camera/front/h264": {
                "subscribers": 1,
                "queue": {"dropped": 2},
            }
        },
        "nodes": {
            "encoder": {"resources": {"cpu_percent": 48.5}},
        },
        "system": {"temperature_c": 61.0, "memory_available_bytes": 1024},
    }
    summary = metrics.summary("/camera/front/h264")
    assert summary["bitrate_mbps"] == pytest.approx(3.25)
    assert summary["subscribers"] == 1
    assert summary["stream_drops"] == 2
    assert summary["node_cpu"]["encoder"] == pytest.approx(48.5)
    assert summary["temperature_c"] == pytest.approx(61.0)


def test_top_once_reads_resource_snapshot(tmp_path: Path) -> None:
    run_dir = tmp_path / ".nodrix" / "runs" / "20260728-test"
    run_dir.mkdir(parents=True)
    (run_dir / "status.json").write_text(json.dumps({
        "pipeline": "top-test",
        "nodes": {
            "encoder": {
                "rate_hz": 30.0,
                "p95_ms": 4.5,
                "resources": {
                    "scope": "isolated_process",
                    "cpu_percent": 75.0,
                    "rss_bytes": 64 * 1024 * 1024,
                    "estimated_queue_bytes": 4096,
                    "input_drops": 3,
                },
                "health": {"status": "healthy"},
            }
        },
        "system": {"memory_available_bytes": 512 * 1024 * 1024, "temperature_c": 55.0},
    }), encoding="utf-8")
    result = CliRunner().invoke(app, ["top", "--run", "20260728-test", "--project", str(tmp_path), "--once", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["nodes"]["encoder"]["resources"]["cpu_percent"] == pytest.approx(75.0)
    assert payload["nodes"]["encoder"]["resources"]["rss_bytes"] == 64 * 1024 * 1024
