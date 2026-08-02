# nodrix-ros2

Universal ROS 2 platform provider and orchestrator for Nodrix. ROS 2 and
`rclpy` remain system dependencies and are intentionally not installed from
PyPI.

## 0.3 package boundary

The base package contains only reusable ROS platform services:

- `ros2.node`, `ros2.launch`, `ros2.rviz` process supervision;
- `ros2.topic_monitor` in `graph`, `sample`, or `statistics` mode;
- generic `ros2.topic_source` and `ros2.topic_sink` bridges;
- one pipeline-scoped `ros2.session` for workspace preparation, environment,
  graph observation, and child-process ownership;
- logical `ros2.topic` links for readiness and remapping.

PointCloud, IMU, and Odometry contracts live in the optional
`nodrix-spatial-ros2` package. This keeps a non-spatial ROS deployment small
and lets both packages evolve independently.

## Same YAML model

Ordinary Nodrix YAML remains valid. A ROS project only adds a session and binds
the ROS nodes that share it:

```yaml
name: ros-demo
runtime: {engine: unified, mode: realtime}

sessions:
  ros:
    uses: ros2.session
    parameters:
      distro: jazzy
      path: ${ROBOT_WS}
      build: {mode: if-needed, symlink_install: true}

nodes:
  driver:
    use: ros2.launch
    bindings: {session: ros}
    package: example_driver
    launch_file: driver.launch.py
```

Generate a complete editable project with:

```bash
nodrix init my-robot --template ros2
```

The workspace is prepared once, source changes are fingerprinted together with
the toolchain and underlays, and build logs are bounded and rotated. Large
ROS-to-ROS payloads remain in DDS/RMW. Use a typed bridge only when an algorithm
inside Nodrix actually needs that data.
