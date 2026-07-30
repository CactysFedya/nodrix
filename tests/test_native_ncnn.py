from __future__ import annotations

import json
from pathlib import Path
import struct

import numpy as np
import pytest

from nodrix.cv_types import Detections, Frame, ManagedBuffer, PixelFormat
from nodrix.messages import Message
import nodrix.native_plugin as native_plugin
from nodrix.native_plugin import NativePluginNode
from nodrix.node import NodeContext
from nodrix.node_docs import validate_parameters
from nodrix.runs import load_run
from nodrix.vision import nodes as vision_nodes
from nodrix.wire import decode_packet_parts, encode_message


class _FakeNativeHost:
    last_parameters: dict[str, object] | None = None
    input_types = {"frame": "vision.frame"}
    output_types = {"detections": "vision.detections"}
    input_memory = {"frame": "cpu"}
    output_memory = {"detections": "cpu"}
    optional_inputs: tuple[str, ...] = ()
    is_source = False

    def __init__(
        self,
        _library: str,
        _node_type: str,
        parameters_json: str,
    ) -> None:
        type(self).last_parameters = json.loads(parameters_json)

    def open(self, **_kwargs: object) -> None:
        return None

    def process(
        self,
        _inputs: dict[str, Message],
    ) -> dict[str, Message]:
        return {}

    def flush(self) -> dict[str, Message]:
        return {}

    def close(self) -> None:
        return None


def _patch_native_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "libnodrix_ncnn_detector.so"
    plugin.write_bytes(b"test")
    monkeypatch.setattr(native_plugin, "NativeNodeHost", _FakeNativeHost)
    monkeypatch.setattr(
        vision_nodes,
        "_packaged_ncnn_plugin",
        lambda: plugin,
    )


def test_native_model_paths_resolve_against_project_and_keep_unicode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_native_host(monkeypatch, tmp_path)
    project = tmp_path / "проект"
    model = project / "модели" / "детектор"
    model.mkdir(parents=True)
    (model / "model.ncnn.param").write_text("test", encoding="utf-8")
    (model / "model.ncnn.bin").write_bytes(b"test")
    invocation = tmp_path / "other"
    invocation.mkdir()
    monkeypatch.chdir(invocation)

    node = vision_nodes.NativeNcnnDetectorNode(
        {"model": "модели/детектор", "imgsz": 320}
    )
    node.open(
        NodeContext(
            name="detector",
            run_dir=tmp_path / "run",
            project_dir=project,
            runtime_mode="realtime",
        )
    )

    parameters = _FakeNativeHost.last_parameters
    assert parameters is not None
    assert parameters["param"] == str(model / "model.ncnn.param")
    assert parameters["bin"] == str(model / "model.ncnn.bin")
    node.close()


@pytest.mark.parametrize(
    ("array", "pixel_format", "message"),
    [
        (
            np.zeros((321, 320, 3), dtype=np.uint8),
            PixelFormat.BGR8,
            "geometry",
        ),
        (
            np.zeros((320, 320, 3), dtype=np.uint8),
            PixelFormat.RGB8,
            "BGR8",
        ),
        (
            np.zeros((320, 320, 4), dtype=np.uint8),
            PixelFormat.BGRA8,
            "BGR8",
        ),
    ],
)
def test_native_detector_rejects_invalid_frame_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    array: np.ndarray,
    pixel_format: PixelFormat,
    message: str,
) -> None:
    _patch_native_host(monkeypatch, tmp_path)
    node = vision_nodes.NativeNcnnDetectorNode({"model": "unused"})
    frame = Frame.from_numpy(array, pixel_format=pixel_format)
    with pytest.raises((ValueError, TypeError), match=message):
        node.process(
            {"frame": Message(type="vision.frame", payload=frame)}
        )


def test_native_adapter_preserves_managed_buffer_slice() -> None:
    managed = ManagedBuffer(
        owner=b"XXpayloadYY",
        offset=2,
        length=7,
    )
    message = Message(type="core.bytes", payload=managed)
    unwrapped = NativePluginNode._unwrap(message)
    assert bytes(unwrapped.payload) == b"payload"


def test_native_detection_payload_decoder_and_invalid_count() -> None:
    header = struct.pack("<4sHHII", b"NDT2", 1, 0, 2, 0)
    boxes = np.asarray(
        [[10, 20, 30, 40], [5, 6, 7, 8]],
        dtype="<f4",
    ).tobytes()
    scores = np.asarray([0.9, 0.5], dtype="<f4").tobytes()
    classes = np.asarray([1, 2], dtype="<i4").tobytes()
    message = Message(
        type="vision.detections",
        payload=header + boxes + scores + classes,
    )
    host = object.__new__(NativePluginNode)
    host.native_labels = ("zero", "one", "two")
    decoded = host._decode_native_detections(message)
    assert decoded is not None
    assert isinstance(decoded.payload, Detections)
    np.testing.assert_allclose(
        decoded.payload.boxes,
        [[10, 20, 30, 40], [5, 6, 7, 8]],
    )
    np.testing.assert_array_equal(
        decoded.payload.class_ids,
        [1, 2],
    )

    malformed = Message(
        type="vision.detections",
        payload=struct.pack("<4sHHII", b"NDT2", 1, 0, 100, 0),
    )
    with pytest.raises(RuntimeError, match="count"):
        host._decode_native_detections(malformed)


def test_hotfix_contracts(tmp_path: Path) -> None:
    validate_parameters("vision.letterbox", {"imgsz": 320})
    with pytest.raises(ValueError, match="must be >= 1"):
        validate_parameters("vision.letterbox", {"imgsz": 0})

    empty = Message(
        type="vision.detections",
        payload=Detections(
            boxes=np.empty((0, 4), dtype=np.float32),
            scores=np.empty((0,), dtype=np.float32),
            class_ids=np.empty((0,), dtype=np.int32),
        ),
    )
    packet = encode_message(empty)
    decoded = decode_packet_parts(
        packet.header,
        packet.type_name,
        packet.metadata,
        b"".join(bytes(part) for part in packet.payload_parts),
    )
    assert isinstance(decoded.payload, Detections)
    assert len(decoded.payload) == 0

    run_dir = tmp_path / ".nodrix" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    assert load_run("run-1", tmp_path)["status"] == "starting"
