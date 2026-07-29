from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

import nodrix
from nodrix.cv_types import Detections, Frame, Tracks
from nodrix.messages import Message
from nodrix.node import NodeContext
from nodrix.project_templates import create_project
from nodrix.registry import load_node_class
from nodrix.vision.geometry import decode_yolo_output, restore_letterbox_boxes
from nodrix.vision.nodes import ByteTrackNode, LetterboxNode, NcnnDetectorNode, OverlayNode


def _context(path: Path, name: str = "vision-test") -> NodeContext:
    return NodeContext(name=name, run_dir=path, project_dir=path, runtime_mode="realtime")


def test_v130_metadata_and_builtin_registration() -> None:
    assert load_node_class("vision.letterbox") is LetterboxNode
    assert load_node_class("vision.ncnn_detector") is NcnnDetectorNode
    assert load_node_class("vision.bytetrack") is ByteTrackNode
    assert load_node_class("vision.overlay") is OverlayNode



def test_v130_vision_template_uses_h264_preview(tmp_path: Path) -> None:
    project = tmp_path / "production-vision"
    create_project(project, "vision")

    manifest = (project / "pipeline.yaml").read_text(encoding="utf-8")
    encoder = (
        project / "blocks/outputs/h264.yaml"
    ).read_text(encoding="utf-8")
    readme = (project / "README.md").read_text(encoding="utf-8")

    assert "blocks/outputs/h264.yaml" in manifest
    assert "media.ffmpeg_encoder" in encoder
    assert "/production-vision/preview/h264" in manifest
    assert "from: overlay.frame" in manifest
    assert "to: encoder.frame" in manifest
    assert "encoder.encoded" in manifest
    assert "nodrix-viewer nodrix://DEVICE_IP:7420/production-vision/preview/h264 --overlay" in readme

def test_decode_modern_yolo_feature_major_and_nms() -> None:
    output = np.zeros((84, 3), dtype=np.float32)
    output[:4, 0] = [50, 50, 40, 40]
    output[4, 0] = 0.90
    output[:4, 1] = [52, 52, 40, 40]
    output[4, 1] = 0.80
    output[:4, 2] = [150, 150, 20, 20]
    output[6, 2] = 0.70

    boxes, scores, classes = decode_yolo_output(
        output,
        confidence_threshold=0.20,
        iou_threshold=0.50,
        num_classes=80,
    )

    assert boxes.shape == (2, 4)
    assert scores.shape == (2,)
    assert set(classes.tolist()) == {0, 2}


def test_decode_single_candidate_does_not_collapse_dimension() -> None:
    output = np.asarray([[160], [160], [100], [100], [0.9]], dtype=np.float32)
    boxes, scores, classes = decode_yolo_output(output, num_classes=1)
    np.testing.assert_allclose(boxes, [[110, 110, 210, 210]])
    np.testing.assert_allclose(scores, [0.9])
    assert classes.tolist() == [0]


def test_letterbox_records_reversible_transform(tmp_path: Path) -> None:
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    node = LetterboxNode({"imgsz": 320})
    node.open(_context(tmp_path))

    message = node.process({"frame": Message("vision.frame", Frame.from_numpy(image), sequence=7)})["frame"]
    assert message.payload.numpy().shape == (320, 320, 3)
    assert message.payload.metadata["letterbox"]["pad_top"] == 80

    restored = restore_letterbox_boxes(
        np.asarray([[0, 80, 320, 240]], dtype=np.float32),
        message.payload.metadata,
    )
    np.testing.assert_allclose(restored, [[0, 0, 199, 99]], atol=1.1)


def test_bytetrack_low_confidence_second_stage_preserves_id(tmp_path: Path) -> None:
    node = ByteTrackNode(
        {
            "track_thresh": 0.5,
            "low_thresh": 0.1,
            "match_iou": 0.2,
            "second_match_iou": 0.1,
        }
    )
    node.open(_context(tmp_path))

    first = Detections([[10, 10, 30, 30]], [0.9], [0])
    first_tracks = node.process(
        {"detections": Message("vision.detections", first, sequence=1, timestamp_ns=1_000_000_000)}
    )["tracks"].payload

    second = Detections([[11, 10, 31, 30]], [0.2], [0])
    second_tracks = node.process(
        {"detections": Message("vision.detections", second, sequence=2, timestamp_ns=1_033_000_000)}
    )["tracks"].payload

    assert first_tracks.track_ids.tolist() == [1]
    assert second_tracks.track_ids.tolist() == [1]


def test_overlay_draws_without_mutating_input(tmp_path: Path) -> None:
    source_image = np.zeros((80, 120, 3), dtype=np.uint8)
    frame = Frame.from_numpy(source_image, readonly=True)
    tracks = Tracks(
        boxes=[[10, 10, 60, 50]],
        track_ids=[3],
        scores=[0.9],
        class_ids=[0],
        states=["tracked"],
        attributes={"labels": ["object"]},
    )
    node = OverlayNode({})
    node.open(_context(tmp_path))

    result = node.process(
        {
            "frame": Message("vision.frame", frame, sequence=1),
            "tracks": Message("vision.tracks", tracks, sequence=1),
        }
    )["frame"].payload.numpy()

    assert not np.any(source_image)
    assert np.any(result)


def test_ncnn_detector_with_fake_backend(tmp_path: Path, monkeypatch) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.ncnn.param").write_text("fake", encoding="utf-8")
    (model / "model.ncnn.bin").write_bytes(b"fake")
    raw = np.asarray([[160], [160], [100], [100], [0.9]], dtype=np.float32)

    class OutputMat:
        def __array__(self, dtype=None, copy=None):
            del copy
            return np.asarray(raw, dtype=dtype)

    class InputMat:
        def substract_mean_normalize(self, _mean, _norm):
            return None

    class Mat:
        class PixelType:
            PIXEL_BGR2RGB = 1

        @staticmethod
        def from_pixels_resize(*_args):
            return InputMat()

    class Extractor:
        def input(self, *_args):
            return 0

        def extract(self, *_args):
            return 0, OutputMat()

    class Options:
        pass

    class Net:
        def __init__(self):
            self.opt = Options()

        def load_param(self, *_args):
            return 0

        def load_model(self, *_args):
            return 0

        def input_names(self):
            return ["in0"]

        def output_names(self):
            return ["out0"]

        def create_extractor(self):
            return Extractor()

    monkeypatch.setitem(sys.modules, "ncnn", SimpleNamespace(Net=Net, Mat=Mat))

    node = NcnnDetectorNode({"model": str(model), "labels": ["object"]})
    node.open(_context(tmp_path, "detector"))
    frame = Frame.from_numpy(np.zeros((320, 320, 3), dtype=np.uint8))
    result = node.process({"frame": Message("vision.frame", frame)})["detections"].payload

    assert result.class_ids.tolist() == [0]
    np.testing.assert_allclose(result.boxes, [[110, 110, 210, 210]])
