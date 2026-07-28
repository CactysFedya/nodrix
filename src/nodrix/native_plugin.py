from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from .cv_types import Frame, ManagedBuffer, Tensor
from .messages import Message
from .node import Node, NodeContext
from .wire import decode_registered_payload, encode_registered_payload, has_registered_wire_codec

try:
    from ._native_plugin import NativeNodeHost
except Exception:  # pragma: no cover
    NativeNodeHost = None


class NativePluginNode(Node):
    """Python SDK adapter for a C++ plugin in the unified executor."""

    def __init__(
        self,
        library: Path,
        node_type: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        if NativeNodeHost is None:
            raise RuntimeError("Nodrix native plugin extension is not built")
        super().__init__(parameters)
        self.library = library
        self.node_type = node_type
        self.host = NativeNodeHost(str(library), node_type, json.dumps(self.parameters))
        self.input_types = dict(self.host.input_types)
        self.output_types = dict(self.host.output_types)
        self.input_memory = dict(self.host.input_memory)
        self.output_memory = dict(self.host.output_memory)
        if bool(self.host.is_source):
            raise RuntimeError(
                "Native source plugins currently require engine: native; mixed Python/C++ graphs support native processors and sinks"
            )

    def open(self, context: NodeContext) -> None:
        super().open(context)
        self.host.open(name=context.name, run_dir=str(context.run_dir), device=context.device)

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
            return message.with_updates(payload=payload.buffer.owner, metadata=metadata)
        if isinstance(payload, Tensor):
            metadata = {
                **message.metadata,
                "nodrix_payload": "Tensor",
                "shape": payload.shape,
                "dtype": payload.dtype,
                "layout": str(payload.layout),
            }
            return message.with_updates(payload=payload.buffer.owner, metadata=metadata)
        if isinstance(payload, ManagedBuffer):
            return message.with_updates(payload=payload.owner)
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

    @staticmethod
    def _rewrap(message: Message) -> Message:
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
        return message

    def process(self, inputs: dict[str, Message]) -> dict[str, Message] | None:
        result = self.host.process({name: self._unwrap(message) for name, message in inputs.items()})
        return {name: self._rewrap(message) for name, message in result.items()} or None

    def flush(self) -> dict[str, Message] | None:
        result = self.host.flush()
        return {name: self._rewrap(message) for name, message in result.items()} or None

    def close(self) -> None:
        self.host.close()
