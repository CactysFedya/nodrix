from __future__ import annotations

import time
from typing import Any

import numpy as np

from nodrix import Message, Node
from nodrix_spatial import PointCloudFrame

from ..voxel_types import VoxelMapDelta, VoxelMapSnapshot


def _native_module():
    try:
        from .. import _mapping_native
    except ImportError as exc:
        raise RuntimeError(
            "mapping.voxel_map requires the compiled C++20 backend"
        ) from exc
    return _mapping_native


def _xyz_fields(frame: PointCloudFrame):
    fields = {field.name: field for field in frame.fields}
    missing = {"x", "y", "z"} - set(fields)
    if missing:
        raise ValueError(
            "Point cloud has no fields: " + ", ".join(sorted(missing))
        )
    result = []
    for name in ("x", "y", "z"):
        field = fields[name]
        if int(field.count) != 1:
            raise ValueError(f"PointField {name} must have count=1")
        result.append((int(field.offset), int(field.datatype)))
    return result


def _array(
    value: bytes,
    *,
    dtype: np.dtype[Any] | str,
    shape: tuple[int, ...],
) -> np.ndarray:
    array = np.frombuffer(value, dtype=dtype)
    if array.size != int(np.prod(shape)):
        raise RuntimeError(
            f"Native mapping array size mismatch: {array.size} != {shape}"
        )
    return array.reshape(shape)


