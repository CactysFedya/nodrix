from __future__ import annotations

from pathlib import Path

import nodrix
from nodrix.node_docs import parameter_schema
from nodrix.project_templates import create_project
from nodrix.ux import render_top


def test_v141_version() -> None:
    assert nodrix.__version__ == "1.4.1"


def test_vision_template_keeps_parameters_in_blocks(tmp_path: Path) -> None:
    project = tmp_path / "pi-detector"
    create_project(project, "vision")

    pipeline = (project / "pipeline.yaml").read_text(encoding="utf-8")
    source = (
        project / "blocks/sources/ffmpeg.yaml"
    ).read_text(encoding="utf-8")
    detector = (
        project / "blocks/detectors/yolo26n-ncnn.yaml"
    ).read_text(encoding="utf-8")
    encoder = (
        project / "blocks/outputs/h264.yaml"
    ).read_text(encoding="utf-8")

    assert "NODRIX_" not in source
    assert "NODRIX_" not in detector
    assert "NODRIX_" not in encoder
    assert "rate=15" in source
    assert "fps: 15" in source
    assert "threads: 3" in detector
    assert "# Minimum detection confidence" in detector
    assert "capacity: 4" in pipeline
    assert "policy: drop_oldest" in pipeline
    assert "fps:" not in encoder
    assert not (project / "native").exists()
    assert not (project / "configs").exists()


def test_detector_parameters_are_documented() -> None:
    names = {
        row["name"]
        for row in parameter_schema("vision.ncnn_detector")
    }
    assert names >= {
        "model",
        "conf",
        "iou",
        "max_det",
        "threads",
        "output_format",
        "has_objectness",
    }


def test_top_render_separates_process_and_node_metrics() -> None:
    renderable = render_top(
        {
            "nodes": {
                "detector": {
                    "rate_hz": 14.0,
                    "p95_ms": 72.0,
                    "resources": {
                        "scope": "executor_shared",
                        "pid": 123,
                        "cpu_percent": 111.0,
                        "executor_cpu_percent": 250.0,
                        "executor_rss_bytes": 100 * 1024 * 1024,
                        "executor_vms_bytes": 500 * 1024 * 1024,
                        "threads": 8,
                        "estimated_queue_bytes": 1024,
                        "input_drops": 4,
                    },
                    "health": {"status": "healthy"},
                }
            },
            "system": {
                "memory_available_bytes": 1024 * 1024 * 1024,
                "temperature_c": 60.0,
                "load_average": [1.0, 0.5, 0.25],
            },
        }
    )
    assert renderable is not None
