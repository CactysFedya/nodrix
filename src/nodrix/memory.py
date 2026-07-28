from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
import os
from typing import Any, Iterable, Mapping, Sequence


class DLPackDeviceType(IntEnum):
    """Subset of the DLPack DLDeviceType ABI used by Nodrix."""

    CPU = 1
    CUDA = 2
    CUDA_HOST = 3
    OPENCL = 4
    VULKAN = 7
    METAL = 8
    ROCM = 10
    ROCM_HOST = 11
    CUDA_MANAGED = 13
    ONE_API = 14


class MemoryAccess(StrEnum):
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


@dataclass(frozen=True, slots=True)
class DmaBufPlane:
    fd: int
    offset: int
    length: int
    stride: int = 0
    bytes_used: int = 0

    def __post_init__(self) -> None:
        if self.fd < 0:
            raise ValueError("DMA-BUF fd must be non-negative")
        if self.offset < 0 or self.length <= 0:
            raise ValueError("DMA-BUF offset/length are invalid")
        if self.stride < 0 or self.bytes_used < 0:
            raise ValueError("DMA-BUF stride/bytes_used cannot be negative")


@dataclass(slots=True)
class DmaBufHandle:
    """Linux DMA-BUF descriptor.

    Nodrix owns duplicated file descriptors when ``owns_fds`` is true. The
    descriptor can be imported by a V4L2, DRM, VAAPI, Vulkan, CUDA or vendor
    backend without first materialising a CPU array.
    """

    planes: tuple[DmaBufPlane, ...]
    width: int = 0
    height: int = 0
    format: str = "unknown"
    modifier: int = 0
    device: str = "linux-dmabuf"
    owns_fds: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    _closed: bool = field(default=False, init=False, repr=False)

    def duplicate(self) -> "DmaBufHandle":
        duplicated = tuple(
            DmaBufPlane(
                fd=os.dup(plane.fd),
                offset=plane.offset,
                length=plane.length,
                stride=plane.stride,
                bytes_used=plane.bytes_used,
            )
            for plane in self.planes
        )
        return DmaBufHandle(
            planes=duplicated,
            width=self.width,
            height=self.height,
            format=self.format,
            modifier=self.modifier,
            device=self.device,
            owns_fds=True,
            metadata=dict(self.metadata),
        )

    @property
    def nbytes(self) -> int:
        return sum(plane.length for plane in self.planes)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.owns_fds:
            for plane in self.planes:
                try:
                    os.close(plane.fd)
                except OSError:
                    pass

    def __del__(self) -> None:  # pragma: no cover - GC timing is implementation-specific
        self.close()


@dataclass(frozen=True, slots=True)
class CudaIpcHandle:
    handle: bytes
    device_index: int
    size: int
    offset: int = 0
    event_handle: bytes | None = None

    def __post_init__(self) -> None:
        if not self.handle:
            raise ValueError("CUDA IPC handle cannot be empty")
        if self.device_index < 0 or self.size <= 0 or self.offset < 0:
            raise ValueError("Invalid CUDA IPC descriptor")


@dataclass(frozen=True, slots=True)
class ExternalMemoryHandle:
    backend: str
    handle: Any
    size: int
    device: str = "external"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryRequirement:
    """Memory contract declared by a node port."""

    allowed: tuple[str, ...] = ("any",)
    preferred: str | None = None
    access: MemoryAccess = MemoryAccess.READ
    contiguous: bool = True

    @classmethod
    def from_value(cls, value: Any) -> "MemoryRequirement":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls((value,), preferred=None if value == "any" else value)
        if isinstance(value, (tuple, list, set)):
            allowed = tuple(str(item) for item in value) or ("any",)
            return cls(allowed=allowed, preferred=None if "any" in allowed else allowed[0])
        if isinstance(value, Mapping):
            raw_allowed = value.get("allowed", ("any",))
            if isinstance(raw_allowed, str):
                raw_allowed = (raw_allowed,)
            allowed = tuple(str(item) for item in raw_allowed) or ("any",)
            return cls(
                allowed=allowed,
                preferred=value.get("preferred"),
                access=MemoryAccess(value.get("access", "read")),
                contiguous=bool(value.get("contiguous", True)),
            )
        raise TypeError(f"Unsupported Nodrix memory requirement: {value!r}")

    def accepts(self, memory_type: str) -> bool:
        return "any" in self.allowed or memory_type in self.allowed


