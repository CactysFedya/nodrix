from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import time
from typing import Any

from .messages import Message
from .cv_types import EncodedFrame, Frame, ManagedBuffer, MediaCodec, PixelFormat
from .node import Node, SinkNode, SourceNode
from .registry import register_builtin


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "shape") and hasattr(value, "dtype"):
        return {
            "kind": type(value).__name__,
            "shape": list(value.shape),
            "dtype": str(value.dtype),
        }
    return repr(value)


@register_builtin("core.synthetic_source")
class SyntheticSource(SourceNode):
    output_types = {"output": "core.object"}

    def produce(self):
        count = int(self.parameters.get("count", 10))
        interval_ms = float(self.parameters.get("interval_ms", 0))
        template = self.parameters.get("payload", {"value": 1})
        for sequence in range(count):
            payload = dict(template) if isinstance(template, dict) else template
            if isinstance(payload, dict):
                payload = {**payload, "sequence": sequence}
            yield {
                "output": Message(
                    type="core.object",
                    payload=payload,
                    sequence=sequence,
                    timestamp_ns=time.time_ns(),
                    trace_id=sequence,
                )
            }
            if interval_ms > 0:
                time.sleep(interval_ms / 1000.0)


@register_builtin("core.identity")
class IdentityNode(Node):
    input_types = {"input": "core.any"}
    output_types = {"output": "core.any"}

    def process(self, inputs):
        return {"output": inputs["input"]}


@register_builtin("core.delay")
class DelayNode(Node):
    input_types = {"input": "core.any"}
    output_types = {"output": "core.any"}

    def process(self, inputs):
        time.sleep(float(self.parameters.get("milliseconds", 1)) / 1000.0)
        return {"output": inputs["input"]}


@register_builtin("core.counter_sink")
class CounterSink(SinkNode):
    input_types = {"input": "core.any"}

    def open(self, context):
        super().open(context)
        self.count = 0

    def process(self, inputs):
        self.count += 1
        return None


@register_builtin("sink.console")
class ConsoleSink(SinkNode):
    input_types = {"input": "core.any"}

    def process(self, inputs):
        message = inputs["input"]
        print(json.dumps({
            "sequence": message.sequence,
            "type": message.type,
            "payload": _jsonable(message.payload),
        }, ensure_ascii=False))
        return None


@register_builtin("sink.jsonl")
class JsonlSink(SinkNode):
    input_types = {"input": "core.any"}

    def open(self, context):
        super().open(context)
        configured = Path(str(self.parameters.get("path", "output.jsonl")))
        if not configured.is_absolute():
            configured = context.run_dir / configured
        configured.parent.mkdir(parents=True, exist_ok=True)
        self.path = configured
        self.handle = configured.open("w", encoding="utf-8", buffering=1024 * 1024)

    def process(self, inputs):
        message = inputs["input"]
        record = {
            "type": message.type,
            "sequence": message.sequence,
            "timestamp_ns": message.timestamp_ns,
            "stream_id": message.stream_id,
            "trace_id": message.trace_id,
            "metadata": _jsonable(message.metadata),
            "payload": _jsonable(message.payload),
        }
        self.handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return None

    def close(self):
        self.handle.close()


try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


@register_builtin("vision.video_source")
class VideoSource(SourceNode):
    output_types = {"frame": "vision.frame"}

    def open(self, context):
        super().open(context)
        if cv2 is None:
            raise RuntimeError("OpenCV is required for vision.video_source")
        uri = self.parameters.get("uri", 0)
        if isinstance(uri, str) and uri.isdigit():
            uri = int(uri)
        elif isinstance(uri, str) and "://" not in uri:
            candidate = Path(uri).expanduser()
            if not candidate.is_absolute():
                candidate = context.project_dir / candidate
            uri = str(candidate.resolve())
        backend = int(self.parameters.get("backend", 0))
        self.capture = cv2.VideoCapture(uri, backend) if backend else cv2.VideoCapture(uri)
        if not self.capture.isOpened():
            raise RuntimeError(f"Cannot open video source: {uri}")
        self.limit = int(self.parameters.get("max_frames", 0))
        self.realtime = bool(self.parameters.get("realtime", False))
        self.fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, int(self.parameters.get("buffer_size", 1)))

    def produce(self):
        sequence = 0
        next_deadline = time.perf_counter()
        while self.limit <= 0 or sequence < self.limit:
            ok, frame = self.capture.read()
            if not ok:
                break
            # OpenCV owns the ndarray memory. Frame.from_numpy wraps it without copying.
            typed_frame = Frame.from_numpy(frame, pixel_format=PixelFormat.BGR8, readonly=True)
            yield {
                "frame": Message(
                    type="vision.frame",
                    payload=typed_frame,
                    sequence=sequence,
                    timestamp_ns=time.time_ns(),
                    trace_id=sequence,
                    metadata={
                        "width": int(frame.shape[1]),
                        "height": int(frame.shape[0]),
                        "pixel_format": "bgr8",
                        "fps": self.fps,
                        "contiguous": bool(frame.flags.c_contiguous),
                    },
                )
            }
            sequence += 1
            if self.realtime and self.fps > 0:
                next_deadline += 1.0 / self.fps
                delay = next_deadline - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)

    def close(self):
        self.capture.release()


