from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib.request import urlopen

import typer

from .cv_types import EncodedFrame, Frame, MediaCodec, PixelFormat
from .messages import Message
from .streams import StreamClient
from .media import FFmpegFrameReader, MediaError

try:
    import cv2
except Exception:  # pragma: no cover - optional dependency
    cv2 = None

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None


class ViewerError(RuntimeError):
    pass


@dataclass(slots=True)
class ViewerStats:
    received: int = 0
    displayed: int = 0
    overwritten: int = 0
    decode_errors: int = 0
    started_ns: int = 0
    last_sequence: int = 0
    last_latency_ms: float | None = None

    def as_dict(self) -> dict[str, Any]:
        elapsed = max((time.perf_counter_ns() - self.started_ns) / 1e9, 1e-9) if self.started_ns else 0.0
        return {
            "received": self.received,
            "displayed": self.displayed,
            "overwritten": self.overwritten,
            "decode_errors": self.decode_errors,
            "receive_fps": self.received / elapsed if elapsed else 0.0,
            "display_fps": self.displayed / elapsed if elapsed else 0.0,
            "last_sequence": self.last_sequence,
            "last_latency_ms": self.last_latency_ms,
        }


class PublisherMetrics:
    def __init__(self, url: str, interval: float = 1.0) -> None:
        self.url = url
        self.interval = max(0.25, interval)
        self.snapshot: dict[str, Any] = {}
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_bytes: tuple[int, float] | None = None
        self.bitrate_mbps = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="plyctl-viewer-metrics", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with urlopen(self.url, timeout=1.0) as response:
                    data = json.load(response)
                total_bytes = sum(int(dict(item).get("sent_bytes", 0)) for item in dict(data.get("streams", {})).values())
                now = time.monotonic()
                if self._last_bytes is not None:
                    previous, previous_time = self._last_bytes
                    self.bitrate_mbps = max(0.0, (total_bytes - previous) * 8 / max(now - previous_time, 1e-9) / 1_000_000)
                self._last_bytes = (total_bytes, now)
                self.snapshot = data
                self.error = None
            except Exception as exc:
                self.error = str(exc)
            self._stop.wait(self.interval)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def summary(self, stream_name: str | None = None) -> dict[str, Any]:
        streams = dict(self.snapshot.get("streams", {}))
        stream = dict(streams.get(stream_name, {})) if stream_name else {}
        if not stream and len(streams) == 1:
            stream = dict(next(iter(streams.values())))
        nodes = dict(self.snapshot.get("nodes", {}))
        node_cpu = {name: float(dict(dict(raw).get("resources", {})).get("cpu_percent", 0.0)) for name, raw in nodes.items()}
        system = dict(self.snapshot.get("system", {}))
        return {
            "bitrate_mbps": self.bitrate_mbps,
            "subscribers": int(stream.get("subscribers", 0)),
            "stream_drops": int(dict(stream.get("queue", {})).get("dropped", 0)),
            "node_cpu": node_cpu,
            "temperature_c": system.get("temperature_c"),
            "memory_available_bytes": system.get("memory_available_bytes"),
            "error": self.error,
        }


def _default_metrics_url(source_label: str) -> str | None:
    if not source_label.startswith("nodrix://"):
        return None
    parsed = urlparse(source_label)
    if not parsed.hostname:
        return None
    return f"http://{parsed.hostname}:9464/metrics.json"


