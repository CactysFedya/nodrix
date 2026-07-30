from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Mapping, Sequence

from .memory import DmaBufHandle, dlpack_memory_type, infer_shape_dtype, object_dlpack_device

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None


class MemoryType(StrEnum):
    CPU = "cpu"
    PINNED_CPU = "pinned_cpu"
    SHARED = "shared"
    DMA_BUF = "dma_buf"
    CUDA = "cuda"
    ROCM = "rocm"
    VULKAN = "vulkan"
    OPENCL = "opencl"
    METAL = "metal"
    NPU = "npu"
    EXTERNAL = "external"


class PixelFormat(StrEnum):
    BGR8 = "bgr8"
    RGB8 = "rgb8"
    GRAY8 = "gray8"
    BGRA8 = "bgra8"
    RGBA8 = "rgba8"
    NV12 = "nv12"
    YUYV = "yuyv"
    JPEG = "jpeg"
    H264 = "h264"
    H265 = "h265"
    UNKNOWN = "unknown"


class MediaCodec(StrEnum):
    JPEG = "jpeg"
    MJPEG = "mjpeg"
    PNG = "png"
    H264 = "h264"
    H265 = "h265"
    UNKNOWN = "unknown"


class TensorLayout(StrEnum):
    NCHW = "nchw"
    NHWC = "nhwc"
    CHW = "chw"
    HWC = "hwc"
    NC = "nc"
    C = "c"
    UNKNOWN = "unknown"


class BoxFormat(StrEnum):
    XYXY = "xyxy"
    XYWH = "xywh"
    CXCYWH = "cxcywh"


class CoordinateSpace(StrEnum):
    PIXELS = "pixels"
    NORMALIZED = "normalized"


