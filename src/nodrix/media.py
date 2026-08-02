from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import os
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


class _BinaryPipeCollector:
    """Drain a subprocess pipe on a thread so Windows does not need select()."""

    def __init__(self, pipe: Any, chunk_size: int) -> None:
        self.pipe = pipe
        self.chunk_size = max(1, int(chunk_size))
        self.chunks: deque[bytes] = deque()
        self.condition = threading.Condition()
        self.closed = False
        self.thread = threading.Thread(
            target=self._read,
            name="nodrix-ffmpeg-stdout",
            daemon=True,
        )
        self.thread.start()

    def _read(self) -> None:
        try:
            while self.pipe is not None:
                chunk = os.read(self.pipe.fileno(), self.chunk_size)
                if not chunk:
                    break
                with self.condition:
                    self.chunks.append(chunk)
                    self.condition.notify_all()
        except (OSError, ValueError):
            pass
        finally:
            with self.condition:
                self.closed = True
                self.condition.notify_all()

    def drain(self, timeout: float) -> bytes:
        with self.condition:
            if not self.chunks and not self.closed and timeout > 0:
                self.condition.wait_for(
                    lambda: bool(self.chunks) or self.closed,
                    timeout=timeout,
                )
            chunks = tuple(self.chunks)
            self.chunks.clear()
        return b"".join(chunks)

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
            raise MediaError('NumPy is required. Install with: pip install "plyctl[media]"')
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

    def runtime_info(self) -> dict[str, Any]:
        return {
            "backend": "ffmpeg",
            "source": self.reader.uri,
            "width": self.reader.width,
            "height": self.reader.height,
            "fps": self.reader.fps,
            "hardware": False,
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


def _encoder_candidates(codec: str, *, include_software: bool = True) -> list[str]:
    """Return hardware-first FFmpeg encoder candidates for this platform.

    Runtime probing remains authoritative: an encoder being compiled into
    FFmpeg does not prove that a device, driver, firmware, or permission is
    usable on the current host.
    """

    normalized = codec.lower().replace("hevc", "h265")
    h264 = normalized in {"h264", "avc"}
    prefix = "h264" if h264 else "hevc"
    candidates: list[str] = []
    machine = platform.machine().lower()
    system = platform.system().lower()

    if system == "darwin":
        candidates.append(f"{prefix}_videotoolbox")
    elif system == "windows":
        candidates.extend(
            [
                f"{prefix}_nvenc",
                f"{prefix}_qsv",
                f"{prefix}_amf",
            ]
        )
    elif system == "linux":
        # Platform media engines first on embedded ARM, then discrete/integrated
        # GPU backends. Unknown encoders are discarded before probing.
        if machine in {"aarch64", "arm64", "armv7l"}:
            candidates.extend(
                [
                    f"{prefix}_v4l2m2m",
                    f"{prefix}_rkmpp",
                    f"{prefix}_nvmpi",
                ]
            )
        candidates.extend(
            [
                f"{prefix}_nvenc",
                f"{prefix}_qsv",
                f"{prefix}_vaapi",
            ]
        )

    # Keep order deterministic while removing aliases duplicated by a platform.
    candidates = list(dict.fromkeys(candidates))
    if include_software:
        candidates.append(_software_encoder(codec))
    return candidates


def is_hardware_encoder(encoder: str, codec: str = "h264") -> bool:
    return encoder != _software_encoder(codec) and encoder not in {"mjpeg", "jpeg"}


def _vaapi_device() -> str | None:
    explicit = os.environ.get("NODRIX_VAAPI_DEVICE")
    if explicit:
        return explicit if Path(explicit).exists() else None
    dri = Path("/dev/dri")
    if not dri.is_dir():
        return None
    render_nodes = sorted(dri.glob("renderD*"))
    return str(render_nodes[0]) if render_nodes else None


def _encoder_backend_arguments(
    encoder: str,
    *,
    quality: int = 23,
    keyint: int = 30,
) -> tuple[list[str], list[str], list[str], str | None]:
    """Return FFmpeg arguments for a concrete encoder backend.

    The tuple is ``(before_input, before_codec, after_codec, pixel_format)``.
    Keeping this in one adapter prevents a backend from passing a simplistic
    probe and then failing under the real persistent encoder command.
    """

    before_input: list[str] = []
    before_codec: list[str] = []
    after_codec: list[str] = []
    pixel_format: str | None = "yuv420p"

    if encoder.endswith("_vaapi"):
        device = _vaapi_device()
        if device is None:
            raise MediaError(
                "VAAPI encoder is present in FFmpeg but no /dev/dri/renderD* device is accessible; "
                "set NODRIX_VAAPI_DEVICE when using a non-default render node"
            )
        before_input += ["-vaapi_device", device]
        before_codec += ["-vf", "format=nv12,hwupload"]
        after_codec += ["-qp", str(int(quality))]
        pixel_format = None  # Frames are VAAPI surfaces after hwupload.
    elif encoder.endswith("_videotoolbox"):
        # Prevent VideoToolbox from silently switching back to software.
        after_codec += ["-allow_sw", "0", "-realtime", "1"]
    elif encoder.endswith("_nvenc"):
        after_codec += ["-preset", "p1", "-tune", "ull", "-bf", "0"]
    elif encoder.endswith("_qsv"):
        after_codec += ["-preset", "veryfast", "-bf", "0"]
        pixel_format = "nv12"
    elif encoder.endswith("_amf"):
        after_codec += ["-usage", "ultralowlatency", "-quality", "speed", "-bf", "0"]
    elif encoder.endswith("_v4l2m2m"):
        after_codec += ["-bf", "0"]
    elif encoder.endswith("_rkmpp"):
        pixel_format = "nv12"
    elif encoder.endswith("_nvmpi"):
        after_codec += ["-bf", "0"]

    if keyint > 0 and encoder not in {"libx264", "libx265"}:
        after_codec += ["-g", str(int(keyint))]
    return before_input, before_codec, after_codec, pixel_format


def _encoder_command_prefix(
    encoder: str,
    codec: str,
    *,
    width: int,
    height: int,
    fps: float,
    quality: int = 23,
    keyint: int = 30,
    overwrite: bool = False,
) -> tuple[list[str], list[str], str | None]:
    before_input, before_codec, after_codec, pixel_format = _encoder_backend_arguments(
        encoder,
        quality=quality,
        keyint=keyint,
    )
    command = [
        _binary("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        *(["-y"] if overwrite else []),
        *before_input,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s:v",
        f"{int(width)}x{int(height)}",
        "-r",
        f"{float(fps):g}",
        "-i",
        "pipe:0",
        "-an",
        *before_codec,
        "-c:v",
        encoder,
    ]
    return command, after_codec, pixel_format


def probe_encoder(encoder: str, codec: str, timeout: float = 6.0) -> tuple[bool, str]:
    if encoder not in available_encoders():
        return False, "encoder is not listed by FFmpeg"
    try:
        command, backend_options, pixel_format = _encoder_command_prefix(
            encoder,
            codec,
            width=64,
            height=64,
            fps=5.0,
            quality=23,
            keyint=5,
        )
    except (MediaError, OSError) as exc:
        return False, str(exc)
    if encoder in {"libx264", "libx265"}:
        command += ["-preset", "ultrafast", "-tune", "zerolatency"]
    command += backend_options
    if pixel_format:
        command += ["-pix_fmt", pixel_format]
    command += ["-frames:v", "2", "-f", "null", "-"]
    try:
        # Two raw BGR frames exercise the same CPU-to-encoder path as runtime.
        frame_bytes = bytes(64 * 64 * 3 * 2)
        result = subprocess.run(
            command,
            input=frame_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    detail_bytes = (result.stderr or b"").strip().splitlines()
    detail = detail_bytes[-1].decode("utf-8", errors="replace") if detail_bytes else "probe passed"
    return result.returncode == 0, detail


@lru_cache(maxsize=32)
def select_encoder(
    codec: str,
    requested: str | None = None,
    acceleration: str = "preferred",
) -> dict[str, Any]:
    """Select an encoder with an explicit hardware acceleration policy.

    ``required`` never falls back to a software encoder. ``preferred`` keeps
    compatibility but reports the fallback. ``disabled`` selects software
    intentionally. Generated Vision projects use hardware-first ``preferred``
    so platforms without an encoder remain usable without a hidden fallback.
    """

    policy = str(acceleration).lower()
    if policy not in {"required", "preferred", "disabled"}:
        raise ValueError("acceleration must be required, preferred, or disabled")
    selected_request = str(requested or "auto")
    software = _software_encoder(codec)
    attempts: list[dict[str, Any]] = []

    if selected_request != "auto":
        hardware = is_hardware_encoder(selected_request, codec)
        if policy == "required" and not hardware:
            return {
                "ok": False,
                "selected": None,
                "requested": selected_request,
                "hardware": False,
                "acceleration": policy,
                "reason": f"software encoder {selected_request} is forbidden by acceleration: required",
                "attempts": attempts,
            }
        ok, reason = probe_encoder(selected_request, codec)
        attempts.append({"encoder": selected_request, "ok": ok, "reason": reason})
        return {
            "ok": ok,
            "selected": selected_request if ok else None,
            "requested": selected_request,
            "hardware": hardware,
            "acceleration": policy,
            "reason": reason if ok else f"explicit encoder probe failed: {reason}",
            "attempts": attempts,
        }

    if policy != "disabled":
        for candidate in [item for item in _encoder_candidates(codec) if item != software]:
            ok, reason = probe_encoder(candidate, codec)
            attempts.append({"encoder": candidate, "ok": ok, "reason": reason})
            if ok:
                return {
                    "ok": True,
                    "selected": candidate,
                    "requested": "auto",
                    "hardware": True,
                    "acceleration": policy,
                    "reason": f"hardware probe passed for {candidate}",
                    "fallback": None,
                    "attempts": attempts,
                }

    if policy == "required":
        return {
            "ok": False,
            "selected": None,
            "requested": "auto",
            "hardware": False,
            "acceleration": policy,
            "reason": "no hardware encoder passed the runtime probe; software fallback is disabled",
            "fallback": None,
            "attempts": attempts,
        }

    ok, reason = probe_encoder(software, codec)
    attempts.append({"encoder": software, "ok": ok, "reason": reason})
    return {
        "ok": ok,
        "selected": software if ok else None,
        "requested": "auto",
        "hardware": False,
        "acceleration": policy,
        "reason": (
            "hardware probes failed; explicit preferred policy selected software fallback"
            if policy == "preferred" and ok
            else reason
        ),
        "fallback": software if ok else None,
        "attempts": attempts,
    }


def _codec_encoder(
    codec: str,
    explicit: str | None = None,
    acceleration: str = "preferred",
) -> tuple[str, dict[str, Any]]:
    selection = select_encoder(codec, explicit, acceleration)
    selected = selection.get("selected")
    if not selection.get("ok") or not selected:
        attempts = "; ".join(
            f"{item.get('encoder')}: {item.get('reason')}"
            for item in selection.get("attempts", [])
        )
        detail = f" ({attempts})" if attempts else ""
        raise MediaError(f"Cannot select {codec} encoder: {selection.get('reason')}{detail}")
    return str(selected), selection


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
        self.acceleration = str(self.parameters.get("acceleration", "preferred"))
        self.encoder, self.encoder_selection = _codec_encoder(
            self.codec, self.parameters.get("encoder"), self.acceleration
        )
        self.preset = str(self.parameters.get("preset", "ultrafast"))
        self.tune = str(self.parameters.get("tune", "zerolatency"))
        self.crf = int(self.parameters.get("crf", 23))
        self.bitrate = str(self.parameters.get("bitrate", ""))
        pixel_format = self.parameters.get("pixel_format")
        self.output_pixel_format = None if pixel_format in {None, "", "auto"} else str(pixel_format)
        self.fps = float(self.parameters.get("fps", 0.0))
        self.keyint = int(self.parameters.get("keyint", 30))
        self._process: subprocess.Popen[bytes] | None = None
        self.stderr: _StderrCollector | None = None
        self.stdout: _BinaryPipeCollector | None = None
        self.shape: tuple[int, int] | None = None
        self.frames = 0

    def _start(self, frame: Frame, message: Message) -> None:
        if frame.pixel_format != PixelFormat.BGR8 or frame.dtype != "uint8" or (frame.channels or 3) != 3:
            raise MediaError("media.ffmpeg_writer currently requires BGR8 uint8 frames for zero-copy input")
        fps = self.fps or float(message.metadata.get("fps", 0.0) or 30.0)
        self.fps = fps
        self.shape = (frame.width, frame.height)
        command, backend_options, backend_pixel_format = _encoder_command_prefix(
            self.encoder,
            self.codec,
            width=frame.width,
            height=frame.height,
            fps=fps,
            quality=self.crf,
            keyint=self.keyint,
            overwrite=True,
        )
        if self.encoder in {"libx264", "libx265"}:
            command += ["-preset", self.preset, "-tune", self.tune, "-crf", str(self.crf)]
            if self.keyint > 0:
                command += ["-g", str(self.keyint), "-bf", "0"]
        command += backend_options
        if self.bitrate:
            command += ["-b:v", self.bitrate]
        selected_pixel_format = self.output_pixel_format or backend_pixel_format
        if selected_pixel_format:
            command += ["-pix_fmt", selected_pixel_format]
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
    """Persistent FFmpeg H.264/H.265 encoder producing Plyctl byte chunks.

    Output messages are Annex-B chunks. They are deliberately not required to
    match one frame or one NAL unit; the stateful Plyctl Viewer decoder accepts
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
        self.acceleration = str(self.parameters.get("acceleration", "preferred"))
        self.encoder, self.encoder_selection = _codec_encoder(
            self.codec, self.parameters.get("encoder"), self.acceleration
        )
        self.preset = str(self.parameters.get("preset", "ultrafast"))
        self.tune = str(self.parameters.get("tune", "zerolatency"))
        self.crf = int(self.parameters.get("crf", 23))
        self.bitrate = str(self.parameters.get("bitrate", ""))
        self.fps = float(self.parameters.get("fps", 0.0))
        self.keyint = int(self.parameters.get("keyint", 30))
        self.read_timeout = float(self.parameters.get("read_timeout_ms", 10.0)) / 1000.0
        self.chunk_size = int(self.parameters.get("chunk_size", 1024 * 1024))
        pixel_format = self.parameters.get("pixel_format")
        self.output_pixel_format = None if pixel_format in {None, "", "auto"} else str(pixel_format)
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
        command, backend_options, backend_pixel_format = _encoder_command_prefix(
            self.encoder,
            self.codec,
            width=frame.width,
            height=frame.height,
            fps=self.fps,
            quality=self.crf,
            keyint=self.keyint,
        )
        if self.encoder in {"libx264", "libx265"}:
            command += ["-preset", self.preset, "-tune", self.tune, "-crf", str(self.crf)]
            if self.keyint > 0:
                command += ["-g", str(self.keyint), "-bf", "0"]
            if self.encoder == "libx264":
                command += ["-x264-params", "repeat-headers=1:aud=1"]
            else:
                command += ["-x265-params", "repeat-headers=1:aud=1"]
        command += backend_options
        if self.bitrate:
            command += ["-b:v", self.bitrate]
        selected_pixel_format = self.output_pixel_format or backend_pixel_format
        if selected_pixel_format:
            command += ["-pix_fmt", selected_pixel_format]
        command += ["-f", muxer, "pipe:1"]
        self._process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
        )
        assert self._process.stdout is not None
        self.stdout = _BinaryPipeCollector(
            self._process.stdout,
            self.chunk_size,
        )
        self.stderr = _StderrCollector(self._process.stderr)

    def _drain(self, timeout: float) -> bytes:
        if self.stdout is None:
            return b""
        return self.stdout.drain(timeout)

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
        if self.stdout is not None:
            self.stdout.join()
        return self._message(self._drain(0.0), self.last_source)

    def runtime_info(self) -> dict[str, Any]:
        selection = dict(getattr(self, "encoder_selection", {}))
        return {
            "backend": getattr(self, "encoder", None),
            "hardware": bool(selection.get("hardware", False)),
            "acceleration": getattr(self, "acceleration", "preferred"),
            "codec": getattr(self, "codec", None),
            "reason": selection.get("reason"),
        }

    def close(self) -> None:
        if self._process is None:
            return
        process = self._process
        self._process = None
        requested_shutdown = False
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()
                requested_shutdown = True
            except (BrokenPipeError, OSError):
                requested_shutdown = True
        if process.poll() is None:
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                requested_shutdown = True
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
        if self.stderr is not None:
            self.stderr.join()
        if self.stdout is not None:
            self.stdout.join()
        detail = self.stderr.text() if self.stderr else ""
        return_code = process.returncode
        if process.stdout is not None:
            process.stdout.close()
        self.stdout = None
        if process.stderr is not None:
            process.stderr.close()
        # FFmpeg may return 255/negative signal codes when the runtime closes
        # its pipes during a user-requested shutdown. Do not turn Ctrl+C into
        # a failed pipeline; non-zero exits during normal processing are still
        # reported by process().
        if return_code not in {0, None} and not requested_shutdown:
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
