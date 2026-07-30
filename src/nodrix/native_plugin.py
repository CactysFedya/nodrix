from __future__ import annotations

import json
from pathlib import Path
import struct
from typing import Any

from .cv_types import (
    BoxFormat,
    CoordinateSpace,
    Detections,
    Frame,
    ManagedBuffer,
    Tensor,
)
from .messages import Message
from .node import Node, NodeContext
from .wire import decode_registered_payload, encode_registered_payload, has_registered_wire_codec

try:
    from ._native_plugin import NativeNodeHost
except Exception:  # pragma: no cover
    NativeNodeHost = None


class NativePluginNode(Node):
    """Adapter for a stable Plugin C ABI 2.0 node in the unified executor."""

    def __init__(
        self,
        library: Path,
        node_type: str,
        parameters: dict[str, Any] | None = None,
        *,
        defer_host: bool = False,
    ) -> None:
        if NativeNodeHost is None:
            raise RuntimeError("Nodrix native plugin extension is not built")
        super().__init__(parameters)
        self.library = library
        self.node_type = node_type
        self.host: Any | None = None
        if not defer_host:
            self._initialize_host()

    def _initialize_host(self) -> None:
        if self.host is not None:
            return
        assert NativeNodeHost is not None
        parameters_json = json.dumps(
            self.parameters,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        host = NativeNodeHost(
            str(self.library),
            self.node_type,
            parameters_json,
        )
        if bool(host.is_source):
            raise RuntimeError(
                "Native source plugins currently require engine: native; mixed Python/C++ graphs support native processors and sinks"
            )
        self.host = host
        self.input_types = dict(host.input_types)
        self.output_types = dict(host.output_types)
        self.input_memory = dict(host.input_memory)
        self.output_memory = dict(host.output_memory)
        self.optional_inputs = frozenset(host.optional_inputs)

    def _require_host(self) -> Any:
        if self.host is None:
            raise RuntimeError("Native plugin host is not initialized")
        return self.host

    def open(self, context: NodeContext) -> None:
        super().open(context)
        self._initialize_host()
        self._require_host().open(
            name=context.name,
            run_dir=str(context.run_dir),
            device=context.device,
        )

    @staticmethod
    def _unwrap(message: Message) -> Message:
        payload = message.payload
        if isinstance(payload, Frame):
            metadata = {
                **message.metadata,
                "nodrix_payload": "Frame",
                "width": payload.width,
                "height": payload.height,
                "pixel_format": str(payload.pixel_format),
                "stride": payload.stride,
                "channels": payload.channels,
                "dtype": payload.dtype,
                "shape": payload.shape,
            }
            return message.with_updates(
                payload=payload.buffer.memoryview(),
                metadata=metadata,
            )
        if isinstance(payload, Tensor):
            metadata = {
                **message.metadata,
                "nodrix_payload": "Tensor",
                "shape": payload.shape,
                "dtype": payload.dtype,
                "layout": str(payload.layout),
            }
            return message.with_updates(
                payload=payload.buffer.memoryview(),
                metadata=metadata,
            )
        if isinstance(payload, ManagedBuffer):
            return message.with_updates(payload=payload.memoryview())
        if has_registered_wire_codec(message.type):
            codec_metadata, parts = encode_registered_payload(message.type, payload)
            if len(parts) != 1:
                encoded = b"".join(bytes(part) for part in parts)
            else:
                encoded = parts[0]
            return message.with_updates(
                payload=encoded,
                metadata={
                    **message.metadata,
                    "nodrix_payload": "CustomWire",
                    "nodrix_wire_metadata": codec_metadata,
                },
            )
        return message

    def _rewrap(self, message: Message) -> Message:
        kind = message.metadata.get("nodrix_payload")
        if kind == "Frame" and message.type == "vision.frame":
            frame = Frame(
                buffer=ManagedBuffer.wrap(message.payload, readonly=True),
                width=int(message.metadata["width"]),
                height=int(message.metadata["height"]),
                pixel_format=message.metadata.get("pixel_format", "bgr8"),
                stride=message.metadata.get("stride"),
                channels=message.metadata.get("channels"),
                dtype=str(message.metadata.get("dtype", "uint8")),
                shape=tuple(message.metadata["shape"]) if message.metadata.get("shape") else None,
            )
            return message.with_updates(payload=frame)
        if kind == "Tensor" and message.type == "vision.tensor":
            tensor = Tensor(
                buffer=ManagedBuffer.wrap(message.payload, readonly=True),
                shape=tuple(message.metadata["shape"]),
                dtype=str(message.metadata["dtype"]),
                layout=message.metadata.get("layout", "unknown"),
            )
            return message.with_updates(payload=tensor)
        if kind == "CustomWire" and has_registered_wire_codec(message.type):
            decoded = decode_registered_payload(
                message.type,
                message.payload,
                dict(message.metadata.get("nodrix_wire_metadata") or {}),
            )
            return message.with_updates(payload=decoded)
        if message.type == "vision.detections":
            decoded = self._decode_native_detections(message)
            if decoded is not None:
                return decoded
        return message

    _NATIVE_DETECTIONS_HEADER = struct.Struct("<4sHHII")

    def _decode_native_detections(
        self,
        message: Message,
    ) -> Message | None:
        """Wrap the stable NDT2 native payload as public Detections."""
        try:
            view = memoryview(message.payload)
        except TypeError:
            return None
        header = self._NATIVE_DETECTIONS_HEADER
        if view.nbytes < header.size:
            return None
        magic, version, flags, count, _reserved = header.unpack_from(view, 0)
        if magic != b"NDT2":
            return None
        if version != 1:
            raise RuntimeError(
                f"Unsupported native detections payload version: {version}"
            )
        record_size = 4 * 4 + 4 + 4
        available = view.nbytes - header.size
        if int(count) > available // record_size:
            raise RuntimeError(
                "Invalid native detections count for payload size"
            )
        expected = header.size + int(count) * record_size
        if view.nbytes != expected:
            raise RuntimeError(
                "Invalid native detections payload size: "
                f"got {view.nbytes}, expected {expected}"
            )
        try:
            import numpy as np
        except Exception as exc:  # pragma: no cover - vision dependency
            raise RuntimeError(
                "NumPy is required to wrap native detections"
            ) from exc
        offset = header.size
        boxes = np.frombuffer(
            view,
            dtype="<f4",
            count=int(count) * 4,
            offset=offset,
        ).reshape((-1, 4)).copy()
        offset += int(count) * 16
        scores = np.frombuffer(
            view,
            dtype="<f4",
            count=int(count),
            offset=offset,
        ).copy()
        offset += int(count) * 4
        class_ids = np.frombuffer(
            view,
            dtype="<i4",
            count=int(count),
            offset=offset,
        ).copy()

        from .vision.geometry import restore_letterbox_boxes

        boxes = restore_letterbox_boxes(boxes, message.metadata)
        labels = getattr(self, "native_labels", None)
        detections = Detections(
            boxes=boxes,
            scores=scores,
            class_ids=class_ids,
            box_format=BoxFormat.XYXY,
            coordinate_space=CoordinateSpace.PIXELS,
            labels=labels,
            attributes={
                "backend": "ncnn-cpp",
                "native": True,
                "payload_flags": int(flags),
            },
        )
        return message.with_updates(
            payload=detections,
            metadata={
                **message.metadata,
                "detections": len(detections),
                "detector_backend": "ncnn-cpp",
            },
        )

    def process(self, inputs: dict[str, Message]) -> dict[str, Message] | None:
        result = self._require_host().process(
            {
                name: self._unwrap(message)
                for name, message in inputs.items()
            }
        )
        return {name: self._rewrap(message) for name, message in result.items()} or None

    def flush(self) -> dict[str, Message] | None:
        result = self._require_host().flush()
        return {name: self._rewrap(message) for name, message in result.items()} or None

    def close(self) -> None:
        if self.host is not None:
            self.host.close()