@dataclass(slots=True)
class ManagedBuffer:
    """Owning or non-owning handle for host and device memory.

    Host-backed buffers expose the Python buffer protocol through
    :meth:`memoryview`. Device-only buffers keep an opaque handle and may be
    consumed through DLPack, DMA-BUF, CUDA IPC, Vulkan/OpenCL or a backend
    plugin without an implicit CPU copy.
    """

    owner: Any = None
    readonly: bool = True
    memory_type: MemoryType = MemoryType.CPU
    device: str = "cpu"
    offset: int = 0
    length: int | None = None
    lease: Any | None = None
    handle: Any | None = None
    nbytes_hint: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def host_accessible(self) -> bool:
        if self.owner is None:
            return False
        try:
            memoryview(self.owner)
            return True
        except TypeError:
            return False

    def memoryview(self) -> memoryview:
        if not self.host_accessible:
            raise TypeError(
                f"Nodrix {self.memory_type.value} buffer on {self.device!r} is device-only; "
                "use DLPack or the matching device backend instead of forcing a CPU copy"
            )
        view = memoryview(self.owner)
        if not view.contiguous:
            raise ValueError("Nodrix buffers must be contiguous")
        byte_view = view.cast("B") if view.format != "B" else view
        end = None if self.length is None else self.offset + self.length
        sliced = byte_view[self.offset:end]
        return sliced.toreadonly() if self.readonly and not sliced.readonly else sliced

    @property
    def nbytes(self) -> int:
        if self.nbytes_hint is not None:
            return int(self.nbytes_hint)
        if self.host_accessible:
            return self.memoryview().nbytes
        handle_size = getattr(self.handle, "nbytes", None)
        if handle_size is not None:
            return int(handle_size)
        raise ValueError("Device-only Nodrix buffer has no nbytes_hint")

    def __dlpack_device__(self) -> tuple[int, int]:
        provider = self.owner if self.owner is not None else self.handle
        method = getattr(provider, "__dlpack_device__", None)
        if method is None:
            if self.memory_type in (MemoryType.CPU, MemoryType.SHARED):
                return 1, 0
            if self.memory_type == MemoryType.PINNED_CPU:
                return 3, 0
            if self.memory_type == MemoryType.CUDA:
                index = int(self.device.split(":", 1)[1]) if ":" in self.device else 0
                return 2, index
            if self.memory_type == MemoryType.ROCM:
                index = int(self.device.split(":", 1)[1]) if ":" in self.device else 0
                return 10, index
            if self.memory_type == MemoryType.VULKAN:
                return 7, 0
            if self.memory_type == MemoryType.OPENCL:
                return 4, 0
            if self.memory_type == MemoryType.METAL:
                return 8, 0
            raise TypeError(f"Buffer on {self.memory_type.value} has no DLPack provider")
        device = method()
        return int(device[0]), int(device[1])

    def __dlpack__(self, stream: Any = None, max_version: Any = None, dl_device: Any = None, copy: Any = None) -> Any:
        provider = self.owner if self.owner is not None else self.handle
        method = getattr(provider, "__dlpack__", None)
        if method is None:
            raise TypeError(f"Buffer on {self.memory_type.value} does not expose DLPack")
        kwargs: dict[str, Any] = {}
        if stream is not None:
            kwargs["stream"] = stream
        if max_version is not None:
            kwargs["max_version"] = max_version
        if dl_device is not None:
            kwargs["dl_device"] = dl_device
        if copy is not None:
            kwargs["copy"] = copy
        try:
            return method(**kwargs)
        except TypeError:
            # Older array libraries accept only the stream argument.
            return method(stream=stream) if stream is not None else method()

    def to_dlpack(self, *, stream: Any = None) -> Any:
        return self.__dlpack__(stream=stream)

    def release(self) -> None:
        owner = self.owner
        self.owner = None
        if isinstance(owner, memoryview):
            try:
                owner.release()
            except (BufferError, ValueError):
                pass
        lease = self.lease
        self.lease = None
        if lease is not None and hasattr(lease, "release"):
            lease.release()
        handle = self.handle
        self.handle = None
        if handle is not None and handle is not owner and hasattr(handle, "close"):
            handle.close()

    def __del__(self) -> None:  # pragma: no cover - GC timing is implementation-specific
        try:
            self.release()
        except Exception:
            pass

    @classmethod
    def wrap(
        cls,
        value: Any,
        *,
        readonly: bool | None = None,
        memory_type: MemoryType = MemoryType.CPU,
        device: str = "cpu",
    ) -> "ManagedBuffer":
        view = memoryview(value)
        return cls(
            owner=value,
            readonly=view.readonly if readonly is None else readonly,
            memory_type=memory_type,
            device=device,
            nbytes_hint=view.nbytes,
        )

    @classmethod
    def from_dlpack(cls, value: Any, *, readonly: bool = False, nbytes: int | None = None) -> "ManagedBuffer":
        device_tuple = object_dlpack_device(value)
        memory_name, device = dlpack_memory_type(device_tuple or (1, 0))
        return cls(
            owner=value,
            readonly=readonly,
            memory_type=MemoryType(memory_name),
            device=device,
            nbytes_hint=nbytes,
            metadata={"interop": "dlpack"},
        )

    @classmethod
    def from_dmabuf(
        cls,
        handle: DmaBufHandle,
        *,
        readonly: bool = True,
        mapped_owner: Any | None = None,
    ) -> "ManagedBuffer":
        return cls(
            owner=mapped_owner,
            readonly=readonly,
            memory_type=MemoryType.DMA_BUF,
            device=handle.device,
            handle=handle,
            nbytes_hint=handle.nbytes,
            metadata={"format": handle.format, "planes": len(handle.planes)},
        )


