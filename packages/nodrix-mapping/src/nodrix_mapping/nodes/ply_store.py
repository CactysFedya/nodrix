from __future__ import annotations

from pathlib import Path
from typing import Any

from nodrix import Message, SinkNode

from ..voxel_types import VoxelMapSnapshot


def _native_module():
    try:
        from .. import _mapping_native
    except ImportError as exc:
        raise RuntimeError(
            "mapping.ply_store requires the compiled C++20 backend"
        ) from exc
    return _mapping_native


class PlyStoreNode(SinkNode):
    input_types = {"map": "mapping.voxel_snapshot/v1"}

    def open(self, context: Any) -> None:
        super().open(context)
        value = Path(
            str(
                self.parameters.get(
                    "path",
                    "artifacts/maps/metric/latest.ply",
                )
            )
        )
        if not value.is_absolute():
            value = context.project_dir / value
        value.parent.mkdir(parents=True, exist_ok=True)

        self._path = value
        self._durable = bool(
            self.parameters.get("durable", True)
        )
        self._native = _native_module()
        self._saves = 0
        self._last_revision = -1
        self._last_vertices = 0
        self._last_bytes = 0

    def process(
        self,
        inputs: dict[str, Message],
    ) -> None:
        snapshot = inputs["map"].payload
        if not isinstance(snapshot, VoxelMapSnapshot):
            raise TypeError(
                "mapping.ply_store expects VoxelMapSnapshot"
            )
        if snapshot.revision < self._last_revision:
            raise ValueError(
                "mapping.ply_store received older map revision"
            )

        self._native.write_ply_atomic(
            path=str(self._path),
            centroids=snapshot.centroids_xyz,
            counts=snapshot.observation_counts,
            min_z=snapshot.min_z,
            max_z=snapshot.max_z,
            revision=int(snapshot.revision),
            voxel_size_m=float(snapshot.voxel_size_m),
            durable=self._durable,
        )

        self._saves += 1
        self._last_revision = snapshot.revision
        self._last_vertices = snapshot.voxel_count
        self._last_bytes = self._path.stat().st_size
        return None

    def health(self) -> dict[str, Any]:
        value = dict(super().health())
        value.update(
            {
                "backend": "cpp20-ply",
                "native": True,
                "path": str(getattr(self, "_path", "")),
                "saves": getattr(self, "_saves", 0),
                "last_revision": getattr(
                    self, "_last_revision", -1
                ),
                "vertices": getattr(
                    self, "_last_vertices", 0
                ),
                "bytes": getattr(self, "_last_bytes", 0),
                "atomic_write": True,
                "durable": getattr(self, "_durable", True),
            }
        )
        return value