class VoxelMapNode(Node):
    input_types = {"cloud": "spatial.point_cloud/v1"}
    output_types = {
        "delta": "mapping.voxel_delta/v1",
        "snapshot": "mapping.voxel_snapshot/v1",
    }

    def open(self, context: Any) -> None:
        super().open(context)
        self._voxel_size_m = float(
            self.parameters.get("voxel_size_m", 0.10)
        )
        if (
            not np.isfinite(self._voxel_size_m)
            or self._voxel_size_m <= 0
        ):
            raise ValueError("voxel_size_m must be positive and finite")

        self._point_stride = max(
            int(self.parameters.get("point_stride", 1)), 1
        )
        self._max_voxels = max(
            int(self.parameters.get("max_voxels", 500_000)), 1
        )
        self._eviction_window = min(
            max(int(self.parameters.get("eviction_window", 64)), 1),
            self._max_voxels,
        )
        self._snapshot_interval_s = max(
            float(self.parameters.get("snapshot_interval_s", 5.0)),
            0.1,
        )

        self._native = _native_module()
        self._core = self._native.create(
            max_voxels=self._max_voxels,
            eviction_window=self._eviction_window,
        )
        self._frames = 0
        self._last_timestamp_ns = 0
        self._last_frame_id = ""
        self._map_frame_id: str | None = None
        self._last_snapshot_monotonic = float("-inf")
        self._last_snapshot_revision = -1

    def _snapshot(self) -> VoxelMapSnapshot:
        raw = self._native.snapshot(self._core)
        count = int(raw["count"])
        return VoxelMapSnapshot(
            timestamp_ns=self._last_timestamp_ns,
            frame_id=self._last_frame_id,
            revision=int(raw["revision"]),
            voxel_size_m=self._voxel_size_m,
            indices=_array(
                raw["indices"], dtype=np.int32, shape=(count, 3)
            ),
            centroids_xyz=_array(
                raw["centroids"], dtype=np.float32, shape=(count, 3)
            ),
            observation_counts=_array(
                raw["counts"], dtype=np.uint32, shape=(count,)
            ),
            min_z=_array(
                raw["min_z"], dtype=np.float32, shape=(count,)
            ),
            max_z=_array(
                raw["max_z"], dtype=np.float32, shape=(count,)
            ),
            metadata={
                "backend": "cpp20-flat-hash",
                "voxel_count": count,
                "max_voxels": self._max_voxels,
                "eviction_policy": "bounded-lru-window",
                "eviction_window": self._eviction_window,
            },
        )

    def process(
        self,
        inputs: dict[str, Message],
    ) -> dict[str, Message]:
        message = inputs["cloud"]
        frame = message.payload

        if not isinstance(frame, PointCloudFrame):
            raise TypeError(
                "mapping.voxel_map expects PointCloudFrame"
            )

        if self._map_frame_id is None:
            self._map_frame_id = frame.frame_id
        elif frame.frame_id != self._map_frame_id:
            raise ValueError(
                "mapping.voxel_map requires one stable world frame: "
                f"{frame.frame_id!r} != {self._map_frame_id!r}"
            )

        timestamp_ns = int(
            message.timestamp_ns or frame.timestamp_ns
        )
        if (
            self._last_timestamp_ns
            and timestamp_ns < self._last_timestamp_ns
        ):
            raise ValueError(
                "mapping.voxel_map received out-of-order timestamp"
            )

        (
            (x_offset, x_type),
            (y_offset, y_type),
            (z_offset, z_type),
        ) = _xyz_fields(frame)

        raw = self._native.integrate(
            core=self._core,
            buffer=frame.buffer.memoryview(),
            width=int(frame.width),
            height=int(frame.height),
            row_step=int(frame.row_step),
            point_step=int(frame.point_step),
            is_bigendian=bool(frame.is_bigendian),
            x_offset=x_offset,
            x_datatype=x_type,
            y_offset=y_offset,
            y_datatype=y_type,
            z_offset=z_offset,
            z_datatype=z_type,
            point_stride=self._point_stride,
            voxel_size_m=self._voxel_size_m,
            timestamp_ns=timestamp_ns,
        )

        changed = int(raw["count"])
        removed_count = (
            len(raw["removed_indices"])
            // (3 * np.dtype(np.int32).itemsize)
        )
        self._frames += 1
        self._last_timestamp_ns = timestamp_ns
        self._last_frame_id = frame.frame_id

        delta = VoxelMapDelta(
            timestamp_ns=timestamp_ns,
            frame_id=frame.frame_id,
            revision=int(raw["revision"]),
            voxel_size_m=self._voxel_size_m,
            indices=_array(
                raw["indices"], dtype=np.int32, shape=(changed, 3)
            ),
            centroids_xyz=_array(
                raw["centroids"], dtype=np.float32, shape=(changed, 3)
            ),
            observation_counts=_array(
                raw["counts"], dtype=np.uint32, shape=(changed,)
            ),
            min_z=_array(
                raw["min_z"], dtype=np.float32, shape=(changed,)
            ),
            max_z=_array(
                raw["max_z"], dtype=np.float32, shape=(changed,)
            ),
            removed_indices=_array(
                raw["removed_indices"],
                dtype=np.int32,
                shape=(removed_count, 3),
            ),
            total_voxels=int(raw["total_voxels"]),
            metadata={
                "backend": "cpp20-flat-hash",
                "input_points": int(raw["input_points"]),
                "accepted_points": int(raw["accepted_points"]),
                "unique_input_voxels": int(
                    raw["unique_input_voxels"]
                ),
                "invalid_points": int(raw["invalid_points"]),
                "coordinate_overflow_points": int(
                    raw["coordinate_overflow_points"]
                ),
                "evicted_voxels_total": int(
                    raw["evicted_voxels_total"]
                ),
            },
        )

        outputs = {
            "delta": message.with_updates(
                type="mapping.voxel_delta/v1",
                payload=delta,
            )
        }

        now = time.monotonic()
        if (
            now - self._last_snapshot_monotonic
            >= self._snapshot_interval_s
        ):
            snapshot = self._snapshot()
            self._last_snapshot_monotonic = now
            self._last_snapshot_revision = snapshot.revision
            outputs["snapshot"] = message.with_updates(
                type="mapping.voxel_snapshot/v1",
                payload=snapshot,
            )

        return outputs

    def drain(self) -> dict[str, Message] | None:
        if self._frames <= 0:
            return None
        stats = self._native.stats(self._core)
        if int(stats["revision"]) == self._last_snapshot_revision:
            return None

        snapshot = self._snapshot()
        self._last_snapshot_revision = snapshot.revision
        return {
            "snapshot": Message(
                type="mapping.voxel_snapshot/v1",
                payload=snapshot,
                sequence=snapshot.revision,
                timestamp_ns=self._last_timestamp_ns,
                metadata={
                    "final_snapshot": True,
                    "frame_id": self._last_frame_id,
                },
            )
        }

    def health(self) -> dict[str, Any]:
        value = dict(super().health())
        core = getattr(self, "_core", None)
        if core is None:
            value.update(
                {
                    "backend": "cpp20-flat-hash",
                    "native": True,
                    "voxel_count": 0,
                }
            )
            return value
        stats = self._native.stats(core)
        value.update(
            {
                "backend": "cpp20-flat-hash",
                "native": True,
                **{key: int(item) for key, item in stats.items()},
            }
        )
        return value