@dataclass(frozen=True, slots=True)
class MemoryPlan:
    source: str
    target: str
    selected: str
    copies: int
    transfers: tuple[str, ...] = ()
    adapter: str | None = None
    reason: str = ""
    runtime_supported: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_memory": self.source,
            "target_memory": self.target,
            "selected_memory": self.selected,
            "planned_copies": self.copies,
            "transfers": list(self.transfers),
            "adapter": self.adapter,
            "reason": self.reason,
            "runtime_supported": self.runtime_supported,
        }


_HOST_MEMORY = {"cpu", "pinned_cpu", "shared"}
_DEVICE_MEMORY = {"cuda", "rocm", "vulkan", "opencl", "metal", "npu", "dma_buf", "external"}


def normalize_requirement(value: Any) -> MemoryRequirement:
    return MemoryRequirement.from_value(value)


def _ordered_allowed(requirement: MemoryRequirement) -> tuple[str, ...]:
    values = tuple(item for item in requirement.allowed if item != "any")
    if requirement.preferred and requirement.preferred in values:
        return (requirement.preferred,) + tuple(item for item in values if item != requirement.preferred)
    return values


def plan_memory(
    source: MemoryRequirement,
    target: MemoryRequirement,
    *,
    forced: str = "auto",
    allow_copy: bool = True,
) -> MemoryPlan:
    """Create a deterministic static memory plan for one graph edge.

    The planner never hides a transfer. If no common domain exists it reports
    the adapter/copy that must be inserted. Device-specific adapters are marked
    unsupported until a backend registers one at runtime.
    """

    source_values = _ordered_allowed(source)
    target_values = _ordered_allowed(target)
    source_any = "any" in source.allowed
    target_any = "any" in target.allowed

    if forced != "auto":
        if not source_any and forced not in source.allowed:
            return MemoryPlan(
                source_values[0] if source_values else "unknown", forced, forced, 1,
                (f"{source_values[0] if source_values else 'unknown'}->{forced}",),
                f"copy_to_{forced}", "edge forces a memory domain not produced by source", allow_copy,
            )
        if not target_any and forced not in target.allowed:
            return MemoryPlan(forced, target_values[0] if target_values else "unknown", forced, 1,
                              (f"{forced}->{target_values[0] if target_values else 'unknown'}",),
                              f"copy_to_{target_values[0] if target_values else 'target'}",
                              "edge forces a memory domain not accepted by target", False)
        return MemoryPlan(forced, forced, forced, 0, reason="explicit edge memory domain")

    if source_any and target_any:
        return MemoryPlan("dynamic", "dynamic", "dynamic", 0, reason="both ports accept dynamic memory")
    if source_any:
        selected = target.preferred or (target_values[0] if target_values else "dynamic")
        return MemoryPlan(selected, selected, selected, 0, reason="source preserves downstream-selected memory")
    if target_any:
        selected = source.preferred or (source_values[0] if source_values else "dynamic")
        return MemoryPlan(selected, selected, selected, 0, reason="target accepts producer memory")

    common = [item for item in source_values if item in target.allowed]
    if common:
        selected = target.preferred if target.preferred in common else source.preferred if source.preferred in common else common[0]
        return MemoryPlan(selected, selected, selected, 0, reason="producer and consumer share a memory domain")

    src = source.preferred or source_values[0]
    dst = target.preferred or target_values[0]
    if not allow_copy:
        return MemoryPlan(src, dst, dst, 1, (f"{src}->{dst}",), f"copy_{src}_to_{dst}",
                          "no common memory domain and copies are forbidden", False)

    if src in _HOST_MEMORY and dst in _HOST_MEMORY:
        return MemoryPlan(src, dst, dst, 1, (f"{src}->{dst}",), f"host_copy_to_{dst}",
                          "host memory domains require one explicit copy")
    if src in _HOST_MEMORY and dst in _DEVICE_MEMORY:
        return MemoryPlan(src, dst, dst, 1, (f"host_to_{dst}",), f"upload_{dst}",
                          "host-to-device transfer requires an explicit backend adapter", False)
    if src in _DEVICE_MEMORY and dst in _HOST_MEMORY:
        return MemoryPlan(src, dst, dst, 1, (f"{src}_to_host",), f"download_{src}",
                          "device-to-host transfer requires an explicit backend adapter", False)
    return MemoryPlan(src, dst, dst, 1, (f"{src}->{dst}",), f"convert_{src}_to_{dst}",
                      "device-domain interoperability adapter required", False)


