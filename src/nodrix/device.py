from __future__ import annotations

import ctypes.util
import importlib.util
import platform
from typing import Any

from .memory import DmaBufHandle, DmaBufPlane, memory_summary

try:
    from ._native_device import device_doctor as _native_doctor, v4l2_probe as _native_v4l2_probe
except Exception:  # pragma: no cover - built during installation
    _native_doctor = None
    _native_v4l2_probe = None


def probe_v4l2(device: str = "/dev/video0") -> dict[str, Any]:
    if _native_v4l2_probe is None:
        raise RuntimeError("Plyctl native device extension is not built")
    return dict(_native_v4l2_probe(device=device))


def device_doctor() -> dict[str, Any]:
    native = dict(_native_doctor()) if _native_doctor is not None else {
        "platform": platform.system().lower(),
        "native_extension": False,
    }
    native["native_extension"] = _native_doctor is not None
    native["dlpack_numpy"] = importlib.util.find_spec("numpy") is not None
    native["dlpack_torch"] = importlib.util.find_spec("torch") is not None
    native["dlpack_cupy"] = importlib.util.find_spec("cupy") is not None
    native["cuda_runtime"] = ctypes.util.find_library("cudart") is not None
    native["opencl_runtime"] = ctypes.util.find_library("OpenCL") is not None
    native["vulkan_runtime"] = ctypes.util.find_library("vulkan") is not None
    native["libavcodec"] = ctypes.util.find_library("avcodec") is not None
    native["libavformat"] = bool(native.get("libavformat")) or ctypes.util.find_library("avformat") is not None
    native["dma_buf_descriptor"] = True
    native["cuda_ipc_descriptor"] = True
    return native


def dmabuf_from_fds(
    fds: list[int] | tuple[int, ...],
    *,
    lengths: list[int] | tuple[int, ...],
    offsets: list[int] | tuple[int, ...] | None = None,
    strides: list[int] | tuple[int, ...] | None = None,
    width: int = 0,
    height: int = 0,
    format: str = "unknown",
    duplicate: bool = True,
) -> DmaBufHandle:
    if len(fds) != len(lengths):
        raise ValueError("fds and lengths must have the same size")
    offsets = offsets or [0] * len(fds)
    strides = strides or [0] * len(fds)
    if not (len(offsets) == len(strides) == len(fds)):
        raise ValueError("DMA-BUF plane arrays must have equal lengths")
    import os

    planes = tuple(
        DmaBufPlane(
            fd=os.dup(int(fd)) if duplicate else int(fd),
            offset=int(offset),
            length=int(length),
            stride=int(stride),
        )
        for fd, offset, length, stride in zip(fds, offsets, lengths, strides)
    )
    return DmaBufHandle(
        planes=planes,
        width=int(width),
        height=int(height),
        format=format,
        owns_fds=duplicate,
    )


__all__ = [
    "DmaBufHandle",
    "DmaBufPlane",
    "device_doctor",
    "probe_v4l2",
    "dmabuf_from_fds",
    "memory_summary",
]
