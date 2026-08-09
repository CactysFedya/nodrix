from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


def _array(
    value: Any,
    *,
    dtype: np.dtype[Any] | str,
) -> np.ndarray:
    expected = np.dtype(dtype)
    if (
        isinstance(value, np.ndarray)
        and value.dtype == expected
        and value.flags.c_contiguous
        and not value.flags.writeable
    ):
        return value

    result = np.array(
        value,
        dtype=expected,
        order="C",
        copy=True,
    )
    result.setflags(write=False)
    return result


@dataclass(slots=True)
class VoxelMapDelta:
    timestamp_ns: int
    frame_id: str
    revision: int
    voxel_size_m: float
    indices: Any
    centroids_xyz: Any
    observation_counts: Any
    min_z: Any
    max_z: Any
    removed_indices: Any
    total_voxels: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns cannot be negative")
        if self.revision < 0:
            raise ValueError("revision cannot be negative")
        if self.voxel_size_m <= 0:
            raise ValueError("voxel_size_m must be positive")
        if self.total_voxels < 0:
            raise ValueError("total_voxels cannot be negative")

        self.indices = _array(self.indices, dtype=np.int32)
        self.centroids_xyz = _array(
            self.centroids_xyz, dtype=np.float32
        )
        self.observation_counts = _array(
            self.observation_counts, dtype=np.uint32
        )
        self.min_z = _array(self.min_z, dtype=np.float32)
        self.max_z = _array(self.max_z, dtype=np.float32)
        self.removed_indices = _array(
            self.removed_indices, dtype=np.int32
        )

        if (
            self.indices.ndim != 2
            or self.indices.shape[1] != 3
        ):
            raise ValueError("indices must have shape [N, 3]")

        count = self.indices.shape[0]
        if self.centroids_xyz.shape != (count, 3):
            raise ValueError(
                "centroids_xyz must have shape [N, 3]"
            )
        if self.observation_counts.shape != (count,):
            raise ValueError(
                "observation_counts must have shape [N]"
            )
        if self.min_z.shape != (count,):
            raise ValueError("min_z must have shape [N]")
        if self.max_z.shape != (count,):
            raise ValueError("max_z must have shape [N]")
        if (
            self.removed_indices.ndim != 2
            or self.removed_indices.shape[1] != 3
        ):
            raise ValueError(
                "removed_indices must have shape [M, 3]"
            )


@dataclass(slots=True)
class VoxelMapSnapshot:
    timestamp_ns: int
    frame_id: str
    revision: int
    voxel_size_m: float
    indices: Any
    centroids_xyz: Any
    observation_counts: Any
    min_z: Any
    max_z: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns cannot be negative")
        if self.revision < 0:
            raise ValueError("revision cannot be negative")
        if self.voxel_size_m <= 0:
            raise ValueError("voxel_size_m must be positive")

        self.indices = _array(self.indices, dtype=np.int32)
        self.centroids_xyz = _array(
            self.centroids_xyz, dtype=np.float32
        )
        self.observation_counts = _array(
            self.observation_counts, dtype=np.uint32
        )
        self.min_z = _array(self.min_z, dtype=np.float32)
        self.max_z = _array(self.max_z, dtype=np.float32)

        if (
            self.indices.ndim != 2
            or self.indices.shape[1] != 3
        ):
            raise ValueError("indices must have shape [N, 3]")

        count = self.indices.shape[0]
        if self.centroids_xyz.shape != (count, 3):
            raise ValueError(
                "centroids_xyz must have shape [N, 3]"
            )
        if self.observation_counts.shape != (count,):
            raise ValueError(
                "observation_counts must have shape [N]"
            )
        if self.min_z.shape != (count,):
            raise ValueError("min_z must have shape [N]")
        if self.max_z.shape != (count,):
            raise ValueError("max_z must have shape [N]")

    @property
    def voxel_count(self) -> int:
        return int(self.indices.shape[0])