@dataclass(slots=True)
class Frame:
    buffer: ManagedBuffer
    width: int
    height: int
    pixel_format: PixelFormat = PixelFormat.BGR8
    stride: int | None = None
    channels: int | None = None
    dtype: str = "uint8"
    shape: tuple[int, ...] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.pixel_format = PixelFormat(self.pixel_format)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Frame width and height must be positive")
        if self.stride is not None and self.stride <= 0:
            raise ValueError("Frame stride must be positive")

    @classmethod
    def from_numpy(
        cls,
        array: Any,
        *,
        pixel_format: PixelFormat | str = PixelFormat.BGR8,
        readonly: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> "Frame":
        if np is None:
            raise RuntimeError("NumPy is required for Frame.from_numpy")
        if not isinstance(array, np.ndarray):
            raise TypeError("Frame.from_numpy expects numpy.ndarray")
        if not array.flags.c_contiguous:
            raise ValueError("Frame NumPy array must be C-contiguous; make the copy explicitly")
        if array.ndim not in (2, 3):
            raise ValueError("Frame array must have shape HxW or HxWxC")
        height, width = int(array.shape[0]), int(array.shape[1])
        channels = 1 if array.ndim == 2 else int(array.shape[2])
        return cls(
            buffer=ManagedBuffer.wrap(array, readonly=readonly),
            width=width,
            height=height,
            pixel_format=PixelFormat(pixel_format),
            stride=int(array.strides[0]),
            channels=channels,
            dtype=str(array.dtype),
            shape=tuple(int(v) for v in array.shape),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_dmabuf(
        cls,
        handle: DmaBufHandle,
        *,
        width: int,
        height: int,
        pixel_format: PixelFormat | str,
        stride: int | None = None,
        mapped_owner: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "Frame":
        return cls(
            buffer=ManagedBuffer.from_dmabuf(handle, mapped_owner=mapped_owner),
            width=width,
            height=height,
            pixel_format=PixelFormat(pixel_format),
            stride=stride,
            metadata=dict(metadata or {}),
        )

    def numpy(self, *, writable: bool = False) -> Any:
        if np is None:
            raise RuntimeError("NumPy is required for Frame.numpy")
        if writable and self.buffer.readonly:
            raise ValueError("Frame buffer is read-only; request a writable buffer explicitly")
        shape = self.shape
        if shape is None:
            channels = self.channels or 1
            shape = (self.height, self.width) if channels == 1 else (self.height, self.width, channels)
        array = np.frombuffer(self.buffer.memoryview(), dtype=np.dtype(self.dtype)).reshape(shape)
        if self.buffer.readonly:
            array.flags.writeable = False
        return array


@dataclass(slots=True)
class EncodedFrame:
    """Compressed image/video access unit carried by Nodrix.

    JPEG/PNG payloads contain one complete image. H.264/H.265 payloads may
    contain an access unit or an ordered Annex-B byte chunk and require a stateful decoder. The buffer remains
    immutable and can be sent through the Nodrix wire protocol without an
    additional Python-side payload copy.
    """

    buffer: ManagedBuffer
    codec: MediaCodec = MediaCodec.JPEG
    width: int = 0
    height: int = 0
    fps: float = 0.0
    keyframe: bool = True
    pts_ns: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.codec = MediaCodec(self.codec)
        if self.width < 0 or self.height < 0:
            raise ValueError("EncodedFrame dimensions cannot be negative")
        if self.fps < 0:
            raise ValueError("EncodedFrame fps cannot be negative")

    @property
    def nbytes(self) -> int:
        return self.buffer.nbytes

    def memoryview(self) -> memoryview:
        return self.buffer.memoryview()


@dataclass(slots=True)
class Tensor:
    buffer: ManagedBuffer
    shape: tuple[int, ...]
    dtype: str
    layout: TensorLayout = TensorLayout.UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.layout = TensorLayout(self.layout)
        if not self.shape or any(int(dim) <= 0 for dim in self.shape):
            raise ValueError("Tensor shape dimensions must be positive")

    @classmethod
    def from_numpy(
        cls,
        array: Any,
        *,
        layout: TensorLayout | str = TensorLayout.UNKNOWN,
        readonly: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> "Tensor":
        if np is None or not isinstance(array, np.ndarray):
            raise TypeError("Tensor.from_numpy expects numpy.ndarray")
        if not array.flags.c_contiguous:
            raise ValueError("Tensor NumPy array must be C-contiguous")
        return cls(
            buffer=ManagedBuffer.wrap(array, readonly=readonly),
            shape=tuple(int(v) for v in array.shape),
            dtype=str(array.dtype),
            layout=TensorLayout(layout),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_dlpack(
        cls,
        value: Any,
        *,
        shape: Sequence[int] | None = None,
        dtype: str | None = None,
        layout: TensorLayout | str = TensorLayout.UNKNOWN,
        readonly: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> "Tensor":
        inferred_shape, inferred_dtype = infer_shape_dtype(value)
        final_shape = tuple(int(item) for item in (shape or inferred_shape or ()))
        final_dtype = dtype or inferred_dtype
        if not final_shape or not final_dtype:
            raise ValueError("Tensor.from_dlpack requires shape and dtype when the provider does not expose them")
        itemsize = None
        if np is not None:
            try:
                itemsize = int(np.dtype(final_dtype).itemsize)
            except TypeError:
                itemsize = None
        nbytes = None if itemsize is None else itemsize * int(__import__("math").prod(final_shape))
        return cls(
            buffer=ManagedBuffer.from_dlpack(value, readonly=readonly, nbytes=nbytes),
            shape=final_shape,
            dtype=str(final_dtype),
            layout=TensorLayout(layout),
            metadata={"interop": "dlpack", **dict(metadata or {})},
        )

    def __dlpack_device__(self) -> tuple[int, int]:
        return self.buffer.__dlpack_device__()

    def __dlpack__(self, stream: Any = None, max_version: Any = None, dl_device: Any = None, copy: Any = None) -> Any:
        return self.buffer.__dlpack__(stream=stream, max_version=max_version, dl_device=dl_device, copy=copy)

    def to_dlpack(self, *, stream: Any = None) -> Any:
        return self.buffer.to_dlpack(stream=stream)

    def numpy(self, *, writable: bool = False, copy: bool = False) -> Any:
        if np is None:
            raise RuntimeError("NumPy is required for Tensor.numpy")
        if self.buffer.host_accessible:
            if writable and self.buffer.readonly:
                raise ValueError("Tensor buffer is read-only")
            array = np.frombuffer(self.buffer.memoryview(), dtype=np.dtype(self.dtype)).reshape(self.shape)
            if self.buffer.readonly:
                array.flags.writeable = False
            return array.copy() if copy else array
        if not copy:
            raise TypeError(
                f"Tensor lives on {self.buffer.device}; Tensor.numpy(copy=False) would require a hidden device-to-host transfer"
            )
        try:
            return np.from_dlpack(self).copy()
        except Exception as exc:
            raise RuntimeError("The installed NumPy/backend cannot import this DLPack tensor") from exc


@dataclass(slots=True)
class Detections:
    boxes: Any
    scores: Any
    class_ids: Any
    box_format: BoxFormat = BoxFormat.XYXY
    coordinate_space: CoordinateSpace = CoordinateSpace.PIXELS
    labels: Sequence[str] | None = None
    attributes: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        self.box_format = BoxFormat(self.box_format)
        self.coordinate_space = CoordinateSpace(self.coordinate_space)
        if np is not None:
            self.boxes = np.asarray(self.boxes, dtype=np.float32)
            self.scores = np.asarray(self.scores, dtype=np.float32)
            self.class_ids = np.asarray(self.class_ids, dtype=np.int32)
            if self.boxes.ndim != 2 or self.boxes.shape[1] != 4:
                raise ValueError("Detections.boxes must have shape [N, 4]")
            count = int(self.boxes.shape[0])
            if self.scores.shape != (count,) or self.class_ids.shape != (count,):
                raise ValueError("Detections scores/class_ids must have shape [N]")
        else:
            if not (len(self.boxes) == len(self.scores) == len(self.class_ids)):
                raise ValueError("Detections arrays must have the same length")

    def __len__(self) -> int:
        return len(self.scores)


@dataclass(slots=True)
class Tracks:
    boxes: Any
    track_ids: Any
    scores: Any
    class_ids: Any
    states: Sequence[str] | None = None
    box_format: BoxFormat = BoxFormat.XYXY
    coordinate_space: CoordinateSpace = CoordinateSpace.PIXELS
    attributes: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        self.box_format = BoxFormat(self.box_format)
        self.coordinate_space = CoordinateSpace(self.coordinate_space)
        if np is not None:
            self.boxes = np.asarray(self.boxes, dtype=np.float32)
            self.track_ids = np.asarray(self.track_ids, dtype=np.int64)
            self.scores = np.asarray(self.scores, dtype=np.float32)
            self.class_ids = np.asarray(self.class_ids, dtype=np.int32)
            if self.boxes.ndim != 2 or self.boxes.shape[1] != 4:
                raise ValueError("Tracks.boxes must have shape [N, 4]")
            count = int(self.boxes.shape[0])
            if any(value.shape != (count,) for value in (self.track_ids, self.scores, self.class_ids)):
                raise ValueError("Tracks arrays must have shape [N]")
        else:
            lengths = {len(self.boxes), len(self.track_ids), len(self.scores), len(self.class_ids)}
            if len(lengths) != 1:
                raise ValueError("Tracks arrays must have the same length")

    def __len__(self) -> int:
        return len(self.track_ids)


@dataclass(slots=True)
class Embeddings:
    values: Any
    object_ids: Any | None = None
    normalized: bool = False

    def __post_init__(self) -> None:
        if np is not None:
            self.values = np.asarray(self.values, dtype=np.float32)
            if self.values.ndim != 2:
                raise ValueError("Embeddings.values must have shape [N, D]")
            if self.object_ids is not None:
                self.object_ids = np.asarray(self.object_ids, dtype=np.int64)
                if self.object_ids.shape != (self.values.shape[0],):
                    raise ValueError("Embeddings.object_ids must have shape [N]")


@dataclass(slots=True)
class Identities:
    track_ids: Any
    object_ids: Any
    similarities: Any

    def __post_init__(self) -> None:
        if np is not None:
            self.track_ids = np.asarray(self.track_ids, dtype=np.int64)
            self.object_ids = np.asarray(self.object_ids, dtype=np.int64)
            self.similarities = np.asarray(self.similarities, dtype=np.float32)
            if not (self.track_ids.shape == self.object_ids.shape == self.similarities.shape):
                raise ValueError("Identity arrays must have matching shapes")


@dataclass(frozen=True, slots=True)
class TypeDefinition:
    name: str
    payload_type: type[Any] | tuple[type[Any], ...] | None = None
    validator: Callable[[Any], None] | None = None
    description: str = ""
    version: int = 1
    compatible_versions: tuple[int, ...] = (1,)

    def validate(self, payload: Any) -> None:
        if self.payload_type is not None and not isinstance(payload, self.payload_type):
            expected = (
                ", ".join(item.__name__ for item in self.payload_type)
                if isinstance(self.payload_type, tuple)
                else self.payload_type.__name__
            )
            raise TypeError(f"{self.name} expects payload {expected}, got {type(payload).__name__}")
        if self.validator is not None:
            self.validator(payload)


class TypeRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, TypeDefinition] = {}

    def register(
        self,
        name: str,
        payload_type: type[Any] | tuple[type[Any], ...] | None = None,
        *,
        validator: Callable[[Any], None] | None = None,
        description: str = "",
        version: int = 1,
        compatible_versions: tuple[int, ...] | None = None,
        replace: bool = False,
    ) -> None:
        if name in self._definitions and not replace:
            raise ValueError(f"Message type is already registered: {name}")
        version = int(version)
        if version <= 0:
            raise ValueError("Message schema version must be positive")
        compatible = tuple(sorted(set(compatible_versions or (version,))))
        self._definitions[name] = TypeDefinition(
            name, payload_type, validator, description, version, compatible
        )

    def definition(self, name: str) -> TypeDefinition | None:
        return self._definitions.get(name)

    def validate(self, name: str, payload: Any) -> None:
        if name in {"core.any", "core.object"}:
            return
        definition = self._definitions.get(name)
        if definition is None:
            # User-defined types are allowed; the graph still enforces exact
            # producer/consumer type names. Register a validator for deeper checks.
            return
        definition.validate(payload)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))


TYPE_REGISTRY = TypeRegistry()
TYPE_REGISTRY.register("core.any")
TYPE_REGISTRY.register("core.object")
def _validate_buffer_protocol(value: Any) -> None:
    try:
        view = memoryview(value.owner if isinstance(value, ManagedBuffer) else value)
    except TypeError as exc:
        raise TypeError(f"Payload does not implement the buffer protocol: {type(value).__name__}") from exc
    if not view.contiguous:
        raise ValueError("Buffer payload must be contiguous")


TYPE_REGISTRY.register("core.bytes", validator=_validate_buffer_protocol)
TYPE_REGISTRY.register("core.buffer", validator=_validate_buffer_protocol)
TYPE_REGISTRY.register("vision.frame", Frame)
TYPE_REGISTRY.register("vision.encoded_frame", EncodedFrame)
TYPE_REGISTRY.register("vision.tensor", Tensor)
TYPE_REGISTRY.register("vision.detections", Detections)
TYPE_REGISTRY.register("vision.tracks", Tracks)
TYPE_REGISTRY.register("vision.identified_tracks", Tracks)
TYPE_REGISTRY.register("vision.embeddings", Embeddings)
TYPE_REGISTRY.register("vision.identities", Identities)


def register_message_type(
    name: str,
    payload_type: type[Any] | tuple[type[Any], ...] | None = None,
    *,
    validator: Callable[[Any], None] | None = None,
    description: str = "",
    version: int = 1,
    compatible_versions: tuple[int, ...] | None = None,
    replace: bool = False,
) -> None:
    TYPE_REGISTRY.register(
        name,
        payload_type,
        validator=validator,
        description=description,
        version=version,
        compatible_versions=compatible_versions,
        replace=replace,
    )


def normalize_payload(name: str, payload: Any) -> Any:
    """Normalize legacy zero-copy payloads into typed SDK objects."""
    if name == "vision.frame" and not isinstance(payload, Frame):
        if np is not None and isinstance(payload, np.ndarray):
            return Frame.from_numpy(payload, readonly=True)
    if name == "vision.tensor" and not isinstance(payload, Tensor):
        if np is not None and isinstance(payload, np.ndarray):
            return Tensor.from_numpy(payload, readonly=True)
    return payload
