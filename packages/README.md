# Plyctl package workspace

This directory contains independently installable Plyctl distributions in one
monorepo.

```bash
python -m pip install -e packages/nodrix-spatial
python -m pip install -e packages/nodrix-mapping
python -m pip install -e packages/nodrix-ros2
python -m pip install -e packages/nodrix-spatial-ros2
```

The source directory names stay unchanged in alpha.5 so existing development
checkouts remain valid. Built distributions use the canonical `plyctl-*`
names shown below.

- `plyctl-spatial` owns transport-neutral point-cloud, IMU, odometry and TF
  payloads;
- `plyctl-mapping` owns map contracts and temporarily preserves alpha aliases;
- `plyctl-ros2` owns ROS workspace preparation, process orchestration,
  shared graph observation, readiness and generic transport bridges;
- `plyctl-spatial-ros2` owns the optional PointCloud2, IMU and Odometry bridge
  implementations.

ROS 2 itself is intentionally not installed through PyPI. `plyctl-ros2` can
source underlays and build an overlay automatically for child processes.
