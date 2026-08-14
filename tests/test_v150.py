from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import nodrix
import nodrix.media as media
from nodrix.manifest import load_manifest
from nodrix.project_templates import create_project
from nodrix.ux import render_pipeline_graph, render_top
from nodrix.vision.tracking import (
    ByteTrackCore,
    RealtimeByteTrackCore,
    greedy_iou_assignment,
    native_tracking_available,
)


def test_v150_version() -> None:
    assert nodrix.__version__ == "2.8.0"


def test_v150_template_is_multirate_hardware_first_and_self_contained(tmp_path: Path) -> None:
    project = tmp_path / "vision-150"
    create_project(project, "vision")

    manifest = load_manifest(project / "pipeline.yaml")
    tracker = manifest.nodes["tracker"]
    encoder = manifest.nodes["encoder"]
    detector = manifest.nodes["detector"]

    assert tracker.uses == "vision.realtime_bytetrack"
    assert tracker.synchronization.policy == "latest_available"
    assert tracker.synchronization.trigger_port == "frame"
    assert tracker.parameters["backend"] == "native"
    assert tracker.parameters["delayed_measurement_replay"] is True
    assert tracker.parameters["max_prediction_frames"] == 15

    assert detector.uses == "vision.ncnn_detector_native"
    assert detector.parameters["backend"] == "cpu"
    assert detector.parameters["threads"] == 4
    assert encoder.parameters["encoder"] == "auto"
    assert encoder.parameters["acceleration"] == "preferred"
    assert manifest.runtime.metrics.listen == "127.0.0.1:9464"

    edges = {(edge.source, edge.target): edge for edge in manifest.edges}
    assert edges[("source.frame", "tracker.frame")].queue.capacity == 2
    assert edges[("source.frame", "tracker.frame")].queue.policy == "drop_oldest"
    assert edges[("detector.detections", "tracker.detections")].queue.policy == "latest"
    assert edges[("source.frame", "overlay.frame")].queue.capacity == 4

    assert not (project / "config.env").exists()
    assert not (project / "configs").exists()
    assert not (project / "native").exists()
    assert (project / "blocks/outputs/h264-software.yaml").is_file()
    project_gitignore = (project / ".gitignore").read_text(encoding="utf-8")
    assert "/outputs/*" in project_gitignore
    assert "!/outputs/.gitkeep" in project_gitignore


def test_realtime_tracker_predicts_every_frame_and_replays_delayed_measurement() -> None:
    core = ByteTrackCore(
        backend="python",
        track_threshold=0.25,
        low_threshold=0.10,
        match_iou=0.10,
        second_match_iou=0.10,
        track_buffer=30,
        maximum_visible_missed=15,
    )
    tracker = RealtimeByteTrackCore(
        core,
        history_frames=16,
        maximum_prediction_frames=15,
        prediction_score_decay=0.99,
        delayed_measurement_replay=True,
    )

    first, first_meta = tracker.step(
        frame_sequence=0,
        frame_timestamp_ns=1_000_000_000,
        detection_sequence=0,
        detection_timestamp_ns=1_000_000_000,
        boxes=[[10, 10, 30, 30]],
        scores=[0.9],
        class_ids=[0],
    )
    assert first[1].tolist() == [1]
    assert first[4] == ["tracked"]
    assert first_meta["measurement"] == "current"

    predicted, predicted_meta = tracker.step(
        frame_sequence=1,
        frame_timestamp_ns=1_033_333_333,
    )
    assert predicted[1].tolist() == [1]
    assert predicted[4] == ["predicted"]
    assert predicted_meta["prediction"] is True

    tracker.step(frame_sequence=2, frame_timestamp_ns=1_066_666_666)
    replayed, replay_meta = tracker.step(
        frame_sequence=3,
        frame_timestamp_ns=1_100_000_000,
        detection_sequence=1,
        detection_timestamp_ns=1_033_333_333,
        boxes=[[12, 10, 32, 30]],
        scores=[0.92],
        class_ids=[0],
    )
    assert replayed[1].tolist() == [1]
    assert replay_meta["measurement"] == "replayed"
    assert replay_meta["replayed_measurements"] == 1

    duplicate, duplicate_meta = tracker.step(
        frame_sequence=4,
        frame_timestamp_ns=1_133_333_333,
        detection_sequence=1,
        detection_timestamp_ns=1_033_333_333,
        boxes=[[12, 10, 32, 30]],
        scores=[0.92],
        class_ids=[0],
    )
    assert duplicate[1].tolist() == [1]
    assert duplicate_meta["measurement"] == "duplicate"


