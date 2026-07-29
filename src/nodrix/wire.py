from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
import ssl
import socket
import struct
from typing import Any, Callable, Iterable

from .cv_types import (
    Detections,
    Embeddings,
    EncodedFrame,
    Frame,
    Identities,
    ManagedBuffer,
    MediaCodec,
    MemoryType,
    Tensor,
    Tracks,
    TYPE_REGISTRY,
)
from .messages import Message

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None

MAGIC = b"NDRX"
WIRE_VERSION = 1
_HEADER = struct.Struct("!4sBBHQQQQHIQ")


class WireProtocolError(RuntimeError):
    pass


class WirePacket:
    """Scatter/gather representation of one Nodrix wire message.

    Large payloads remain memoryviews over their original buffers. On Unix,
    :func:`send_packet` uses ``sendmsg`` so the Python runtime does not build a
    second contiguous payload copy before handing data to the kernel.
    """

    __slots__ = ("header", "type_name", "metadata", "payload_parts")

    def __init__(
        self,
        header: bytes,
        type_name: bytes,
        metadata: bytes,
        payload_parts: tuple[memoryview, ...],
    ) -> None:
        self.header = header
        self.type_name = type_name
        self.metadata = metadata
        self.payload_parts = payload_parts

    def parts(self) -> tuple[memoryview, ...]:
        return (
            memoryview(self.header),
            memoryview(self.type_name),
            memoryview(self.metadata),
            *self.payload_parts,
        )

    @property
    def nbytes(self) -> int:
        return sum(part.nbytes for part in self.parts())


Encoder = Callable[[Any], tuple[dict[str, Any], Iterable[memoryview]]]
Decoder = Callable[[memoryview, dict[str, Any]], Any]
_CUSTOM_CODECS: dict[str, tuple[Encoder, Decoder]] = {}


def register_wire_codec(type_name: str, encoder: Encoder, decoder: Decoder) -> None:
    if not type_name:
        raise ValueError("type_name must not be empty")
    _CUSTOM_CODECS[type_name] = (encoder, decoder)


def _trace_u64(value: int | str) -> tuple[int, str | None]:
    if isinstance(value, int):
        return value & ((1 << 64) - 1), None
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big"), value


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "value"):
        return value.value
    if np is not None:
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes_hex__": bytes(value).hex()}
    return str(value)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _byte_view(value: Any) -> memoryview:
    view = memoryview(value)
    if not view.contiguous:
        raise ValueError("Nodrix network payloads must be contiguous")
    return view if view.format == "B" else view.cast("B")


def _array_segment(array: Any) -> tuple[Any, memoryview, dict[str, Any]]:
    if np is None:
        raise RuntimeError("NumPy is required for structured array wire codecs")
    value = np.asarray(array)
    if not value.flags.c_contiguous:
        value = np.ascontiguousarray(value)
    view = _byte_view(value)
    return value, view, {
        "dtype": str(value.dtype),
        "shape": [int(item) for item in value.shape],
        "nbytes": view.nbytes,
    }


