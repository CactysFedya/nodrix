from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

import nodrix
from nodrix.cli import app
from nodrix.manifest import PipelineManifest, load_manifest_details
from nodrix.planning import (
    build_static_plan,
    diagnose_report,
    explain_target,
    optimization_spec,
    select_optimization_variant,
    write_optimization_bundle,
)


def _manifest() -> PipelineManifest:
    return PipelineManifest.model_validate(
        {
            "metadata": {"name": "planner"},
            "runtime": {"engine": "unified"},
            "nodes": {
                "source": {
                    "uses": "core.synthetic_source",
                    "parameters": {"fps": 30, "count": 3},
                    "outputs": {"output": "core.object"},
                },
                "detector": {
                    "uses": "demo.detector",
                    "parameters": {"every_n": 3, "threads": 2},
                    "inputs": {"input": "core.object"},
                    "outputs": {"output": "core.object"},
                },
                "sink": {
                    "uses": "core.counter_sink",
                    "inputs": {"input": "core.object"},
                },
            },
            "edges": [
                {"from": "source.output", "to": "detector.input"},
                {"from": "detector.output", "to": "sink.input"},
            ],
        }
    )


def _description() -> dict:
    nodes = {
        "source": {
            "implementation": "python",
            "outputs": {"output": "core.object"},
        },
        "detector": {
            "implementation": "python",
            "inputs": {"input": "core.object"},
            "outputs": {"output": "core.object"},
        },
        "sink": {
            "implementation": "python",
            "inputs": {"input": "core.object"},
        },
    }
    return {
        "engine": "unified",
        "nodes": nodes,
        "edges": [
            {
                "from": "source.output",
                "to": "detector.input",
                "type": "core.object",
                "memory": {
                    "selected_memory": "host",
                    "planned_copies": 0,
                    "reason": "common host domain",
                },
            },
            {
                "from": "detector.output",
                "to": "sink.input",
                "type": "core.object",
                "memory": {
                    "selected_memory": "shared",
                    "planned_copies": 1,
                    "reason": "explicit upload",
                },
            },
        ],
    }


def test_v190_version() -> None:
    assert nodrix.__version__ == "2.8.0"


def test_planner_uses_declared_rates_and_never_invents_unknowns() -> None:
    result = build_static_plan(_manifest(), _description(), include_hardware=False)
    assert result["rates"]["source"]["estimated_hz"] == 30
    assert result["rates"]["detector"]["estimated_hz"] == 10
    assert result["rates"]["sink"]["estimated_hz"] == 10
    assert result["expected_output_hz"] == 10
    assert result["execution_plan"]["summary"]["planned_copies"] == 1
    assert any(item["code"] == "P201" for item in result["recommendations"])

    raw = _manifest().model_dump(by_alias=True)
    raw["nodes"]["source"]["parameters"].pop("fps")
    unknown = build_static_plan(
        PipelineManifest.model_validate(raw),
        _description(),
        include_hardware=False,
    )
    assert unknown["expected_output_hz"] is None
    assert any(item["code"] == "P101" for item in unknown["recommendations"])


def test_diagnose_reports_measured_bottleneck_pressure_copies_and_thermal() -> None:
    result = diagnose_report(
        {
            "pipeline": "measured",
            "status": "completed",
            "duration_seconds": 2,
            "nodes": {
                "source": {"processing": {"p95_ms": 1}},
                "detector": {
                    "processing": {"p95_ms": 20},
                    "transport": {"input_payload_copies": 2},
                    "resources": {"sync_misses": 1},
                },
            },
            "edges": [
                {
                    "source": "source.output",
                    "target": "detector.input",
                    "capacity": 4,
                    "max_depth": 4,
                    "dropped": 3,
                    "policy": "latest",
                }
            ],
            "system": {"temperature_c": 84},
        }
    )
    codes = {item["code"] for item in result["findings"]}
    assert {"D101", "D201", "D202", "D302", "D501"} <= codes
    bottleneck = next(item for item in result["findings"] if item["code"] == "D101")
    assert bottleneck["target"] == "detector"
    assert bottleneck["evidence"]["p95_ms"] == 20


def test_explain_and_optimize_preserve_source_manifest(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        yaml.safe_dump(_manifest().model_dump(by_alias=True), sort_keys=False),
        encoding="utf-8",
    )
    original = pipeline.read_bytes()
    details = load_manifest_details(pipeline)
    explained = explain_target(details, _description(), "detector.threads")
    assert explained["kind"] == "config"
    assert explained["target"] == "nodes.detector.parameters.threads"
    assert explained["value"] == 2

    spec_path, report_path, result = write_optimization_bundle(
        pipeline,
        details.manifest,
        tmp_path / "optimization",
    )
    assert pipeline.read_bytes() == original
    assert spec_path.is_file() and report_path.is_file()
    assert result["applied"] is False
    assert "detector_threads_1" in result["variants"]
    assert optimization_spec(details.manifest)["schema"] == "nodrix.optimization/v1"


def test_diagnose_cli_reads_completed_report(tmp_path: Path) -> None:
    report = tmp_path / "summary.json"
    report.write_text(
        json.dumps(
            {
                "pipeline": "demo",
                "status": "completed",
                "nodes": {"worker": {"processing": {"p95_ms": 5}}},
                "edges": [],
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["diagnose", str(report), "--json"])
    assert result.exit_code == 0, result.output
    decoded = json.loads(result.stdout)
    assert decoded["schema"] == "nodrix.diagnosis/v1"


def test_optimizer_selects_only_measured_constraint_compliant_variant() -> None:
    benchmark = {
        "variants": {
            "fast-hot": {
                "sink_rate_hz": {"mean": 40},
                "end_to_end_p95_ms": {"mean": 120},
                "temperature_c": {"max": 85},
                "estimated_memory_bytes": {"max": 100 * 1024 * 1024},
            },
            "balanced": {
                "sink_rate_hz": {"mean": 30},
                "end_to_end_p95_ms": {"mean": 80},
                "temperature_c": {"max": 70},
                "estimated_memory_bytes": {"max": 120 * 1024 * 1024},
            },
        }
    }
    result = select_optimization_variant(
        benchmark,
        constraints={"latency_p95_ms": 100, "temperature_c": 75},
    )
    assert result["selected"] == "balanced"
    assert result["applied"] is False