@register_builtin("vision.resize")
class ResizeNode(Node):
    input_types = {"frame": "vision.frame"}
    output_types = {"frame": "vision.frame"}

    def open(self, context):
        super().open(context)
        if cv2 is None:
            raise RuntimeError("OpenCV is required for vision.resize")
        self.width = int(self.parameters["width"])
        self.height = int(self.parameters["height"])
        self.interpolation = int(self.parameters.get("interpolation", cv2.INTER_LINEAR))

    def process(self, inputs):
        src = inputs["frame"]
        frame = src.payload
        if not isinstance(frame, Frame):
            raise TypeError("vision.resize expects a nodrix.Frame payload")
        resized = cv2.resize(frame.numpy(), (self.width, self.height), interpolation=self.interpolation)
        typed = Frame.from_numpy(resized, pixel_format=frame.pixel_format, readonly=True, metadata=frame.metadata)
        return {
            "frame": src.with_updates(
                payload=typed,
                metadata={**src.metadata, "width": self.width, "height": self.height},
            )
        }


@register_builtin("vision.jpeg_encoder")
class JpegEncoderNode(Node):
    input_types = {"frame": "vision.frame"}
    output_types = {"frame": "vision.encoded_frame"}

    def open(self, context):
        super().open(context)
        if cv2 is None:
            raise RuntimeError("OpenCV is required for vision.jpeg_encoder")
        self.quality = max(1, min(int(self.parameters.get("quality", 85)), 100))

    def process(self, inputs):
        source = inputs["frame"]
        typed = source.payload
        if not isinstance(typed, Frame):
            raise TypeError("vision.jpeg_encoder expects a nodrix.Frame payload")
        ok, encoded = cv2.imencode(
            ".jpg",
            typed.numpy(),
            [int(cv2.IMWRITE_JPEG_QUALITY), self.quality],
        )
        if not ok:
            raise RuntimeError("OpenCV JPEG encoding failed")
        payload = EncodedFrame(
            buffer=ManagedBuffer.wrap(encoded, readonly=True),
            codec=MediaCodec.JPEG,
            width=typed.width,
            height=typed.height,
            fps=float(source.metadata.get("fps", 0.0) or 0.0),
            keyframe=True,
            pts_ns=source.timestamp_ns,
            metadata={**typed.metadata, "quality": self.quality},
        )
        return {
            "frame": source.with_updates(
                type="vision.encoded_frame",
                payload=payload,
                metadata={**source.metadata, "codec": "jpeg", "encoded_bytes": payload.nbytes},
            )
        }


@register_builtin("vision.jpeg_decoder")
class JpegDecoderNode(Node):
    input_types = {"frame": "vision.encoded_frame"}
    output_types = {"frame": "vision.frame"}

    def open(self, context):
        super().open(context)
        if cv2 is None:
            raise RuntimeError("OpenCV is required for vision.jpeg_decoder")

    def process(self, inputs):
        source = inputs["frame"]
        encoded = source.payload
        if not isinstance(encoded, EncodedFrame):
            raise TypeError("vision.jpeg_decoder expects a nodrix.EncodedFrame payload")
        if encoded.codec not in {MediaCodec.JPEG, MediaCodec.MJPEG, MediaCodec.PNG}:
            raise ValueError(f"Unsupported still-image codec: {encoded.codec.value}")
        import numpy as np

        data = np.frombuffer(encoded.memoryview(), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("OpenCV image decoding failed")
        frame = Frame.from_numpy(image, pixel_format=PixelFormat.BGR8, readonly=True, metadata=encoded.metadata)
        return {
            "frame": source.with_updates(
                type="vision.frame",
                payload=frame,
                metadata={**source.metadata, "codec": "bgr8", "width": frame.width, "height": frame.height},
            )
        }


@register_builtin("sink.video_writer")
class VideoWriterSink(SinkNode):
    input_types = {"frame": "vision.frame"}

    def open(self, context):
        super().open(context)
        if cv2 is None:
            raise RuntimeError("OpenCV is required for sink.video_writer")
        self.path = Path(str(self.parameters.get("path", "output.mp4")))
        if not self.path.is_absolute():
            self.path = context.run_dir / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fps = float(self.parameters.get("fps", 30.0))
        self.codec = str(self.parameters.get("codec", "mp4v"))
        self.writer = None

    def process(self, inputs):
        typed = inputs["frame"].payload
        if not isinstance(typed, Frame):
            raise TypeError("sink.video_writer expects a nodrix.Frame payload")
        frame = typed.numpy()
        if self.writer is None:
            height, width = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*self.codec)
            self.writer = cv2.VideoWriter(str(self.path), fourcc, self.fps, (width, height))
            if not self.writer.isOpened():
                raise RuntimeError(f"Cannot open video writer: {self.path}")
        self.writer.write(frame)
        return None

    def close(self):
        if self.writer is not None:
            self.writer.release()


@register_builtin("core.stream_source")
class StreamSource(SourceNode):
    """Subscribe to a named LAN stream or an explicit ``nodrix://`` URI."""

    output_types = {"output": "core.any"}

    def open(self, context):
        super().open(context)
        from .streams import StreamClient

        target = str(self.parameters.get("name") or self.parameters.get("uri") or "")
        if not target:
            raise ValueError("core.stream_source requires parameters.name or parameters.uri")
        self.client = StreamClient(
            target,
            discovery_timeout=float(self.parameters.get("discovery_timeout", 3.0)),
            capacity=int(self.parameters.get("capacity", 1)),
            policy=str(self.parameters.get("policy", "latest")),
            receive_buffer_bytes=int(self.parameters.get("receive_buffer_bytes", 262144)),
        )
        self.client.connect(timeout=float(self.parameters.get("connect_timeout", 5.0)))
        self.limit = int(self.parameters.get("max_messages", 0))

    def produce(self):
        received = 0
        while self.limit <= 0 or received < self.limit:
            try:
                message = self.client.receive()
            except EOFError:
                break
            yield {"output": message}
            received += 1

    def close(self):
        self.client.close()