def _encode_payload(message: Message) -> tuple[dict[str, Any], tuple[memoryview, ...]]:
    custom = _CUSTOM_CODECS.get(message.type)
    if custom is not None:
        metadata, parts = custom[0](message.payload)
        return {"codec": "custom", "custom": metadata}, tuple(_byte_view(part) for part in parts)

    payload = message.payload
    if isinstance(payload, ManagedBuffer):
        if not payload.host_accessible:
            raise WireProtocolError(
                f"Cannot serialize device-only {payload.memory_type.value} buffer on {payload.device}; "
                "insert an explicit device adapter, encoded media branch, or same-device consumer"
            )
        return {
            "codec": "raw",
            "memory_type": payload.memory_type.value,
            "device": payload.device,
            "readonly": payload.readonly,
        }, (payload.memoryview(),)
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return {"codec": "raw", "readonly": memoryview(payload).readonly}, (_byte_view(payload),)
    if isinstance(payload, Frame):
        if not payload.buffer.host_accessible:
            raise WireProtocolError(
                f"Cannot serialize device-only Frame from {payload.buffer.memory_type.value}; "
                "export an encoded stream or add an explicit transfer node"
            )
        return {
            "codec": "frame",
            "width": payload.width,
            "height": payload.height,
            "pixel_format": payload.pixel_format.value,
            "stride": payload.stride,
            "channels": payload.channels,
            "dtype": payload.dtype,
            "shape": payload.shape,
            "frame_metadata": payload.metadata,
            "memory_type": payload.buffer.memory_type.value,
            "device": payload.buffer.device,
        }, (payload.buffer.memoryview(),)
    if isinstance(payload, EncodedFrame):
        if not payload.buffer.host_accessible:
            raise WireProtocolError("EncodedFrame payload is not host-accessible")
        return {
            "codec": "encoded_frame",
            "media_codec": payload.codec.value,
            "width": payload.width,
            "height": payload.height,
            "fps": payload.fps,
            "keyframe": payload.keyframe,
            "pts_ns": payload.pts_ns,
            "frame_metadata": payload.metadata,
            "memory_type": payload.buffer.memory_type.value,
            "device": payload.buffer.device,
        }, (payload.buffer.memoryview(),)
    if isinstance(payload, Tensor):
        if not payload.buffer.host_accessible:
            raise WireProtocolError(
                f"Cannot serialize device-only Tensor from {payload.buffer.memory_type.value}; "
                "use DLPack/CUDA IPC inside the host or add an explicit download node"
            )
        return {
            "codec": "tensor",
            "shape": payload.shape,
            "dtype": payload.dtype,
            "layout": payload.layout.value,
            "tensor_metadata": payload.metadata,
            "memory_type": payload.buffer.memory_type.value,
            "device": payload.buffer.device,
        }, (payload.buffer.memoryview(),)

    if isinstance(payload, Detections):
        fields: dict[str, Any] = {}
        parts: list[memoryview] = []
        for name in ("boxes", "scores", "class_ids"):
            _, part, spec = _array_segment(getattr(payload, name))
            fields[name] = spec
            parts.append(part)
        return {
            "codec": "detections",
            "fields": fields,
            "box_format": payload.box_format.value,
            "coordinate_space": payload.coordinate_space.value,
            "labels": payload.labels,
            "attributes": payload.attributes,
        }, tuple(parts)

    if isinstance(payload, Tracks):
        fields = {}
        parts = []
        for name in ("boxes", "track_ids", "scores", "class_ids"):
            _, part, spec = _array_segment(getattr(payload, name))
            fields[name] = spec
            parts.append(part)
        return {
            "codec": "tracks",
            "fields": fields,
            "states": payload.states,
            "box_format": payload.box_format.value,
            "coordinate_space": payload.coordinate_space.value,
            "attributes": payload.attributes,
        }, tuple(parts)

    if isinstance(payload, Embeddings):
        fields = {}
        parts = []
        _, part, spec = _array_segment(payload.values)
        fields["values"] = spec
        parts.append(part)
        if payload.object_ids is not None:
            _, part, spec = _array_segment(payload.object_ids)
            fields["object_ids"] = spec
            parts.append(part)
        return {
            "codec": "embeddings",
            "fields": fields,
            "normalized": payload.normalized,
        }, tuple(parts)

    if isinstance(payload, Identities):
        fields = {}
        parts = []
        for name in ("track_ids", "object_ids", "similarities"):
            _, part, spec = _array_segment(getattr(payload, name))
            fields[name] = spec
            parts.append(part)
        return {"codec": "identities", "fields": fields}, tuple(parts)

    encoded = _json_bytes(payload)
    return {"codec": "json"}, (memoryview(encoded),)