@pytest.mark.skipif(not native_tracking_available(), reason="native tracking extension is not built")
def test_native_tracking_backend_matches_expected_assignment() -> None:
    result = greedy_iou_assignment(
        [[0, 0, 10, 10], [20, 20, 30, 30]],
        [[1, 1, 11, 11], [100, 100, 110, 110]],
        [0, 1],
        [0, 1],
        minimum_iou=0.3,
        backend="native",
    )
    assert result == ([(0, 0)], [1], [1])


def test_required_hardware_policy_never_probes_software_fallback(monkeypatch) -> None:
    attempted: list[str] = []

    monkeypatch.setattr(media, "_encoder_candidates", lambda _codec: ["h264_hw", "libx264"])
    monkeypatch.setattr(media, "_software_encoder", lambda _codec: "libx264")

    def fake_probe(encoder: str, _codec: str) -> tuple[bool, str]:
        attempted.append(encoder)
        return False, "not available"

    monkeypatch.setattr(media, "probe_encoder", fake_probe)
    result = media.select_encoder("h264", "auto", "required")

    assert result["ok"] is False
    assert result["selected"] is None
    assert attempted == ["h264_hw"]
    assert "software fallback is disabled" in result["reason"]


def test_preferred_hardware_policy_reports_visible_software_fallback(monkeypatch) -> None:
    monkeypatch.setattr(media, "_encoder_candidates", lambda _codec: ["h264_hw", "libx264"])
    monkeypatch.setattr(media, "_software_encoder", lambda _codec: "libx264")
    monkeypatch.setattr(
        media,
        "probe_encoder",
        lambda encoder, _codec: (encoder == "libx264", "probe result"),
    )

    result = media.select_encoder("h264", "auto", "preferred")
    assert result["ok"] is True
    assert result["selected"] == "libx264"
    assert result["hardware"] is False
    assert result["fallback"] == "libx264"
    assert "hardware probes failed" in result["reason"]


def test_v150_graph_and_htop_renderers_smoke(tmp_path: Path) -> None:
    project = tmp_path / "render-150"
    create_project(project, "vision")
    manifest = load_manifest(project / "pipeline.yaml")
    assert render_pipeline_graph(manifest) is not None
    assert render_top(
        {
            "pipeline": "render-150",
            "status": "running",
            "duration_seconds": 2.0,
            "nodes": {
                "source": {
                    "rate_hz": 30.0,
                    "p95_ms": 0.2,
                    "resources": {
                        "scope": "executor_shared",
                        "executor_cpu_percent": 120.0,
                        "executor_rss_bytes": 128 * 1024 * 1024,
                        "cpu_percent": 1.0,
                    },
                    "health": {"status": "healthy"},
                },
                "tracker": {
                    "rate_hz": 29.8,
                    "p95_ms": 0.8,
                    "resources": {"cpu_percent": 3.0},
                    "runtime_info": {"backend": "cpp20-iou+numpy-kalman"},
                    "health": {"status": "healthy"},
                },
            },
            "system": {"cpu_count": 4, "memory_total_bytes": 8 * 1024**3},
            "edges": [],
        }
    ) is not None


def test_realtime_tracker_node_starts_before_first_detection(tmp_path: Path) -> None:
    from nodrix.cv_types import Detections, Frame
    from nodrix.messages import Message
    from nodrix.node import NodeContext
    from nodrix.vision.nodes import RealtimeByteTrackNode

    node = RealtimeByteTrackNode(
        {
            "backend": "python",
            "history_frames": 16,
            "max_prediction_frames": 15,
            "delayed_measurement_replay": True,
        }
    )
    node.open(NodeContext("tracker", tmp_path, tmp_path, "realtime"))

    def frame_message(sequence: int) -> Message:
        return Message(
            "vision.frame",
            Frame.from_numpy(np.zeros((64, 64, 3), dtype=np.uint8)),
            sequence=sequence,
            timestamp_ns=1_000_000_000 + sequence * 33_333_333,
        )

    first = node.process({"frame": frame_message(0)})["tracks"].payload
    second = node.process({"frame": frame_message(1)})["tracks"].payload
    assert len(first) == 0
    assert len(second) == 0

    detection = Detections([[10, 10, 30, 30]], [0.9], [0])
    replayed = node.process(
        {
            "frame": frame_message(2),
            "detections": Message(
                "vision.detections",
                detection,
                sequence=0,
                timestamp_ns=1_000_000_000,
            ),
        }
    )["tracks"].payload

    assert replayed.track_ids.tolist() == [1]
    assert replayed.attributes["measurement"] == "replayed"


