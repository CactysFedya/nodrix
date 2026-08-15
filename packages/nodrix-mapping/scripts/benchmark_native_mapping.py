from __future__ import annotations

import argparse
import statistics
import struct
import time
from pathlib import Path

from nodrix import ManagedBuffer, Message, NodeContext
from nodrix_spatial import PointCloudFrame, PointFieldSpec
from nodrix_mapping.nodes.voxel_map import VoxelMapNode


def make_cloud(points: int) -> Message:
    raw = bytearray(points * 12)
    for index in range(points):
        x = float(index % 240) * 0.05
        y = float((index // 240) % 240) * 0.05
        z = float(index % 37) * 0.01
        struct.pack_into("<fff", raw, index * 12, x, y, z)

    frame = PointCloudFrame(
        timestamp_ns=1,
        frame_id="map",
        width=points,
        height=1,
        fields=(
            PointFieldSpec("x", 0, 7),
            PointFieldSpec("y", 4, 7),
            PointFieldSpec("z", 8, 7),
        ),
        is_bigendian=False,
        point_step=12,
        row_step=points * 12,
        is_dense=True,
        buffer=ManagedBuffer.wrap(raw, readonly=True),
    )
    return Message(
        type="spatial.point_cloud/v1",
        payload=frame,
        timestamp_ns=1,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--points", type=int, default=20000)
    parser.add_argument("--frames", type=int, default=100)
    args = parser.parse_args()

    node = VoxelMapNode(
        {
            "voxel_size_m": 0.1,
            "max_voxels": 500000,
            "eviction_window": 64,
            "snapshot_interval_s": 3600.0,
        }
    )
    node.open(
        NodeContext(
            "mapping-native-benchmark",
            Path.cwd(),
            Path.cwd(),
            "realtime",
        )
    )

    source = make_cloud(args.points)
    latencies = []

    for sequence in range(args.frames):
        timestamp = sequence + 1
        source.payload.timestamp_ns = timestamp
        message = source.with_updates(
            sequence=sequence,
            timestamp_ns=timestamp,
        )
        started = time.perf_counter_ns()
        node.process({"cloud": message})
        latencies.append(
            (time.perf_counter_ns() - started) / 1_000_000.0
        )

    ordered = sorted(latencies)
    p95 = ordered[
        min(int(len(ordered) * 0.95), len(ordered) - 1)
    ]
    health = node.health()

    print("backend:", health["backend"])
    print("frames:", len(latencies))
    print("points/frame:", args.points)
    print("mean_ms:", round(statistics.mean(latencies), 3))
    print("p95_ms:", round(p95, 3))
    print("voxel_count:", health["voxel_count"])
    print(
        "native_state_mib:",
        round(
            health["native_state_bytes"] / (1024 * 1024),
            2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