def encode_message(message: Message) -> WirePacket:
    codec_meta, payload_parts = _encode_payload(message)
    type_bytes = message.type.encode("utf-8")
    trace_id, trace_text = _trace_u64(message.trace_id)
    definition = TYPE_REGISTRY.definition(message.type)
    metadata = {
        "stream_id": message.stream_id,
        "message_metadata": message.metadata,
        "codec": codec_meta,
        "schema_version": definition.version if definition is not None else 1,
    }
    if trace_text is not None:
        metadata["trace_text"] = trace_text
    metadata_bytes = _json_bytes(metadata)
    payload_len = sum(part.nbytes for part in payload_parts)
    header = _HEADER.pack(
        MAGIC,
        WIRE_VERSION,
        0,
        len(payload_parts),
        int(message.sequence) & ((1 << 64) - 1),
        int(message.timestamp_ns) & ((1 << 64) - 1),
        int(message.created_ns) & ((1 << 64) - 1),
        trace_id,
        len(type_bytes),
        len(metadata_bytes),
        payload_len,
    )
    return WirePacket(header, type_bytes, metadata_bytes, payload_parts)


def _send_all(sock: socket.socket, view: memoryview) -> None:
    while view:
        sent = sock.send(view)
        if sent <= 0:
            raise ConnectionError("socket closed while sending Nodrix message")
        view = view[sent:]


def send_packet(sock: socket.socket, packet: WirePacket) -> int:
    parts = list(packet.parts())
    total = sum(part.nbytes for part in parts)
    if hasattr(sock, "sendmsg") and not isinstance(sock, ssl.SSLSocket):
        while parts:
            sent = sock.sendmsg(parts)
            if sent <= 0:
                raise ConnectionError("socket closed while sending Nodrix message")
            remaining = sent
            next_parts: list[memoryview] = []
            for index, part in enumerate(parts):
                if remaining >= part.nbytes:
                    remaining -= part.nbytes
                    continue
                if remaining:
                    part = part[remaining:]
                    remaining = 0
                next_parts = [part, *parts[index + 1 :]]
                break
            parts = next_parts
    else:  # pragma: no cover - Windows fallback
        for part in parts:
            _send_all(sock, part)
    return total


def _recv_exact(sock: socket.socket, size: int) -> bytearray:
    data = bytearray(size)
    view = memoryview(data)
    offset = 0
    while offset < size:
        count = sock.recv_into(view[offset:])
        if count <= 0:
            raise EOFError("socket closed while receiving Nodrix message")
        offset += count
    return data


def _decode_array(payload: memoryview, spec: dict[str, Any], offset: int) -> tuple[Any, int]:
    if np is None:
        raise RuntimeError("NumPy is required to decode this Nodrix message")
    nbytes = int(spec["nbytes"])
    part = payload[offset : offset + nbytes]
    value = np.frombuffer(part, dtype=np.dtype(spec["dtype"])).reshape(tuple(spec["shape"]))
    value.flags.writeable = False
    return value, offset + nbytes


