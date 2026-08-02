# FAST-LIVO2 → Plyctl integration

FAST-LIVO2 remains an external ROS 2 process. No algorithm-specific Python
plugin is required.

Two pipeline modes are included:

- `pipelines/input.yaml` — consume an already running FAST-LIVO2 graph;
- `pipelines/orchestrated-ros2.yaml` — let `plyctl-ros2` prepare the workspace,
  start Livox, wait for input topics, start FAST-LIVO2, monitor output and start
  RViz.

## Expected topics

```text
/livox/lidar      livox_ros_driver2/msg/CustomMsg
/livox/imu        sensor_msgs/msg/Imu
/cloud_registered sensor_msgs/msg/PointCloud2
/odometry         nav_msgs/msg/Odometry
```

The exact FAST-LIVO2 ROS 2 port, package name, launch file and topic names must
be pinned by the deployment because upstream variants differ.

## Development install

```bash
python -m pip install -e packages/nodrix-spatial --no-deps
python -m pip install -e packages/nodrix-mapping --no-deps
python -m pip install -e packages/nodrix-ros2 --no-deps
python -m pip install -e packages/nodrix-spatial-ros2 --no-deps  # only for typed bridges
```

## Run

```bash
export LIVOX_WS=$HOME/livox_ws
export ROBOT_WS=$HOME/robot_ws
plyctl validate integrations/nodrix-fast-livo2/pipelines/orchestrated-ros2.yaml
plyctl run integrations/nodrix-fast-livo2/pipelines/orchestrated-ros2.yaml
```

`plyctl-ros2` prepares one shared session for the complete graph, then performs
`colcon build --symlink-install` only when the source, underlay, toolchain or
build command identity has changed. The default health nodes use graph mode,
so PointCloud2 payloads are not deserialized merely to check readiness.
