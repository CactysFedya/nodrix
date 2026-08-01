# FAST-LIVO2 → Nodrix integration

FAST-LIVO2 remains an external ROS 2 process. No algorithm-specific Python
plugin is required.

Two pipeline modes are included:

- `pipelines/input.yaml` — consume an already running FAST-LIVO2 graph;
- `pipelines/orchestrated-ros2.yaml` — let `nodrix-ros2` prepare the workspace,
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
```

## Run

```bash
export LIVOX_WS=$HOME/livox_ws
export ROBOT_WS=$HOME/robot_ws
nodrix validate integrations/nodrix-fast-livo2/pipelines/orchestrated-ros2.yaml
nodrix run integrations/nodrix-fast-livo2/pipelines/orchestrated-ros2.yaml
```

`nodrix-ros2` captures ROS setup environments for child processes and performs
`colcon build --symlink-install` only when the overlay source fingerprint has
changed.