def _decode_payload(type_name: str, payload: memoryview, metadata: dict[str, Any]) -> Any:
    codec_meta = metadata["codec"]
    codec = codec_meta["codec"]
    if codec == "custom":
        custom = _CUSTOM_CODECS.get(type_name)
        if custom is None:
            raise WireProtocolError(f"No custom wire codec registered for {type_name!r}")
        return custom[1](payload, codec_meta.get("custom", {}))
    if codec == "raw":
        return ManagedBuffer(
            owner=payload,
            readonly=True,
            memory_type=MemoryType(codec_meta.get("memory_type", "cpu")),
            device=codec_meta.get("device", "cpu"),
        )
    if codec == "frame":
        return Frame(
            buffer=ManagedBuffer(owner=payload, readonly=True, memory_type=MemoryType.CPU),
            width=int(codec_meta["width"]),
            height=int(codec_meta["height"]),
            pixel_format=codec_meta["pixel_format"],
            stride=codec_meta.get("stride"),
            channels=codec_meta.get("channels"),
            dtype=codec_meta.get("dtype", "uint8"),
            shape=tuple(codec_meta["shape"]) if codec_meta.get("shape") else None,
            metadata=dict(codec_meta.get("frame_metadata") or {}),
        )
    if codec == "encoded_frame":
        return EncodedFrame(
            buffer=ManagedBuffer(owner=payload, readonly=True, memory_type=MemoryType.CPU),
            codec=MediaCodec(codec_meta.get("media_codec", "unknown")),
            width=int(codec_meta.get("width", 0)),
            height=int(codec_meta.get("height", 0)),
            fps=float(codec_meta.get("fps", 0.0)),
            keyframe=bool(codec_meta.get("keyframe", True)),
            pts_ns=int(codec_meta.get("pts_ns", 0)),
            metadata=dict(codec_meta.get("frame_metadata") or {}),
        )
    if codec == "tensor":
        return Tensor(
            buffer=ManagedBuffer(owner=payload, readonly=True, memory_type=MemoryType.CPU),
            shape=tuple(codec_meta["shape"]),
            dtype=codec_meta["dtype"],
            layout=codec_meta.get("layout", "unknown"),
            metadata=dict(codec_meta.get("tensor_metadata") or {}),
        )
    if codec == "json":
        return json.loads(bytes(payload).decode("utf-8"))

    fields = codec_meta.get("fields", {})
    values: dict[str, Any] = {}
    offset = 0
    for name, spec in fields.items():
        values[name], offset = _decode_array(payload, spec, offset)
    if codec == "detections":
        return Detections(
            **values,
            box_format=codec_meta["box_format"],
            coordinate_space=codec_meta["coordinate_space"],
            labels=codec_meta.get("labels"),
            attributes=codec_meta.get("attributes"),
        )
    if codec == "tracks":
        return Tracks(
            **values,
            states=codec_meta.get("states"),
            box_format=codec_meta["box_format"],
            coordinate_space=codec_meta["coordinate_space"],
            attributes=codec_meta.get("attributes"),
        )
    if codec == "embeddings":
        return Embeddings(**values, normalized=bool(codec_meta.get("normalized", False)))
    if codec == "identities":
        return Identities(**values)
    raise WireProtocolError(f"Unknown Nodrix payload codec: {codec!r}")



def decode_packet_parts(
    header_bytes: bytes | bytearray | memoryview,
    type_bytes: bytes | bytearray | memoryview,
    metadata_bytes: bytes | bytearray | memoryview,
    payload: bytes | bytearray | memoryview,
) -> Message:
    """Decode a wire packet whose payload may live in shared memory.

    Unlike :func:`recv_message`, this function does not copy the payload. The
    returned SDK object keeps a view over ``payload``. It is used by the local
    shared-memory/process data plane and by the ``.ndrx`` reader.
    """
    header_view = memoryview(header_bytes)
    if header_view.nbytes != _HEADER.size:
        raise WireProtocolError(f"Invalid Nodrix header size: {header_view.nbytes}")
    (
        magic, version, _flags, _segments, sequence, timestamp_ns, created_ns,
        trace_id, type_len, metadata_len, payload_len,
    ) = _HEADER.unpack(header_view)
    if magic != MAGIC:
        raise WireProtocolError(f"Invalid Nodrix wire magic: {magic!r}")
    if version != WIRE_VERSION:
        raise WireProtocolError(f"Unsupported Nodrix wire version: {version}")
    type_view = memoryview(type_bytes)
    metadata_view = memoryview(metadata_bytes)
    payload_view = memoryview(payload)
    if type_view.nbytes != type_len or metadata_view.nbytes != metadata_len or payload_view.nbytes != payload_len:
        raise WireProtocolError("Nodrix packet part lengths do not match the header")
    type_name = bytes(type_view).decode("utf-8")
    metadata = json.loads(bytes(metadata_view).decode("utf-8"))
    definition = TYPE_REGISTRY.definition(type_name)
    schema_version = int(metadata.get("schema_version", 1))
    if definition is not None and schema_version not in definition.compatible_versions:
        raise WireProtocolError(
            f"Incompatible schema version for {type_name}: received {schema_version}, "
            f"supported {definition.compatible_versions}"
        )
    readonly_payload = payload_view if payload_view.readonly else payload_view.toreadonly()
    decoded = _decode_payload(type_name, readonly_payload, metadata)
    return Message(
        type=type_name, payload=decoded, sequence=sequence, timestamp_ns=timestamp_ns,
        stream_id=metadata.get("stream_id", ""),
        trace_id=metadata.get("trace_text", trace_id),
        metadata=dict(metadata.get("message_metadata") or {}), created_ns=created_ns,
    )


