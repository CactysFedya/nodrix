from __future__ import annotations

import socket
import threading
from pathlib import Path

import cv2
import numpy as np

from nodrix import Message
from nodrix.builtin_nodes import JpegDecoderNode, JpegEncoderNode
from nodrix.cv_types import EncodedFrame, Frame, ManagedBuffer, MediaCodec, PixelFormat
from nodrix.node import NodeContext
from nodrix.project_templates import create_project
from nodrix.viewer import LatestSlot, _prepare_overlay_frame, message_to_bgr, run_viewer
from nodrix.wire import encode_message, recv_message, send_packet


def _roundtrip(message: Message) -> Message:
    left, right = socket.socketpair()
    try:
        packet = encode_message(message)
        sender = threading.Thread(target=send_packet, args=(left, packet))
        sender.start()
        result = recv_message(right)
        sender.join(timeout=2)
        return result
    finally:
        left.close()
        right.close()


def test_encoded_frame_wire_roundtrip() -> None:
    encoded = EncodedFrame(
        buffer=ManagedBuffer.wrap(b"jpeg-payload", readonly=True),
        codec=MediaCodec.JPEG,
        width=640,
        height=360,
        fps=30.0,
        pts_ns=123,
    )
    result = _roundtrip(Message(type="vision.encoded_frame", payload=encoded, sequence=7))
    assert isinstance(result.payload, EncodedFrame)
    assert result.payload.codec == MediaCodec.JPEG
    assert bytes(result.payload.memoryview()) == b"jpeg-payload"
    assert result.payload.width == 640
    assert result.payload.fps == 30.0


def test_jpeg_encoder_decoder_nodes(tmp_path: Path) -> None:
    context = NodeContext("test", tmp_path, tmp_path, "realtime")
    encoder = JpegEncoderNode({"quality": 92})
    decoder = JpegDecoderNode()
    encoder.open(context)
    decoder.open(context)
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    image[:, :, 1] = 180
    message = Message(
        type="vision.frame",
        payload=Frame.from_numpy(image, pixel_format=PixelFormat.BGR8),
        sequence=4,
        metadata={"fps": 25.0},
    )
    encoded_message = encoder.process({"frame": message})["frame"]
    assert encoded_message.type == "vision.encoded_frame"
    assert encoded_message.payload.nbytes < image.nbytes
    decoded_message = decoder.process({"frame": encoded_message})["frame"]
    decoded = decoded_message.payload.numpy()
    assert decoded.shape == image.shape
    assert float(np.mean(np.abs(decoded.astype(np.int16) - image.astype(np.int16)))) < 5.0


def test_viewer_decodes_rgb_and_jpeg() -> None:
    rgb = np.zeros((8, 10, 3), dtype=np.uint8)
    rgb[:, :, 0] = 255
    raw = message_to_bgr(Message(type="vision.frame", payload=Frame.from_numpy(rgb, pixel_format=PixelFormat.RGB8)))
    assert tuple(raw[0, 0]) == (0, 0, 255)

    bgr = np.zeros((8, 10, 3), dtype=np.uint8)
    bgr[:, :, 2] = 200
    ok, data = cv2.imencode(".jpg", bgr)
    assert ok
    encoded = EncodedFrame(ManagedBuffer.wrap(data), MediaCodec.JPEG, 10, 8)
    decoded = message_to_bgr(Message(type="vision.encoded_frame", payload=encoded))
    assert decoded.shape == bgr.shape


def test_latest_slot_keeps_only_current_message() -> None:
    slot = LatestSlot()
    slot.put(Message(type="core.object", payload=1, sequence=1))
    slot.put(Message(type="core.object", payload=2, sequence=2))
    version, message = slot.wait_next(0)
    assert version == 2
    assert message is not None and message.sequence == 2
    assert slot.overwritten == 1


def test_vision_template_exports_compressed_preview(tmp_path: Path) -> None:
    project = tmp_path / "camera-app"
    create_project(project, "vision")
    manifest = (project / "pipeline.yaml").read_text(encoding="utf-8")
    readme = (project / "README.md").read_text(encoding="utf-8")

    if "blocks/outputs/jpeg-preview.yaml" in manifest:
        preview = (
            project / "blocks/outputs/jpeg-preview.yaml"
        ).read_text(encoding="utf-8")
        assert "vision.jpeg_encoder" in preview
        assert "/camera-app/preview" in manifest
        assert "preview_encoder.frame" in manifest
        assert "nodrix-viewer /camera-app/preview" in readme
        return

    assert "blocks/outputs/h264.yaml" in manifest
    encoder = (
        project / "blocks/outputs/h264.yaml"
    ).read_text(encoding="utf-8")
    assert "media.ffmpeg_encoder" in encoder
    assert "/camera-app/preview/h264" in manifest
    assert "encoder.encoded" in manifest
    assert "nodrix-viewer nodrix://DEVICE_IP:7420/camera-app/preview/h264 --overlay" in readme


def test_headless_viewer_reads_local_video(tmp_path: Path) -> None:
    path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20.0, (64, 48))
    assert writer.isOpened()
    for index in range(8):
        frame = np.full((48, 64, 3), index * 20, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    report = run_viewer(
        str(path),
        headless=True,
        overlay=False,
        max_frames=4,
        realtime_file=True,
    )
    assert report["displayed"] == 4
    assert report["decode_errors"] == 0


def test_headless_viewer_reads_nodrix_jpeg_stream() -> None:
    from nodrix.streams import StreamServer
    import time

    server = StreamServer(host="127.0.0.1")
    server.register("/viewer/preview", "vision.encoded_frame", capacity=1, policy="latest")
    server.start()

    def publish() -> None:
        time.sleep(0.1)
        for sequence in range(12):
            image = np.full((36, 48, 3), sequence * 10, dtype=np.uint8)
            ok, data = cv2.imencode(".jpg", image)
            assert ok
            payload = EncodedFrame(
                ManagedBuffer.wrap(data, readonly=True),
                MediaCodec.JPEG,
                width=48,
                height=36,
                fps=30.0,
                pts_ns=time.time_ns(),
            )
            server.publish(
                "/viewer/preview",
                Message(
                    type="vision.encoded_frame",
                    payload=payload,
                    sequence=sequence,
                    timestamp_ns=time.time_ns(),
                ),
            )
            time.sleep(0.02)

    thread = threading.Thread(target=publish)
    thread.start()
    try:
        report = run_viewer(
            f"nodrix://127.0.0.1:{server.port}/viewer/preview",
            headless=True,
            overlay=False,
            max_frames=5,
        )
        assert report["displayed"] == 5
        assert report["decode_errors"] == 0
    finally:
        thread.join(timeout=2)
        server.close()


def test_overlay_prepares_readonly_frame_without_mutating_source() -> None:
    source = np.zeros((8, 8, 3), dtype=np.uint8)
    source.flags.writeable = False
    prepared = _prepare_overlay_frame(source)
    assert prepared.flags.writeable
    assert prepared is not source
    prepared[0, 0] = 255
    assert int(source[0, 0, 0]) == 0