def requirement_for_port(mapping: Mapping[str, Any] | None, port: str) -> MemoryRequirement:
    if not mapping or port not in mapping:
        return MemoryRequirement()
    return normalize_requirement(mapping[port])


def dlpack_memory_type(device: tuple[int, int]) -> tuple[str, str]:
    kind, index = int(device[0]), int(device[1])
    if kind == DLPackDeviceType.CPU:
        return "cpu", "cpu"
    if kind == DLPackDeviceType.CUDA_HOST:
        return "pinned_cpu", f"cuda_host:{index}"
    if kind in (DLPackDeviceType.CUDA, DLPackDeviceType.CUDA_MANAGED):
        return "cuda", f"cuda:{index}"
    if kind in (DLPackDeviceType.ROCM, DLPackDeviceType.ROCM_HOST):
        return ("rocm" if kind == DLPackDeviceType.ROCM else "pinned_cpu"), f"rocm:{index}"
    if kind == DLPackDeviceType.VULKAN:
        return "vulkan", f"vulkan:{index}"
    if kind == DLPackDeviceType.OPENCL:
        return "opencl", f"opencl:{index}"
    if kind == DLPackDeviceType.METAL:
        return "metal", f"metal:{index}"
    if kind == DLPackDeviceType.ONE_API:
        return "npu", f"oneapi:{index}"
    return "external", f"dlpack:{kind}:{index}"


def object_dlpack_device(value: Any) -> tuple[int, int] | None:
    method = getattr(value, "__dlpack_device__", None)
    if method is None:
        return None
    device = method()
    if not isinstance(device, Sequence) or len(device) != 2:
        raise TypeError("__dlpack_device__ must return (device_type, device_id)")
    return int(device[0]), int(device[1])


def infer_shape_dtype(value: Any) -> tuple[tuple[int, ...] | None, str | None]:
    shape = getattr(value, "shape", None)
    dtype = getattr(value, "dtype", None)
    normalized_shape = tuple(int(item) for item in shape) if shape is not None else None
    return normalized_shape, None if dtype is None else str(dtype)


def memory_summary(buffer: Any) -> dict[str, Any]:
    memory_type = str(getattr(buffer, "memory_type", "unknown"))
    if hasattr(getattr(buffer, "memory_type", None), "value"):
        memory_type = buffer.memory_type.value
    return {
        "memory_type": memory_type,
        "device": str(getattr(buffer, "device", "unknown")),
        "nbytes": int(getattr(buffer, "nbytes", 0)),
        "readonly": bool(getattr(buffer, "readonly", True)),
        "host_accessible": bool(getattr(buffer, "host_accessible", False)),
        "dlpack": callable(getattr(buffer, "__dlpack__", None)),
        "handle_type": type(getattr(buffer, "handle", None)).__name__ if getattr(buffer, "handle", None) is not None else None,
    }