def read_message(stream: Any) -> Message:
    """Read one complete wire message from a binary file-like object."""
    header = stream.read(_HEADER.size)
    if not header:
        raise EOFError
    if len(header) != _HEADER.size:
        raise WireProtocolError("Truncated Nodrix wire header")
    unpacked = _HEADER.unpack(header)
    type_len, metadata_len, payload_len = unpacked[-3:]
    type_bytes = stream.read(type_len)
    metadata_bytes = stream.read(metadata_len)
    payload = stream.read(payload_len)
    if len(type_bytes) != type_len or len(metadata_bytes) != metadata_len or len(payload) != payload_len:
        raise WireProtocolError("Truncated Nodrix wire message")
    return decode_packet_parts(header, type_bytes, metadata_bytes, payload)

def recv_message(sock: socket.socket, *, max_message_bytes: int = 256 * 1024 * 1024) -> Message:
    header_bytes = _recv_exact(sock, _HEADER.size)
    (
        magic,
        version,
        _flags,
        _segments,
        sequence,
        timestamp_ns,
        created_ns,
        trace_id,
        type_len,
        metadata_len,
        payload_len,
    ) = _HEADER.unpack(header_bytes)
    if magic != MAGIC:
        raise WireProtocolError(f"Invalid Nodrix wire magic: {magic!r}")
    if version != WIRE_VERSION:
        raise WireProtocolError(f"Unsupported Nodrix wire version: {version}")
    total_size = int(type_len) + int(metadata_len) + int(payload_len)
    if type_len > 4096 or metadata_len > 16 * 1024 * 1024 or total_size > int(max_message_bytes):
        raise WireProtocolError(
            f"Nodrix message exceeds configured limits: type={type_len}, metadata={metadata_len}, payload={payload_len}"
        )
    type_name = bytes(_recv_exact(sock, type_len)).decode("utf-8")
    metadata = json.loads(bytes(_recv_exact(sock, metadata_len)).decode("utf-8"))
    definition = TYPE_REGISTRY.definition(type_name)
    schema_version = int(metadata.get("schema_version", 1))
    if definition is not None and schema_version not in definition.compatible_versions:
        raise WireProtocolError(
            f"Incompatible schema version for {type_name}: received {schema_version}, "
            f"supported {definition.compatible_versions}"
        )
    payload_owner = _recv_exact(sock, payload_len)
    payload_view = memoryview(payload_owner).toreadonly()
    payload = _decode_payload(type_name, payload_view, metadata)
    return Message(
        type=type_name,
        payload=payload,
        sequence=sequence,
        timestamp_ns=timestamp_ns,
        stream_id=metadata.get("stream_id", ""),
        trace_id=metadata.get("trace_text", trace_id),
        metadata=dict(metadata.get("message_metadata") or {}),
        created_ns=created_ns,
    )


def encode_registered_payload(type_name: str, payload: Any) -> tuple[dict[str, Any], tuple[memoryview, ...]]:
    """Encode a registered custom payload for local native plugins or transports."""
    custom = _CUSTOM_CODECS.get(type_name)
    if custom is None:
        raise KeyError(type_name)
    metadata, parts = custom[0](payload)
    return metadata, tuple(_byte_view(part) for part in parts)


def decode_registered_payload(type_name: str, payload: Any, metadata: dict[str, Any]) -> Any:
    """Decode a registered custom payload from a contiguous buffer."""
    custom = _CUSTOM_CODECS.get(type_name)
    if custom is None:
        raise KeyError(type_name)
    return custom[1](_byte_view(payload), metadata)


def has_registered_wire_codec(type_name: str) -> bool:
    return type_name in _CUSTOM_CODECS
