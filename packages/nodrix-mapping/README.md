# plyctl-mapping

Transport-neutral metric mapping for Nodrix/Plyctl.

Version 0.3.0 keeps the alpha compatibility aliases
`mapping.point_cloud/v1` and `geometry.odometry/v1`, while canonical sensor
contracts remain owned by `plyctl-spatial`.

## Native C++20 data plane

`mapping.voxel_map` consumes `spatial.point_cloud/v1` and maintains a bounded
incremental metric voxel map.

The realtime hot path is implemented in a compiled C++20 extension:

- reads `PointCloudFrame` through the Python buffer protocol;
- does not create an intermediate `N x 3` NumPy point copy;
- avoids a Python loop per point/voxel;
- performs finite checks, voxel quantization and bounded flat-hash updates;
- incrementally maintains centroid, observation count, min-Z and max-Z;
- evicts voxels under `max_voxels`;
- releases the GIL while integrating the point cloud.

The node emits:

- `mapping.voxel_delta/v1` on every accepted frame;
- `mapping.voxel_snapshot/v1` periodically and during final drain.

`mapping.ply_store` writes snapshots as binary PLY using the same native
extension and performs atomic file replacement. The GIL is released while the
file is written.

## Development build

From the repository root:

```bash
python packages/nodrix-mapping/setup.py build_ext --inplace
```

For a portable developer build, LTO and host-specific ISA flags are disabled
by default.

## Raspberry Pi 5 production build

Build on the Raspberry Pi itself:

```bash
cd ~/nodrix
source .venv/bin/activate

NODRIX_MAPPING_NATIVE_ARCH_NATIVE=1 \
NODRIX_MAPPING_NATIVE_LTO=1 \
python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e ./packages/nodrix-mapping
```

`-march=native` is opt-in because such a binary is tied to the CPU it was
compiled for and must not be distributed as a generic wheel.

## Benchmark

```bash
python packages/nodrix-mapping/scripts/benchmark_native_mapping.py \
  --points 20000 \
  --frames 100
```

Measure the benchmark again on the actual Raspberry Pi 5 with the same
configuration used by the robot.
