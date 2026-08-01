# Nodrix package workspace

This directory contains independently installable Nodrix distributions in one
monorepo.

```bash
python -m pip install -e packages/nodrix-spatial
python -m pip install -e packages/nodrix-mapping
python -m pip install -e packages/nodrix-ros2
```

- `nodrix-spatial` owns transport-neutral point-cloud, IMU, odometry and TF
  payloads;
- `nodrix-mapping` owns map contracts and temporarily preserves alpha aliases;
- `nodrix-ros2` owns ROS workspace preparation, process orchestration,
  readiness and generic transport bridges.

ROS 2 itself is intentionally not installed through PyPI. `nodrix-ros2` can
source underlays and build an overlay automatically for child processes.
