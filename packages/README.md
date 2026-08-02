# Nodrix package workspace

This directory contains independently installable Nodrix distributions in one
monorepo.

```bash
python -m pip install -e packages/nodrix-spatial
python -m pip install -e packages/nodrix-mapping
python -m pip install -e packages/nodrix-ros2
python -m pip install -e packages/nodrix-spatial-ros2
```

- `nodrix-spatial` owns transport-neutral point-cloud, IMU, odometry and TF
  payloads;
- `nodrix-mapping` owns map contracts and temporarily preserves alpha aliases;
- `nodrix-ros2` owns ROS workspace preparation, process orchestration,
  shared graph observation, readiness and generic transport bridges;
- `nodrix-spatial-ros2` owns the optional PointCloud2, IMU and Odometry bridge
  implementations.

ROS 2 itself is intentionally not installed through PyPI. `nodrix-ros2` can
source underlays and build an overlay automatically for child processes.
