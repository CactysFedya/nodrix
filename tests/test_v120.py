from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.lockfile import build_lock, verify_lock, write_lock
from nodrix.manifest import load_manifest_details


def _write_project(tmp_path: Path) -> Path:
    (tmp_path / "blocks" / "detectors").mkdir(parents=True)
    (tmp_path / "blocks" / "source.yaml").write_text(
        yaml.safe_dump({"use": "core.synthetic_source", "count": 3}),
        encoding="utf-8",
    )
    (tmp_path / "blocks" / "detectors" / "fast.yaml").write_text(
        yaml.safe_dump({"use": "core.identity", "label": "fast"}),
        encoding="utf-8",
    )
    (tmp_path / "blocks" / "detectors" / "accurate.yaml").write_text(
        yaml.safe_dump({"use": "core.identity", "label": "accurate"}),
        encoding="utf-8",
    )
    (tmp_path / "blocks" / "sink.yaml").write_text(
        yaml.safe_dump({"use": "core.counter_sink"}),
        encoding="utf-8",
    )
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(yaml.safe_dump({
        "name": "blocks-demo",
        "profile": "realtime-low-latency",
        "blocks": {
            "source": "blocks/source.yaml",
            "detector": "blocks/detectors/fast.yaml",
            "sink": "blocks/sink.yaml",
        },
        "flow": [
            "source.output -> detector.input",
            "detector.output -> sink.input",
        ],
    }, sort_keys=False), encoding="utf-8")
    return pipeline


def test_blocks_expand_to_nodes_without_runtime_boundaries(tmp_path: Path) -> None:
    pipeline = _write_project(tmp_path)
    details = load_manifest_details(pipeline)
    assert set(details.manifest.nodes) == {"source", "detector", "sink"}
    assert details.manifest.nodes["detector"].uses == "core.identity"
    assert details.manifest.nodes["detector"].parameters["label"] == "fast"
    assert set(details.block_files) == {"source", "detector", "sink"}
    assert details.sources["nodes.detector.parameters.label"].startswith("block:")
    assert len(details.manifest.edges) == 2


def test_block_override_and_short_parameter_override(tmp_path: Path) -> None:
    pipeline = _write_project(tmp_path)
    details = load_manifest_details(
        pipeline,
        block_overrides=["detector=blocks/detectors/accurate.yaml"],
        overrides=["detector.label=experiment", "source.count=7"],
    )
    assert details.manifest.nodes["detector"].parameters["label"] == "experiment"
    assert details.manifest.nodes["source"].parameters["count"] == 7
    assert details.block_files["detector"].name == "accurate.yaml"
    assert details.sources["nodes.detector.parameters.label"] == "CLI --set"


def test_unknown_block_override_is_rejected(tmp_path: Path) -> None:
    pipeline = _write_project(tmp_path)
    result = CliRunner().invoke(app, [
        "validate", str(pipeline), "--block", "tracker=blocks/detectors/fast.yaml",
    ])
    assert result.exit_code == 1
    assert "Unknown block" in result.output


def test_block_cli_list_and_inspect(tmp_path: Path) -> None:
    _write_project(tmp_path)
    runner = CliRunner()
    listed = runner.invoke(app, ["block", "list", "--project", str(tmp_path), "--json"])
    assert listed.exit_code == 0, listed.output
    items = json.loads(listed.output)
    assert {item["name"] for item in items} >= {"source", "fast", "accurate", "sink"}
    inspected = runner.invoke(app, [
        "block", "inspect", str(tmp_path / "blocks" / "source.yaml"),
        "--project", str(tmp_path), "--json",
    ])
    assert inspected.exit_code == 0, inspected.output
    payload = json.loads(inspected.output)
    assert payload["uses"] == "core.synthetic_source"
    assert payload["parameters"]["count"] == 3
    assert payload["outputs"]["output"] == "core.object"


def test_validate_and_resolved_support_block_replacement(tmp_path: Path) -> None:
    pipeline = _write_project(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, [
        "inspect", str(pipeline), "--resolved",
        "--block", "detector=blocks/detectors/accurate.yaml",
        "--set", "detector.label=selected",
    ])
    assert result.exit_code == 0, result.output
    rendered = yaml.safe_load(result.output)
    assert rendered["nodes"]["detector"]["parameters"]["label"] == "selected"
    assert "blocks" not in rendered

    explained = runner.invoke(app, [
        "config", "explain", "detector.label", "--pipeline", str(pipeline),
        "--block", "detector=blocks/detectors/accurate.yaml",
    ])
    assert explained.exit_code == 0, explained.output
    assert 'Value: "accurate"' in explained.output
    assert "block:blocks/detectors/accurate.yaml" in explained.output


def test_resolved_blocks_execute_as_normal_nodes(tmp_path: Path) -> None:
    pipeline = _write_project(tmp_path)
    details = load_manifest_details(pipeline, profile="lossless-recording", overrides=["source.count=5"])
    runtime = HybridPipelineRuntime(details.manifest, pipeline, run_root=tmp_path / "runs")
    runtime.build()
    report = runtime.run_sync()
    assert report["status"] == "completed"
    assert report["nodes"]["sink"]["messages"] == 5


def test_lock_contains_only_imported_blocks_and_detects_changes(tmp_path: Path) -> None:
    pipeline = _write_project(tmp_path)
    lock = build_lock(pipeline)
    files = set(lock["files"])
    assert "blocks/source.yaml" in files
    assert "blocks/detectors/fast.yaml" in files
    assert "blocks/detectors/accurate.yaml" not in files
    write_lock(pipeline)
    (tmp_path / "blocks" / "detectors" / "fast.yaml").write_text(
        yaml.safe_dump({"use": "core.identity", "label": "changed"}),
        encoding="utf-8",
    )
    result = verify_lock(pipeline)
    assert result["ok"] is False
    assert any("blocks/detectors/fast.yaml" in issue for issue in result["issues"])


def test_locked_run_rejects_block_override(tmp_path: Path) -> None:
    pipeline = _write_project(tmp_path)
    result = CliRunner().invoke(app, [
        "run", str(pipeline), "--locked",
        "--block", "detector=blocks/detectors/accurate.yaml",
    ])
    assert result.exit_code == 2
    assert "--block" in result.output