def test_latest_available_optional_side_input_does_not_block(tmp_path: Path) -> None:
    from nodrix import Message, SinkNode, SourceNode
    from nodrix.hybrid_runtime import HybridPipelineRuntime
    from nodrix.manifest import PipelineManifest
    from nodrix.registry import BUILTINS

    class Frames(SourceNode):
        output_types = {"out": "core.object"}

        def produce(self):
            for sequence in range(3):
                yield {
                    "out": Message(
                        "core.object",
                        f"frame-{sequence}",
                        sequence=sequence,
                    )
                }

    class NoMeasurements(SourceNode):
        output_types = {"out": "core.object"}

        def produce(self):
            if False:
                yield {}

    class Join(SinkNode):
        input_types = {"frame": "core.object", "measurement": "core.object"}
        optional_inputs = frozenset({"measurement"})

        def open(self, context):
            super().open(context)
            self.values = []

        def process(self, inputs):
            self.values.append(
                (
                    inputs["frame"].payload,
                    None if "measurement" not in inputs else inputs["measurement"].payload,
                )
            )

    BUILTINS.update(
        {
            "test.v150_frames": Frames,
            "test.v150_no_measurements": NoMeasurements,
            "test.v150_optional_join": Join,
        }
    )
    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "optional-side-input"},
            "runtime": {"engine": "unified"},
            "nodes": {
                "frames": {"uses": "test.v150_frames"},
                "measurements": {"uses": "test.v150_no_measurements"},
                "join": {
                    "uses": "test.v150_optional_join",
                    "synchronization": {
                        "policy": "latest_available",
                        "trigger_port": "frame",
                    },
                },
            },
            "edges": [
                {"from": "frames.out", "to": "join.frame"},
                {"from": "measurements.out", "to": "join.measurement"},
            ],
        }
    )
    manifest_path = tmp_path / "pipeline.yaml"
    manifest_path.write_text("metadata: {name: placeholder}\nnodes: {}\nedges: []\n")
    runtime = HybridPipelineRuntime(manifest, manifest_path, run_root=tmp_path / "runs")
    runtime.build()
    join = runtime.nodes["join"].node

    report = runtime.run_sync()

    assert report["status"] == "completed"
    assert join.values == [
        ("frame-0", None),
        ("frame-1", None),
        ("frame-2", None),
    ]


def test_hardware_encoder_candidates_cover_embedded_and_gpu_backends(monkeypatch) -> None:
    monkeypatch.setattr(media.platform, "system", lambda: "Linux")
    monkeypatch.setattr(media.platform, "machine", lambda: "aarch64")

    candidates = media._encoder_candidates("h264")

    assert candidates[:3] == ["h264_v4l2m2m", "h264_rkmpp", "h264_nvmpi"]
    assert "h264_nvenc" in candidates
    assert "h264_qsv" in candidates
    assert "h264_vaapi" in candidates
    assert candidates[-1] == "libx264"


def test_vaapi_adapter_uses_render_node_and_hwupload(monkeypatch) -> None:
    monkeypatch.setattr(media, "_vaapi_device", lambda: "/dev/dri/renderD128")

    before_input, before_codec, after_codec, pixel_format = media._encoder_backend_arguments(
        "h264_vaapi",
        quality=21,
        keyint=30,
    )

    assert before_input == ["-vaapi_device", "/dev/dri/renderD128"]
    assert before_codec == ["-vf", "format=nv12,hwupload"]
    assert after_codec == ["-qp", "21", "-g", "30"]
    assert pixel_format is None


def test_videotoolbox_adapter_forbids_internal_software_fallback() -> None:
    _, _, after_codec, _ = media._encoder_backend_arguments(
        "h264_videotoolbox",
        quality=23,
        keyint=30,
    )
    assert ["-allow_sw", "0"] == after_codec[:2]
