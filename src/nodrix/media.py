from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import os
import select
from functools import lru_cache
from pathlib import Path
import platform
import shutil
import subprocess
import threading
import time
from typing import Any, Iterator, Mapping

from .cv_types import EncodedFrame, Frame, ManagedBuffer, MediaCodec, PixelFormat
from .messages import Message
from .node import Node, NodeContext, SinkNode, SourceNode
from .registry import register_builtin

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None


class MediaError(RuntimeError):
    pass


def _binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise MediaError(f"{name} is not installed or is not available in PATH")
    return path


def _rational(value: str | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        den = float(denominator)
        return float(numerator) / den if den else 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def normalize_media_uri(uri: Any, project_dir: Path | None = None) -> str:
    if isinstance(uri, int):
        return str(uri)
    text = str(uri)
    if "://" in text or text.startswith("lavfi:") or text.startswith("/dev/"):
        return text
    path = Path(text).expanduser()
    if not path.is_absolute() and project_dir is not None:
        path = project_dir / path
    return str(path.resolve())


def ffmpeg_version() -> str:
    result = subprocess.run(
        [_binary("ffmpeg"), "-version"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()[0] if result.stdout else "ffmpeg"


def ffprobe_version() -> str:
    result = subprocess.run(
        [_binary("ffprobe"), "-version"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()[0] if result.stdout else "ffprobe"


def probe_media(uri: str, *, input_format: str | None = None, timeout: float = 15.0) -> dict[str, Any]:
    command = [_binary("ffprobe"), "-v", "error"]
    if input_format:
        command += ["-f", input_format]
    command += ["-show_streams", "-show_format", "-of", "json", uri]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffprobe timed out for {uri}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise MediaError(f"ffprobe failed for {uri}: {detail}") from exc
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    summary: dict[str, Any] = {
        "uri": uri,
        "format": data.get("format", {}),
        "streams": streams,
        "video": None,
        "audio": None,
    }
    if video:
        summary["video"] = {
            "index": video.get("index"),
            "codec": video.get("codec_name"),
            "profile": video.get("profile"),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "pixel_format": video.get("pix_fmt"),
            "fps": _rational(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            "time_base": video.get("time_base"),
            "duration": _rational(video.get("duration")),
            "bit_rate": int(video.get("bit_rate") or 0),
        }
    if audio:
        summary["audio"] = {
            "index": audio.get("index"),
            "codec": audio.get("codec_name"),
            "sample_rate": int(audio.get("sample_rate") or 0),
            "channels": int(audio.get("channels") or 0),
            "bit_rate": int(audio.get("bit_rate") or 0),
        }
    return summary


def available_encoders() -> set[str]:
    result = subprocess.run(
        [_binary("ffmpeg"), "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
    )
    encoders: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) >= 1 and parts[0][0] in {"V", "A", "S", "."}:
            encoders.add(parts[1])
    return encoders


def media_doctor() -> dict[str, Any]:
    encoders = available_encoders()
    candidates = [
        "libx264",
        "libx265",
        "h264_v4l2m2m",
        "hevc_v4l2m2m",
        "h264_nvenc",
        "hevc_nvenc",
        "h264_videotoolbox",
        "hevc_videotoolbox",
        "h264_vaapi",
        "hevc_vaapi",
    ]
    return {
        "ffmpeg": ffmpeg_version(),
        "ffprobe": ffprobe_version(),
        "encoders": {name: name in encoders for name in candidates},
    }


class _StderrCollector:
    def __init__(self, pipe: Any, limit: int = 100) -> None:
        self.pipe = pipe
        self.lines: deque[str] = deque(maxlen=limit)
        self.thread = threading.Thread(target=self._read, name="nodrix-ffmpeg-stderr", daemon=True)
        self.thread.start()

    def _read(self) -> None:
        if self.pipe is None:
            return
        try:
            for raw in iter(self.pipe.readline, b""):
                self.lines.append(raw.decode("utf-8", errors="replace").rstrip())
        except Exception:
            return

    def text(self) -> str:
        return "\n".join(self.lines)

    def join(self, timeout: float = 1.0) -> None:
        self.thread.join(timeout=timeout)


def _read_exact(stream: Any, size: int) -> bytearray | None:
    data = bytearray(size)
    view = memoryview(data)
    offset = 0
    while offset < size:
        read = stream.readinto(view[offset:])
        if read is None:
            continue
        if read == 0:
            return None if offset == 0 else None
        offset += read
    return data


@dataclass(slots=True)
class FFmpegFrameReader:
    uri: str
    width: int = 0
    height: int = 0
    fps: float = 0.0
    input_format: str | None = None
    rtsp_transport: str = "tcp"
    realtime: bool = False
    low_latency: bool = True
    project_dir: Path | None = None
    process: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    stderr: _StderrCollector | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.uri = normalize_media_uri(self.uri, self.project_dir)

    def open(self) -> None:
        if np is None:
            raise MediaError('NumPy is required. Install with: pip install "nodrix[media]"')
        source = self.uri
        if source.startswith("lavfi:"):
            self.input_format = "lavfi"
            source = source.removeprefix("lavfi:")
        if not self.width or not self.height or not self.fps:
            if self.input_format == "lavfi":
                if not self.width or not self.height or not self.fps:
                    raise MediaError("lavfi sources require width, height, and fps parameters")
            else:
                info = probe_media(source, input_format=self.input_format)
                video = info.get("video") or {}
                self.width = self.width or int(video.get("width") or 0)
                self.height = self.height or int(video.get("height") or 0)
                self.fps = self.fps or float(video.get("fps") or 0.0)
        if self.width <= 0 or self.height <= 0:
            raise MediaError(f"Cannot determine source dimensions for {self.uri}")

        command = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
        if self.realtime and (self.input_format == "lavfi" or "://" not in source):
            command += ["-re"]
        if self.low_latency:
            command += ["-fflags", "nobuffer", "-flags", "low_delay", "-probesize", "64k", "-analyzeduration", "0"]
        if source.startswith("rtsp://"):
            command += ["-rtsp_transport", self.rtsp_transport]
        if self.input_format:
            command += ["-f", self.input_format]
        command += ["-i", source, "-map", "0:v:0", "-an", "-sn", "-dn", "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert self.process.stdout is not None
        self.stderr = _StderrCollector(self.process.stderr)

    def frames(self) -> Iterator[Any]:
        if self.process is None:
            self.open()
        assert self.process is not None and self.process.stdout is not None
        frame_bytes = self.width * self.height * 3
        while True:
            storage = _read_exact(self.process.stdout, frame_bytes)
            if storage is None:
                break
            yield np.frombuffer(storage, dtype=np.uint8).reshape((self.height, self.width, 3))
        return_code = self.process.poll()
        if return_code not in (None, 0) and self.stderr is not None:
            detail = self.stderr.text()
            raise MediaError(f"ffmpeg decoder exited with code {return_code}: {detail}")

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1.0)
        if self.process.stdout is not None:
            self.process.stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()
        if self.stderr is not None:
            self.stderr.join()
        self.process = None


@register_builtin("media.ffmpeg_source")
class FFmpegSource(SourceNode):
    output_types = {"frame": "vision.frame"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        uri = self.parameters.get("uri", self.parameters.get("source", ""))
        if uri == "":
            raise ValueError("media.ffmpeg_source requires parameters.uri")
        self.reader = FFmpegFrameReader(
            uri=str(uri),
            width=int(self.parameters.get("width", 0)),
            height=int(self.parameters.get("height", 0)),
            fps=float(self.parameters.get("fps", 0.0)),
            input_format=self.parameters.get("format"),
            rtsp_transport=str(self.parameters.get("rtsp_transport", "tcp")),
            realtime=bool(self.parameters.get("realtime", False)),
            low_latency=bool(self.parameters.get("low_latency", True)),
            project_dir=context.project_dir,
        )
        self.reader.open()
        self.limit = int(self.parameters.get("max_frames", 0))

    def produce(self):
        for sequence, array in enumerate(self.reader.frames()):
            if self.limit > 0 and sequence >= self.limit:
                break
            yield {
                "frame": Message(
                    type="vision.frame",
                    payload=Frame.from_numpy(array, pixel_format=PixelFormat.BGR8, readonly=True),
                    sequence=sequence,
                    timestamp_ns=time.time_ns(),
                    trace_id=sequence,
                    metadata={
                        "source": self.reader.uri,
                        "width": self.reader.width,
                        "height": self.reader.height,
                        "fps": self.reader.fps,
                        "decoder": "ffmpeg",
                    },
                )
            }

    def close(self) -> None:
        self.reader.close()


def _software_encoder(codec: str) -> str:
    normalized = codec.lower().replace("hevc", "h265")
    if normalized in {"h264", "avc"}:
        return "libx264"
    if normalized in {"h265", "hevc"}:
        return "libx265"
    if normalized in {"mjpeg", "jpeg"}:
        return "mjpeg"
    return codec


def _encoder_candidates(codec: str) -> list[str]:
    normalized = codec.lower().replace("hevc", "h265")
    h264 = normalized in {"h264", "avc"}
    prefix = "h264" if h264 else "hevc"
    candidates: list[str] = []
    machine = platform.machine().lower()
    system = platform.system().lower()
    if system == "darwin":
        candidates.append(f"{prefix}_videotoolbox")
    if system == "linux":
        if machine in {"aarch64", "arm64", "armv7l"}:
            candidates.append(f"{prefix}_v4l2m2m")
        candidates.extend([f"{prefix}_nvenc", f"{prefix}_vaapi"])
    candidates.append(_software_encoder(codec))
    return candidates


def probe_encoder(encoder: str, codec: str, timeout: float = 6.0) -> tuple[bool, str]:
    if encoder not in available_encoders():
        return False, "encoder is not listed by FFmpeg"
    command = [
        _binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "color=size=64x64:rate=5:color=black",
        "-frames:v", "2", "-an", "-c:v", encoder,
    ]
    if encoder in {"libx264", "libx265"}:
        command += ["-preset", "ultrafast", "-tune", "zerolatency"]
    command += ["-f", "null", "-"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    detail = (result.stderr or "").strip().splitlines()
    return result.returncode == 0, (detail[-1] if detail else "probe passed")


@lru_cache(maxsize=16)
def select_encoder(codec: str, requested: str | None = None) -> dict[str, Any]:
    if requested is None:
        selected = _software_encoder(codec)
        return {"selected": selected, "requested": "default", "reason": "built-in software default", "fallback": None}
    if requested != "auto":
        return {"selected": requested, "requested": requested, "reason": "explicit pipeline setting", "fallback": None}
    candidates = _encoder_candidates(codec)
    attempts: list[dict[str, Any]] = []
    for candidate in candidates:
        ok, reason = probe_encoder(candidate, codec)
        attempts.append({"encoder": candidate, "ok": ok, "reason": reason})
        if ok:
            return {
                "selected": candidate,
                "requested": requested or "default",
                "reason": f"runtime probe passed for {candidate}",
                "fallback": _software_encoder(codec) if candidate != _software_encoder(codec) else None,
                "attempts": attempts,
            }
    fallback = _software_encoder(codec)
    return {
        "selected": fallback, "requested": requested or "default",
        "reason": "all hardware probes failed; using software fallback",
        "fallback": fallback, "attempts": attempts,
    }


def _codec_encoder(codec: str, explicit: str | None = None) -> str:
    return str(select_encoder(codec, explicit).get("selected"))


@register_builtin("media.ffmpeg_writer")
class FFmpegWriter(SinkNode):
    input_types = {"frame": "vision.frame"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        configured = Path(str(self.parameters.get("path", "output.mp4"))).expanduser()
        if not configured.is_absolute():
            configured = context.run_dir / configured
        configured.parent.mkdir(parents=True, exist_ok=True)
        self.path = configured
        self.codec = str(self.parameters.get("codec", "h264"))
        self.encoder = _codec_encoder(self.codec, self.parameters.get("encoder"))
        self.preset = str(self.parameters.get("preset", "ultrafast"))
        self.tune = str(self.parameters.get("tune", "zerolatency"))
        self.crf = int(self.parameters.get("crf", 23))
        self.bitrate = str(self.parameters.get("bitrate", ""))
        self.output_pixel_format = str(self.parameters.get("pixel_format", "yuv420p"))
        self.fps = float(self.parameters.get("fps", 0.0))
        self.keyint = int(self.parameters.get("keyint", 30))
        self._process: subprocess.Popen[bytes] | None = None
        self.stderr: _StderrCollector | None = None
        self.shape: tuple[int, int] | None = None
        self.frames = 0

    def _start(self, frame: Frame, message: Message) -> None:
        if frame.pixel_format != PixelFormat.BGR8 or frame.dtype != "uint8" or (frame.channels or 3) != 3:
            raise MediaError("media.ffmpeg_writer currently requires BGR8 uint8 frames for zero-copy input")
        fps = self.fps or float(message.metadata.get("fps", 0.0) or 30.0)
        self.fps = fps
        self.shape = (frame.width, frame.height)
        command = [
            _binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s:v", f"{frame.width}x{frame.height}",
            "-r", f"{fps:g}", "-i", "pipe:0", "-an", "-c:v", self.encoder,
        ]
        if self.encoder in {"libx264", "libx265"}:
            command += ["-preset", self.preset, "-tune", self.tune, "-crf", str(self.crf)]
            if self.keyint > 0:
                command += ["-g", str(self.keyint), "-bf", "0"]
        if self.bitrate:
            command += ["-b:v", self.bitrate]
        if self.output_pixel_format:
            command += ["-pix_fmt", self.output_pixel_format]
        if self.path.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            command += ["-movflags", "+faststart"]
        command += [str(self.path)]
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert self._process.stdin is not None
        self.stderr = _StderrCollector(self._process.stderr)

    def process(self, inputs: Mapping[str, Message]):
        message = inputs["frame"]
        frame = message.payload
        if not isinstance(frame, Frame):
            raise TypeError("media.ffmpeg_writer expects a nodrix.Frame payload")
        if self._process is None:
            self._start(frame, message)
        assert self._process is not None and self._process.stdin is not None
        if self.shape != (frame.width, frame.height):
            raise MediaError(f"Frame size changed from {self.shape} to {(frame.width, frame.height)}")
        if self._process.poll() is not None:
            detail = self.stderr.text() if self.stderr else ""
            raise MediaError(f"ffmpeg encoder stopped with code {self._process.returncode}: {detail}")
        try:
            self._process.stdin.write(frame.buffer.memoryview())
        except BrokenPipeError as exc:
            detail = self.stderr.text() if self.stderr else ""
            raise MediaError(f"ffmpeg encoder pipe closed: {detail}") from exc
        self.frames += 1
        return None

    def close(self) -> None:
        if self._process is None:
            return
        if self._process.stdin is not None and not self._process.stdin.closed:
            self._process.stdin.close()
        try:
            return_code = self._process.wait(timeout=15.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            return_code = self._process.wait(timeout=2.0)
        if self.stderr is not None:
            self.stderr.join()
        detail = self.stderr.text() if self.stderr else ""
        if self._process.stderr is not None:
            self._process.stderr.close()
        self._process = None
        if return_code != 0:
            raise MediaError(f"ffmpeg encoder exited with code {return_code}: {detail}")


@register_builtin("media.ffmpeg_encoder")
class FFmpegEncoder(Node):
    """Persistent FFmpeg H.264/H.265 encoder producing Nodrix byte chunks.

    Output messages are Annex-B chunks. They are deliberately not required to
    match one frame or one NAL unit; the stateful Nodrix Viewer decoder accepts
    arbitrary ordered chunks and therefore avoids an extra parser/copy in the
    encoder node.
    """

    input_types = {"frame": "vision.frame"}
    output_types = {"encoded": "vision.encoded_frame"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        self.codec = str(self.parameters.get("codec", "h264")).lower().replace("hevc", "h265")
        if self.codec not in {"h264", "h265"}:
            raise MediaError("media.ffmpeg_encoder supports h264 or h265")
        self.encoder = _codec_encoder(self.codec, self.parameters.get("encoder"))
        self.preset = str(self.parameters.get("preset", "ultrafast"))
        self.tune = str(self.parameters.get("tune", "zerolatency"))
        self.crf = int(self.parameters.get("crf", 23))
        self.bitrate = str(self.parameters.get("bitrate", ""))
        self.fps = float(self.parameters.get("fps", 0.0))
        self.keyint = int(self.parameters.get("keyint", 30))
        self.read_timeout = float(self.parameters.get("read_timeout_ms", 10.0)) / 1000.0
        self.chunk_size = int(self.parameters.get("chunk_size", 1024 * 1024))
        self.output_pixel_format = str(self.parameters.get("pixel_format", "yuv420p"))
        self._process: subprocess.Popen[bytes] | None = None
        self.stderr: _StderrCollector | None = None
        self.shape: tuple[int, int] | None = None
        self.output_sequence = 0
        self.last_source: Message | None = None

    def _start(self, frame: Frame, message: Message) -> None:
        if frame.pixel_format != PixelFormat.BGR8 or frame.dtype != "uint8" or (frame.channels or 3) != 3:
            raise MediaError("media.ffmpeg_encoder currently requires contiguous BGR8 uint8 frames")
        self.fps = self.fps or float(message.metadata.get("fps", 0.0) or 30.0)
        self.shape = (frame.width, frame.height)
        muxer = "h264" if self.codec == "h264" else "hevc"
        command = [
            _binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s:v", f"{frame.width}x{frame.height}",
            "-r", f"{self.fps:g}", "-i", "pipe:0", "-an", "-c:v", self.encoder,
        ]
        if self.encoder in {"libx264", "libx265"}:
            command += ["-preset", self.preset, "-tune", self.tune, "-crf", str(self.crf)]
            if self.keyint > 0:
                command += ["-g", str(self.keyint), "-bf", "0"]
            if self.encoder == "libx264":
                command += ["-x264-params", "repeat-headers=1:aud=1"]
            else:
                command += ["-x265-params", "repeat-headers=1:aud=1"]
        if self.bitrate:
            command += ["-b:v", self.bitrate]
        if self.output_pixel_format:
            command += ["-pix_fmt", self.output_pixel_format]
        command += ["-f", muxer, "pipe:1"]
        self._process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
        )
        assert self._process.stdout is not None
        os.set_blocking(self._process.stdout.fileno(), False)
        self.stderr = _StderrCollector(self._process.stderr)

    def _drain(self, timeout: float) -> bytes:
        if self._process is None or self._process.stdout is None:
            return b""
        fd = self._process.stdout.fileno()
        chunks: list[bytes] = []
        first = True
        while True:
            readable, _, _ = select.select([fd], [], [], timeout if first else 0.0)
            first = False
            if not readable:
                break
            try:
                chunk = os.read(fd, self.chunk_size)
            except BlockingIOError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def _message(self, data: bytes, source: Message) -> dict[str, Message] | None:
        if not data:
            return None
        codec = MediaCodec.H264 if self.codec == "h264" else MediaCodec.H265
        assert self.shape is not None
        width, height = self.shape
        encoded = EncodedFrame(
            ManagedBuffer.wrap(data, readonly=True), codec, width, height, self.fps,
            keyframe=(self.output_sequence == 0), pts_ns=source.timestamp_ns,
            metadata={"chunked": True, "encoder": self.encoder},
        )
        output = Message(
            type="vision.encoded_frame", payload=encoded, sequence=self.output_sequence,
            timestamp_ns=source.timestamp_ns, trace_id=source.trace_id,
            metadata={**source.metadata, "codec": codec.value, "chunked": True},
            created_ns=source.created_ns,
        )
        self.output_sequence += 1
        return {"encoded": output}

    def process(self, inputs: Mapping[str, Message]):
        source = inputs["frame"]
        frame = source.payload
        if not isinstance(frame, Frame):
            raise TypeError("media.ffmpeg_encoder expects Frame")
        if self._process is None:
            self._start(frame, source)
        assert self._process is not None and self._process.stdin is not None
        if self.shape != (frame.width, frame.height):
            raise MediaError(f"Frame size changed from {self.shape} to {(frame.width, frame.height)}")
        if self._process.poll() is not None:
            raise MediaError(f"ffmpeg encoder stopped: {self.stderr.text() if self.stderr else ''}")
        self._process.stdin.write(frame.buffer.memoryview())
        self._process.stdin.flush()
        self.last_source = source
        return self._message(self._drain(self.read_timeout), source)

    def flush(self):
        if self._process is None or self.last_source is None:
            return None
        if self._process.stdin is not None and not self._process.stdin.closed:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            self._process.wait(timeout=2.0)
        return self._message(self._drain(0.0), self.last_source)

    def close(self) -> None:
        if self._process is None:
            return
        if self._process.stdin is not None and not self._process.stdin.closed:
            self._process.stdin.close()
        if self._process.poll() is None:
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
        if self.stderr is not None:
            self.stderr.join()
        detail = self.stderr.text() if self.stderr else ""
        return_code = self._process.returncode
        self._process = None
        if return_code not in {0, None}:
            raise MediaError(f"ffmpeg encoder exited with code {return_code}: {detail}")


@register_builtin("media.encoded_writer")
class EncodedWriter(SinkNode):
    """Write already encoded access units without decoding or re-encoding."""

    input_types = {"frame": "vision.encoded_frame"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        configured = Path(str(self.parameters.get("path", "stream.bin"))).expanduser()
        if not configured.is_absolute():
            configured = context.run_dir / configured
        configured.parent.mkdir(parents=True, exist_ok=True)
        self.path = configured
        self.expected_codec = str(self.parameters.get("codec", "")).lower()
        self.handle = configured.open("wb", buffering=1024 * 1024)
        self.frames = 0
        self.bytes_written = 0

    def process(self, inputs: Mapping[str, Message]):
        payload = inputs["frame"].payload
        if not isinstance(payload, EncodedFrame):
            raise TypeError("media.encoded_writer expects EncodedFrame")
        if self.expected_codec and payload.codec.value != self.expected_codec:
            raise MediaError(f"Expected codec {self.expected_codec}, got {payload.codec.value}")
        view = payload.memoryview()
        self.handle.write(view)
        self.frames += 1
        self.bytes_written += view.nbytes
        return None

    def close(self) -> None:
        self.handle.close()


def run_ffmpeg_relay(
    source: str,
    output: str,
    *,
    copy: bool = True,
    codec: str = "h264",
    encoder: str | None = None,
    rtsp_transport: str = "tcp",
    duration: float = 0.0,
    overwrite: bool = True,
) -> int:
    command = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "warning", "-nostdin"]
    if overwrite:
        command.append("-y")
    if source.startswith("rtsp://"):
        command += ["-rtsp_transport", rtsp_transport]
    command += ["-i", source, "-map", "0:v:0", "-an"]
    if duration > 0:
        command += ["-t", f"{duration:g}"]
    if copy:
        command += ["-c:v", "copy"]
    else:
        chosen = _codec_encoder(codec, encoder)
        command += ["-c:v", chosen]
        if chosen in {"libx264", "libx265"}:
            command += ["-preset", "ultrafast", "-tune", "zerolatency", "-bf", "0"]
    command.append(output)
    return subprocess.run(command, check=False).returncode
