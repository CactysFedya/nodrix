from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from nodrix.benchmarking import (
    BENCHMARK_SCHEMA,
    BenchmarkPlan,
    BenchmarkVariant,
    aggregate_reports,
    load_benchmark_plan,
    model_inventory,
    replay_plan,
    run_benchmark_suite,
)


def _report(run_dir: Path, *, rate: float, p95: float, drops: int = 0) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "pipeline": "demo",
        "status": "completed",
        "run_dir": str(run_dir),
        "duration_seconds": 2.0,
        "nodes": {
            "source": {
                "messages": int(rate * 2),
                "rate_hz": rate,
                "processing": {"mean_ms": 1.0, "p50_ms": 1.0, "p95_ms": 1.2, "p99_ms": 1.4},
                "queue_wait": {"p95_ms": 0.0},
                "end_to_end": {"p95_ms": 0.0},
                "errors": 0,
                "resources": {"rss_bytes": 1024},
            },
            "sink": {
                "messages": int(rate * 2) - drops,
                "rate_hz": rate - drops / 2,
                "processing": {"mean_ms": 2.0, "p50_ms": 2.0, "p95_ms": 2.5, "p99_ms": 3.0},
                "queue_wait": {"p95_ms": 0.5},
                "end_to_end": {"p95_ms": p95},
                "errors": 0,
                "resources": {"rss_bytes": 2048},
            },
        },
        "edges": [{"source": "source.output", "target": "sink.input", "dropped": drops}],
        "system": {"temperature_c": 60.0},
    }


def test_load_benchmark_plan_variants(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text("name: demo\n", encoding="utf-8")
    spec = tmp_path / "benchmark.yaml"
    spec.write_text(yaml.safe_dump({
        "version": 1,
        "pipeline": "pipeline.yaml",
        "repeat": 4,
        "warmup": 2,
        "variants": {
            "fast": {"profile": "maximum-throughput", "set": ["detector.imgsz=320"]},
            "accurate": {"block": ["detector=blocks/yolo512.yaml"]},
        },
    }), encoding="utf-8")
    plan = load_benchmark_plan(spec, selected_variants=["fast"])
    assert plan.pipeline == pipeline.resolve()
    assert plan.repeat == 4
    assert plan.warmup == 2
    assert plan.variants == (BenchmarkVariant("fast", "maximum-throughput", ("detector.imgsz=320",), ()),)


def test_load_benchmark_plan_rejects_unknown_variant(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text("name: demo\n", encoding="utf-8")
    spec = tmp_path / "benchmark.yaml"
    spec.write_text("version: 1\npipeline: pipeline.yaml\nvariants:\n  base: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown benchmark variants"):
        load_benchmark_plan(spec, selected_variants=["missing"])


def test_aggregate_reports_includes_pipeline_metrics(tmp_path: Path) -> None:
    summary = aggregate_reports([
        _report(tmp_path / "a", rate=20.0, p95=50.0, drops=1),
        _report(tmp_path / "b", rate=22.0, p95=54.0, drops=3),
    ])
    assert summary["source_rate_hz"]["mean"] == 21.0
    assert summary["sink_rate_hz"]["mean"] == 20.0
    assert summary["end_to_end_p95_ms"]["mean"] == 52.0
    assert summary["dropped_messages"]["mean"] == 2.0
    assert summary["estimated_memory_bytes"]["max"] == 3072.0
    assert summary["nodes"]["sink"]["processing_ms"]["p95"]["mean"] == 2.5


def test_run_benchmark_suite_writes_versioned_artifacts(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text("name: demo\n", encoding="utf-8")
    calls: list[tuple[str | None, list[str], list[str]]] = []

    def runner(path: Path, run_root: Path, profile: str | None, set_values: list[str], block_values: list[str]) -> dict:
        calls.append((profile, set_values, block_values))
        return _report(run_root / f"run-{len(calls)}", rate=20.0, p95=50.0)

    result = run_benchmark_suite(
        BenchmarkPlan(
            pipeline,
            repeat=2,
            warmup=1,
            variants=(BenchmarkVariant("fast", "maximum-throughput", ("x=1",), ()),),
        ),
        runner,
        output_root=tmp_path / "benchmarks",
    )
    suite_dir = Path(result["suite_dir"])
    assert len(calls) == 3
    assert result["schema"] == BENCHMARK_SCHEMA
    assert (suite_dir / "benchmark.json").is_file()
    assert (suite_dir / "environment.json").is_file()
    assert (suite_dir / "models.json").is_file()
    summary = json.loads((suite_dir / "variants/fast/summary.json").read_text(encoding="utf-8"))
    assert summary["repeat"] == 2
    assert summary["warmup"] == 1
    assert summary["profile"] == "maximum-throughput"
    assert len(summary["run_dirs"]) == 2



def test_model_inventory_hashes_resolved_model(tmp_path: Path) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(b"nodrix-model")
    manifest = tmp_path / "resolved-manifest.yaml"
    manifest.write_text(
        yaml.safe_dump({"nodes": {"detector": {"parameters": {"model": str(model)}}}}),
        encoding="utf-8",
    )
    inventory = model_inventory(manifest)
    assert len(inventory) == 1
    assert inventory[0]["path"] == str(model)
    assert inventory[0]["size_bytes"] == len(b"nodrix-model")
    assert len(inventory[0]["sha256"]) == 64

def test_replay_plan_prefers_ndrx_recording(tmp_path: Path) -> None:
    run = tmp_path / "run"
    recording = run / "outputs/input.ndrx"
    recording.parent.mkdir(parents=True)
    recording.write_bytes(b"NDRX")
    plan = replay_plan(run)
    assert plan["replayable"] is True
    assert plan["mode"] == "recording"
    assert plan["command"][-1] == str(recording.resolve())


def test_replay_plan_rejects_live_source(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "resolved-manifest.yaml").write_text(
        "nodes:\n  camera:\n    uses: media.ffmpeg_source\n    parameters:\n      uri: rtsp://camera/live\n",
        encoding="utf-8",
    )
    plan = replay_plan(run)
    assert plan["replayable"] is False
    assert plan["mode"] == "live-source"