class LatestSlot:
    """Single-element mailbox optimized for low-latency preview.

    Producers never block. If a frame has not yet been consumed, it is replaced
    by the newer one. The viewer therefore displays current data instead of an
    accumulated queue of stale frames.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._value: Message | None = None
        self._version = 0
        self._consumed_version = 0
        self._closed = False
        self._error: BaseException | None = None
        self.overwritten = 0

    def put(self, value: Message) -> None:
        with self._condition:
            if self._closed:
                return
            if self._value is not None and self._consumed_version < self._version:
                self.overwritten += 1
            self._value = value
            self._version += 1
            self._condition.notify_all()

    def fail(self, error: BaseException) -> None:
        with self._condition:
            self._error = error
            self._closed = True
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def wait_next(self, last_version: int, timeout: float = 0.25) -> tuple[int, Message | None]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._version <= last_version and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return last_version, None
                self._condition.wait(remaining)
            if self._error is not None:
                raise ViewerError(str(self._error)) from self._error
            if self._version <= last_version:
                return last_version, None
            self._consumed_version = self._version
            return self._version, self._value

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed


class _Reader(Protocol):
    source_label: str
    slot: LatestSlot

    def start(self) -> None: ...
    def close(self) -> None: ...


class FFmpegAccessUnitDecoder:
    """Persistent low-latency decoder for H.264/H.265 Plyctl access units."""

    def __init__(self, slot: LatestSlot, encoded: EncodedFrame) -> None:
        if np is None:
            raise ViewerError("NumPy is required for H.264/H.265 Plyctl stream decoding")
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise ViewerError("FFmpeg is required for H.264/H.265 Plyctl stream decoding")
        if encoded.width <= 0 or encoded.height <= 0:
            raise ViewerError("Encoded H.264/H.265 frames must declare width and height")
        self.slot = slot
        self.codec = encoded.codec
        self.width = encoded.width
        self.height = encoded.height
        self.frame_bytes = self.width * self.height * 3
        self._metadata: queue.Queue[Message] = queue.Queue(maxsize=256)
        input_format = "h264" if encoded.codec == MediaCodec.H264 else "hevc"
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-flags", "low_delay", "-probesize", "32", "-analyzeduration", "0", "-fpsprobesize", "0",
            "-f", input_format, "-framerate", f"{encoded.fps or 30:g}", "-i", "pipe:0",
            "-an", "-sn", "-dn", "-pix_fmt", "bgr24",
            "-f", "rawvideo", "pipe:1",
        ]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read_loop, name="plyctl-viewer-au-decoder", daemon=True)
        self._thread.start()

    @staticmethod
    def _read_exact(pipe: Any, size: int) -> bytes | None:
        data = bytearray(size)
        view = memoryview(data)
        offset = 0
        while offset < size:
            count = pipe.readinto(view[offset:])
            if not count:
                return None
            offset += count
        return bytes(data)

    def write(self, message: Message) -> None:
        if self.process.stdin is None or self.process.poll() is not None:
            raise ViewerError("FFmpeg access-unit decoder stopped unexpectedly")
        try:
            self._metadata.put_nowait(message)
        except queue.Full:
            try:
                self._metadata.get_nowait()
            except queue.Empty:
                pass
            self._metadata.put_nowait(message)
        payload = message.payload
        assert isinstance(payload, EncodedFrame)
        self.process.stdin.write(payload.memoryview())
        self.process.stdin.flush()

    def _read_loop(self) -> None:
        assert self.process.stdout is not None
        try:
            while not self._stop.is_set():
                raw = self._read_exact(self.process.stdout, self.frame_bytes)
                if raw is None:
                    break
                try:
                    source = self._metadata.get_nowait()
                except queue.Empty:
                    source = Message(type="vision.encoded_frame", payload=None)
                array = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))
                frame = Frame.from_numpy(array, pixel_format=PixelFormat.BGR8, readonly=True)
                self.slot.put(Message(
                    type="vision.frame",
                    payload=frame,
                    sequence=source.sequence,
                    timestamp_ns=source.timestamp_ns,
                    stream_id=source.stream_id,
                    trace_id=source.trace_id,
                    metadata={**source.metadata, "decoded_from": self.codec.value},
                    created_ns=source.created_ns,
                ))
        except BaseException as exc:
            if not self._stop.is_set():
                self.slot.fail(exc)

    def finish(self, timeout: float = 3.0) -> None:
        """Flush the decoder at end-of-stream and drain all complete frames."""
        if self.process.stdin is not None and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.terminate()
        self._thread.join(timeout=timeout)

    def close(self) -> None:
        self._stop.set()
        if self.process.stdin is not None and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except (subprocess.TimeoutExpired, OSError):
                self.process.kill()
        self._thread.join(timeout=1.0)


class NodrixStreamReader:
    def __init__(
        self,
        target: str,
        *,
        discovery_timeout: float,
        receive_buffer_bytes: int,
    ) -> None:
        self.target = target
        self.source_label = target
        self.slot = LatestSlot()
        self.client = StreamClient(
            target,
            discovery_timeout=discovery_timeout,
            capacity=1,
            policy="latest",
            receive_buffer_bytes=receive_buffer_bytes,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._decoder: FFmpegAccessUnitDecoder | None = None

    def start(self) -> None:
        self.client.connect()
        self.source_label = self.client.uri
        self._thread = threading.Thread(target=self._loop, name="plyctl-viewer-stream", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                message = self.client.receive()
                payload = message.payload
                if isinstance(payload, EncodedFrame) and payload.codec in {MediaCodec.H264, MediaCodec.H265}:
                    if self._decoder is None:
                        self._decoder = FFmpegAccessUnitDecoder(self.slot, payload)
                    self._decoder.write(message)
                else:
                    self.slot.put(message)
        except EOFError:
            # Publisher shutdown closes the stream socket normally.
            pass
        except (OSError, ConnectionError) as exc:
            if not self._stop.is_set():
                self.slot.fail(exc)
        except BaseException as exc:  # pragma: no cover - defensive reader boundary
            self.slot.fail(exc)
        finally:
            if self._decoder is not None and not self._stop.is_set():
                self._decoder.finish()
                self._decoder = None
            self.slot.close()

    def close(self) -> None:
        self._stop.set()
        self.client.close()
        if self._decoder is not None:
            self._decoder.close()
            self._decoder = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.slot.close()


class FFmpegReader:
    def __init__(
        self,
        source: str,
        *,
        realtime: bool = True,
        rtsp_transport: str = "tcp",
    ) -> None:
        self.source_label = source
        self.slot = LatestSlot()
        self.reader = FFmpegFrameReader(
            uri=source,
            realtime=realtime,
            rtsp_transport=rtsp_transport,
            low_latency=True,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.reader.open()
        self._thread = threading.Thread(target=self._loop, name="plyctl-viewer-ffmpeg", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        try:
            for sequence, frame in enumerate(self.reader.frames()):
                if self._stop.is_set():
                    break
                self.slot.put(Message(
                    type="vision.frame",
                    payload=Frame.from_numpy(frame, pixel_format=PixelFormat.BGR8, readonly=True),
                    sequence=sequence,
                    timestamp_ns=time.time_ns(),
                    trace_id=sequence,
                    metadata={
                        "source": self.source_label,
                        "fps": self.reader.fps,
                        "width": self.reader.width,
                        "height": self.reader.height,
                        "decoder": "ffmpeg",
                    },
                ))
        except (MediaError, OSError) as exc:
            if not self._stop.is_set():
                self.slot.fail(exc)
        except BaseException as exc:  # pragma: no cover
            self.slot.fail(exc)
        finally:
            self.slot.close()

    def close(self) -> None:
        self._stop.set()
        self.reader.close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.slot.close()


class OpenCVReader:
    def __init__(self, source: str, *, realtime: bool = True, backend: int = 0) -> None:
        if cv2 is None:
            raise ViewerError('OpenCV is required. Install with: pip install "plyctl[viewer]"')
        self.original_source = source
        self.source = _normalize_opencv_source(source)
        self.source_label = str(source)
        self.realtime = realtime
        self.backend = int(backend)
        self.slot = LatestSlot()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.capture: Any = None
        self.source_fps = 0.0

    def start(self) -> None:
        capture = cv2.VideoCapture(self.source, self.backend) if self.backend else cv2.VideoCapture(self.source)
        if not capture.isOpened():
            capture.release()
            raise ViewerError(f"Cannot open video source: {self.original_source}")
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self.capture = capture
        self._thread = threading.Thread(target=self._loop, name="plyctl-viewer-capture", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        sequence = 0
        next_deadline = time.perf_counter()
        file_like = _is_local_file_source(self.original_source)
        capture = self.capture
        if capture is None:
            self.slot.close()
            return
        try:
            while not self._stop.is_set():
                ok, frame = capture.read()
                if not ok:
                    break
                message = Message(
                    type="vision.frame",
                    payload=Frame.from_numpy(frame, pixel_format=PixelFormat.BGR8, readonly=True),
                    sequence=sequence,
                    timestamp_ns=time.time_ns(),
                    trace_id=sequence,
                    metadata={
                        "source": self.source_label,
                        "fps": self.source_fps,
                        "width": int(frame.shape[1]),
                        "height": int(frame.shape[0]),
                    },
                )
                self.slot.put(message)
                sequence += 1
                if file_like and self.realtime and self.source_fps > 0:
                    next_deadline += 1.0 / self.source_fps
                    delay = next_deadline - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
        except BaseException as exc:  # pragma: no cover - defensive reader boundary
            if not self._stop.is_set():
                self.slot.fail(exc)
        finally:
            capture.release()
            if self.capture is capture:
                self.capture = None
            self.slot.close()

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
            if not thread.is_alive():
                self._thread = None
        self.slot.close()


def _normalize_opencv_source(source: str) -> str | int:
    stripped = source.strip()
    if stripped.isdigit():
        return int(stripped)
    return str(Path(stripped).expanduser()) if "://" not in stripped else stripped


def _is_local_file_source(source: str) -> bool:
    if source.isdigit() or source.startswith("/dev/video") or "://" in source:
        return False
    return Path(source).expanduser().is_file()


def _is_nodrix_target(source: str) -> bool:
    return source.startswith("nodrix://") or source.startswith("/") and not Path(source).exists() and not source.startswith("/dev/video")


def _decode_still_image(encoded: EncodedFrame) -> Any:
    if cv2 is None or np is None:
        raise ViewerError("OpenCV and NumPy are required to decode compressed frames")
    if encoded.codec not in {MediaCodec.JPEG, MediaCodec.MJPEG, MediaCodec.PNG}:
        raise ViewerError(
            f"Still-image decoder cannot decode {encoded.codec.value}; "
            "H.264/H.265 Plyctl streams are handled by the persistent FFmpeg reader"
        )
    data = np.frombuffer(encoded.memoryview(), dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise ViewerError("Compressed frame decoding failed")
    return frame


def message_to_bgr(message: Message) -> Any:
    if cv2 is None:
        raise ViewerError('OpenCV is required. Install with: pip install "plyctl[viewer]"')
    payload = message.payload
    if isinstance(payload, EncodedFrame):
        return _decode_still_image(payload)
    if not isinstance(payload, Frame):
        raise ViewerError(
            f"plyctl-viewer expects vision.frame or vision.encoded_frame, got {message.type} / {type(payload).__name__}"
        )
    frame = payload.numpy()
    pixel_format = payload.pixel_format
    if pixel_format == PixelFormat.BGR8:
        return frame
    if pixel_format == PixelFormat.RGB8:
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    if pixel_format == PixelFormat.GRAY8:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if pixel_format == PixelFormat.BGRA8:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    if pixel_format == PixelFormat.RGBA8:
        return cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
    raise ViewerError(f"Unsupported raw pixel format for viewer: {pixel_format.value}")


class RollingRate:
    def __init__(self, window_seconds: float = 1.5) -> None:
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque()

    def tick(self) -> float:
        now = time.perf_counter()
        self.timestamps.append(now)
        cutoff = now - self.window_seconds
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()
        if len(self.timestamps) < 2:
            return 0.0
        elapsed = self.timestamps[-1] - self.timestamps[0]
        return (len(self.timestamps) - 1) / elapsed if elapsed > 0 else 0.0


def _latency_ms(message: Message) -> float | None:
    # H.264/H.265 is transported as arbitrary ordered chunks.
    # Until decoded frames are matched to timestamped access units,
    # a precise latency value would be misleading.
    if message.metadata.get("decoded_from") in {"h264", "h265"}:
        return None
    if message.timestamp_ns <= 0:
        return None
    value = (time.time_ns() - int(message.timestamp_ns)) / 1e6
    # Remote hosts require synchronized wall clocks. Hide obviously invalid data.
    return value if -1000.0 <= value <= 60000.0 else None


def _prepare_overlay_frame(frame):
    """Return a writable frame only when overlay drawing requires it."""
    flags = getattr(frame, "flags", None)
    if flags is not None and not bool(flags.writeable):
        return frame.copy()
    return frame


def _draw_overlay(
    frame: Any,
    *,
    source: str,
    message: Message,
    receive_fps: float,
    display_fps: float,
    latency_ms: float | None,
    overwritten: int,
    publisher: dict[str, Any] | None = None,
) -> None:
    if cv2 is None:
        return
    height, width = frame.shape[:2]
    lines = [
        f"RX {receive_fps:5.1f} FPS   VIEW {display_fps:5.1f} FPS",
        f"{width}x{height}   seq {message.sequence}   drop {overwritten}",
        f"latency {latency_ms:.1f} ms" if latency_ms is not None else "latency n/a (encoded timing unavailable)",
    ]
    if publisher:
        lines.append(
            f"PUB {float(publisher.get('bitrate_mbps', 0.0)):.2f} Mbit/s  "
            f"subs {int(publisher.get('subscribers', 0))}  drops {int(publisher.get('stream_drops', 0))}"
        )
        node_cpu = dict(publisher.get("node_cpu", {}))
        if node_cpu:
            busiest = sorted(node_cpu.items(), key=lambda item: item[1], reverse=True)[:2]
            text = "  ".join(f"{name} {value:.0f}%" for name, value in busiest)
            temperature = publisher.get("temperature_c")
            if temperature is not None:
                text += f"  {float(temperature):.1f}C"
            lines.append(text)
    lines.append(source)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.55
    thickness = 1
    line_height = 22
    max_width = max(cv2.getTextSize(line, font, scale, thickness)[0][0] for line in lines)
    right = min(width - 8, max_width + 24)
    bottom = min(height - 8, 16 + line_height * len(lines))
    if right > 8 and bottom > 8:
        # Blend only the small text background ROI instead of copying the full frame.
        roi = frame[8:bottom, 8:right]
        shade = np.zeros_like(roi)
        cv2.addWeighted(shade, 0.58, roi, 0.42, 0, roi)
    for index, line in enumerate(lines):
        cv2.putText(frame, line, (16, 29 + index * line_height), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def _make_reader(
    source: str,
    *,
    discovery_timeout: float,
    receive_buffer_bytes: int,
    realtime_file: bool,
    backend: int,
    decoder: str,
    rtsp_transport: str,
) -> _Reader:
    if _is_nodrix_target(source):
        return NodrixStreamReader(
            source,
            discovery_timeout=discovery_timeout,
            receive_buffer_bytes=receive_buffer_bytes,
        )
    selected = decoder.lower()
    if selected not in {"auto", "opencv", "ffmpeg"}:
        raise ViewerError("decoder must be auto, opencv, or ffmpeg")
    use_ffmpeg = selected == "ffmpeg" or (selected == "auto" and source.startswith(("rtsp://", "srt://", "udp://")))
    if use_ffmpeg:
        return FFmpegReader(source, realtime=realtime_file, rtsp_transport=rtsp_transport)
    return OpenCVReader(source, realtime=realtime_file, backend=backend)


def run_viewer(
    source: str,
    *,
    title: str = "Plyctl Viewer",
    max_fps: float = 0.0,
    overlay: bool = True,
    fullscreen: bool = False,
    scale: float = 1.0,
    discovery_timeout: float = 3.0,
    receive_buffer_bytes: int = 262144,
    realtime_file: bool = True,
    backend: int = 0,
    decoder: str = "auto",
    rtsp_transport: str = "tcp",
    headless: bool = False,
    max_frames: int = 0,
    screenshot_dir: Path = Path("screenshots"),
    json_stats: bool = False,
    publisher_stats: bool = True,
    metrics_url: str | None = None,
) -> dict[str, Any]:
    if cv2 is None or np is None:
        raise ViewerError('Install viewer dependencies with: pip install "plyctl[viewer]"')
    if max_fps < 0:
        raise ViewerError("--fps cannot be negative")
    if scale <= 0:
        raise ViewerError("--scale must be positive")

    reader = _make_reader(
        source,
        discovery_timeout=discovery_timeout,
        receive_buffer_bytes=receive_buffer_bytes,
        realtime_file=realtime_file,
        backend=backend,
        decoder=decoder,
        rtsp_transport=rtsp_transport,
    )
    stats = ViewerStats()
    rx_rate = RollingRate()
    display_rate = RollingRate()
    version = 0
    last_display_at = 0.0
    screenshot_dir = Path(screenshot_dir)
    remote_metrics: PublisherMetrics | None = None

    try:
        reader.start()
        selected_metrics_url = metrics_url or (_default_metrics_url(reader.source_label) if publisher_stats else None)
        if selected_metrics_url:
            remote_metrics = PublisherMetrics(selected_metrics_url)
            remote_metrics.start()
        stats.started_ns = time.perf_counter_ns()
        if not headless:
            cv2.namedWindow(title, cv2.WINDOW_NORMAL)
            if fullscreen:
                cv2.setWindowProperty(title, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        while True:
            version, message = reader.slot.wait_next(version, timeout=0.25)
            if message is None:
                if reader.slot.closed:
                    break
                if not headless:
                    key = cv2.waitKey(1) & 0xFF
                    if key in (27, ord("q")):
                        break
                continue

            stats.received += 1
            stats.overwritten = reader.slot.overwritten
            stats.last_sequence = int(message.sequence)
            receive_fps = rx_rate.tick()

            now = time.perf_counter()
            if max_fps > 0 and last_display_at > 0:
                remaining = 1.0 / max_fps - (now - last_display_at)
                if remaining > 0:
                    time.sleep(remaining)
            last_display_at = time.perf_counter()

            try:
                frame = message_to_bgr(message)
            except ViewerError:
                stats.decode_errors += 1
                raise
            if scale != 1.0:
                frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)

            display_fps = display_rate.tick()
            latency_ms = _latency_ms(message)
            stats.last_latency_ms = latency_ms
            if overlay:
                frame = _prepare_overlay_frame(frame)
                _draw_overlay(
                    frame,
                    source=reader.source_label,
                    message=message,
                    receive_fps=receive_fps,
                    display_fps=display_fps,
                    latency_ms=latency_ms,
                    overwritten=stats.overwritten,
                    publisher=(remote_metrics.summary(urlparse(reader.source_label).path) if remote_metrics else None),
                )
            stats.displayed += 1

            if not headless:
                cv2.imshow(title, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                if key == ord("s"):
                    screenshot_dir.mkdir(parents=True, exist_ok=True)
                    path = screenshot_dir / f"nodrix-{int(time.time())}-{message.sequence}.png"
                    cv2.imwrite(str(path), frame)
            if max_frames > 0 and stats.displayed >= max_frames:
                break
    finally:
        if remote_metrics is not None:
            remote_metrics.close()
        reader.close()
        if not headless and cv2 is not None:
            cv2.destroyWindow(title)

    report = {
        "source": reader.source_label,
        **stats.as_dict(),
        "publisher": remote_metrics.summary(urlparse(reader.source_label).path) if remote_metrics else None,
    }
    if json_stats:
        print(json.dumps(report, ensure_ascii=False))
    return report


def view_command(
    source: str = typer.Argument(..., help="Stream name, nodrix:// URI, RTSP/HTTP URL, device, camera index, or video path"),
    fps: float = typer.Option(0.0, "--fps", min=0.0, help="Maximum display FPS; 0 keeps source rate"),
    title: str = typer.Option("Plyctl Viewer", "--title"),
    overlay: bool = typer.Option(True, "--overlay/--no-overlay", help="Show FPS, latency, sequence and dropped frames"),
    fullscreen: bool = typer.Option(False, "--fullscreen"),
    scale: float = typer.Option(1.0, "--scale", min=0.05, max=8.0),
    discovery_timeout: float = typer.Option(3.0, "--discovery-timeout", min=0.05),
    receive_buffer_kb: int = typer.Option(256, "--receive-buffer-kb", min=16),
    realtime_file: bool = typer.Option(True, "--realtime-file/--fast-file", help="Pace local files at their recorded FPS"),
    backend: int = typer.Option(0, "--backend", help="Optional OpenCV VideoCapture backend id"),
    decoder: str = typer.Option("auto", "--decoder", help="auto, opencv, or ffmpeg"),
    rtsp_transport: str = typer.Option("tcp", "--rtsp-transport", help="tcp or udp for RTSP FFmpeg input"),
    headless: bool = typer.Option(False, "--headless", help="Decode without creating a window"),
    max_frames: int = typer.Option(0, "--max-frames", min=0),
    screenshot_dir: Path = typer.Option(Path("screenshots"), "--screenshot-dir"),
    json_stats: bool = typer.Option(False, "--json-stats"),
    publisher_stats: bool = typer.Option(True, "--publisher-stats/--no-publisher-stats", help="Read Plyctl publisher metrics from port 9464"),
    metrics_url: str | None = typer.Option(None, "--metrics-url", help="Explicit Plyctl /metrics.json endpoint"),
) -> None:
    """View a frame stream with a latest-frame low-latency policy."""
    try:
        report = run_viewer(
            source,
            title=title,
            max_fps=fps,
            overlay=overlay,
            fullscreen=fullscreen,
            scale=scale,
            discovery_timeout=discovery_timeout,
            receive_buffer_bytes=receive_buffer_kb * 1024,
            realtime_file=realtime_file,
            backend=backend,
            decoder=decoder,
            rtsp_transport=rtsp_transport,
            headless=headless,
            max_frames=max_frames,
            screenshot_dir=screenshot_dir,
            json_stats=json_stats,
            publisher_stats=publisher_stats,
            metrics_url=metrics_url,
        )
    except (ViewerError, OSError, LookupError, ValueError) as exc:
        typer.echo(f"Viewer failed: {exc}", err=True)
        raise typer.Exit(1)
    if not json_stats:
        latency = report["last_latency_ms"]
        latency_text = "n/a" if latency is None else f"{latency:.1f} ms"
        typer.echo(
            f"Displayed {report['displayed']} frames; "
            f"{report['display_fps']:.1f} FPS; overwritten {report['overwritten']}; latency {latency_text}"
        )


def main() -> None:
    typer.run(view_command)


if __name__ == "__main__":
    main()