from __future__ import annotations

from pathlib import Path
import struct

import pytest

from nodrix import ManagedBuffer, Message, NodeContext
from nodrix_spatial import PointCloudFrame, PointFieldSpec


pytest.importorskip(
    "nodrix_mapping._mapping_native",
    reason="native extension was not built for this test environment",
)

from nodrix_mapping.nodes.ply_store import PlyStoreNode
from nodrix_mapping.nodes.voxel_map import VoxelMapNode
from nodrix_mapping.voxel_types import VoxelMapDelta, VoxelMapSnapshot


def _cloud(points: list[tuple[float, float, float]], timestamp_ns: int = 1) -> Message:
    raw = bytearray(len(points) * 12)
    for index, (x, y, z) in enumerate(points):
        struct.pack_into("<fff", raw, index * 12, x, y, z)

    frame = PointCloudFrame(
        timestamp_ns=timestamp_ns,
        frame_id="map",
        width=len(points),
        height=1,
        fields=(
            PointFieldSpec("x", 0, 7),
            PointFieldSpec("y", 4, 7),
            PointFieldSpec("z", 8, 7),
        ),
        is_bigendian=False,
        point_step=12,
        row_step=len(points) * 12,
        is_dense=True,
        buffer=ManagedBuffer.wrap(raw, readonly=True),
    )
    return Message(
        type="spatial.point_cloud/v1",
        payload=frame,
        timestamp_ns=timestamp_ns,
    )


def test_native_voxel_map_integrates_and_snapshots(tmp_path: Path) -> None:
    node = VoxelMapNode(
        {
            "voxel_size_m": 0.1,
            "max_voxels": 1024,
            "eviction_window": 16,
            "snapshot_interval_s": 0.1,
        }
    )
    node.open(
        NodeContext(
            "mapping-test",
            tmp_path,
            tmp_path,
            "realtime",
        )
    )

    result = node.process(
        {
            "cloud": _cloud(
                [
                    (0.01, 0.01, 0.00),
                    (0.02, 0.02, 0.04),
                    (0.21, 0.01, 0.10),
                ]
            )
        }
    )

    assert isinstance(result["delta"].payload, VoxelMapDelta)
    assert result["delta"].payload.total_voxels == 2
    assert isinstance(result["snapshot"].payload, VoxelMapSnapshot)
    assert result["snapshot"].payload.voxel_count == 2

    health = node.health()
    assert health["native"] is True
    assert health["voxel_count"] == 2


def test_native_ply_store_writes_atomic_binary_ply(tmp_path: Path) -> None:
    mapper = VoxelMapNode(
        {
            "voxel_size_m": 0.1,
            "max_voxels": 1024,
            "snapshot_interval_s": 0.1,
        }
    )
    mapper.open(
        NodeContext(
            "mapping-test",
            tmp_path,
            tmp_path,
            "realtime",
        )
    )
    snapshot_message = mapper.process(
        {"cloud": _cloud([(0.0, 0.0, 0.0), (0.2, 0.1, 0.3)])}
    )["snapshot"]

    store = PlyStoreNode(
        {
            "path": "artifacts/map.ply",
            "durable": False,
        }
    )
    store.open(
        NodeContext(
            "store-test",
            tmp_path,
            tmp_path,
            "realtime",
        )
    )
    store.process({"map": snapshot_message})

    output = tmp_path / "artifacts/map.ply"
    assert output.is_file()
    assert output.read_bytes().startswith(b"ply\n")
    health = store.health()
    assert health["native"] is True
    assert health["saves"] == 1
    assert health["vertices"] == 2
