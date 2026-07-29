from __future__ import annotations

from pathlib import Path

import numpy as np

from nodrix import Message
from nodrix.cv_types import EncodedFrame, Frame, ManagedBuffer, MediaCodec, PixelFormat
from nodrix.media import EncodedWriter, FFmpegSource, FFmpegWriter, media_doctor, probe_media
from nodrix.node import NodeContext
from nodrix.project_templates import create_project


def test_init_without_template_is_empty_skeleton(tmp_path: Path) -> None:
    project = tmp_path / "empty"
    create_project(project)
    assert (project / "pipeline.yaml").exists()
    assert list((project / "nodes").glob("*.py")) == [project / "nodes" / "__init__.py"]
    assert not (project / "nodes" / "source.py").exists()
    assert "nodes: {}" in (project / "pipeline.yaml").read_text(encoding="utf-8")


def test_media_template_is_populated(tmp_path: Path) -> None:
    project = tmp_path / "media-app"
    create_project(project, "media")
    manifest = (project / "pipeline.yaml").read_text(encoding="utf-8")
    assert "media.ffmpeg_source" in manifest
    assert "media.ffmpeg_encoder" in manifest
    assert "media.encoded_writer" in manifest
    assert "/media-app/h264" in manifest


def test_ffmpeg_doctor_and_lavfi_source(tmp_path: Path) -> None:
    report = media_doctor()
    assert "ffmpeg version" in report["ffmpeg"]
    context = NodeContext("source", tmp_path, tmp_path, "realtime")
    source = FFmpegSource({
        "uri": "lavfi:testsrc=size=64x48:rate=20",
        "width": 64,
        "height": 48,
        "fps": 20,
        "max_frames": 3,
    })
    source.open(context)
    try:
        messages = list(source.produce())
    finally:
        source.close()
    assert len(messages) == 3
    assert messages[0]["frame"].payload.numpy().shape == (48, 64, 3)


def test_ffmpeg_h264_writer_and_probe(tmp_path: Path) -> None:
    context = NodeContext("writer", tmp_path, tmp_path, "offline")
    writer = FFmpegWriter({"path": "result.mp4", "codec": "h264", "fps": 15, "preset": "ultrafast"})
    writer.open(context)
    for sequence in range(6):
        image = np.full((48, 64, 3), sequence * 20, dtype=np.uint8)
        frame = Frame.from_numpy(image, pixel_format=PixelFormat.BGR8)
        writer.process({"frame": Message(type="vision.frame", payload=frame, sequence=sequence, metadata={"fps": 15})})
    writer.close()
    path = tmp_path / "result.mp4"
    assert path.exists() and path.stat().st_size > 0
    info = probe_media(str(path))
    assert info["video"]["codec"] == "h264"
    assert info["video"]["width"] == 64


def test_encoded_writer_does_not_reencode(tmp_path: Path) -> None:
    context = NodeContext("encoded", tmp_path, tmp_path, "offline")
    writer = EncodedWriter({"path": "stream.h264", "codec": "h264"})
    writer.open(context)
    payload = EncodedFrame(ManagedBuffer.wrap(b"\x00\x00\x00\x01payload"), MediaCodec.H264, 64, 48)
    writer.process({"frame": Message(type="vision.encoded_frame", payload=payload)})
    writer.close()
    assert (tmp_path / "stream.h264").read_bytes() == b"\x00\x00\x00\x01payload"
