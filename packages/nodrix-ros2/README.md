# plyctl-ros2

Universal ROS 2 platform provider and orchestrator for Plyctl. ROS 2 and
`rclpy` remain system dependencies and are intentionally not installed from
PyPI.

This is an alpha provider. The repository's `KNOWN_LIMITATIONS.md` records the
exact production and hardware boundaries; the most important data-path limit
is also stated below.

## 0.4 package boundary

The base package contains only reusable ROS platform services:

- `ros2.node`, `ros2.launch`, `ros2.rviz` managed Applications;
- `ros2.topic_monitor` in `graph`, `sample`, or `statistics` mode;
- generic `ros2.topic_source` and `ros2.topic_sink` bridges;
- one pipeline-scoped `ros2.session` for workspace preparation, environment,
  graph observation, and child-process ownership;
- `ros2.topic` transports attached to logical Edges for readiness and
  remapping.

PointCloud, IMU, and Odometry contracts live in the optional
`plyctl-spatial-ros2` package. This keeps a non-spatial ROS deployment small
and lets both packages evolve independently.

## Same YAML model

Ordinary Plyctl YAML remains valid. A ROS project only adds a session and binds
the managed Applications that share it:

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

applications:
  driver:
    uses: ros2.launch
    bindings: {session: ros}
    parameters:
      package: example_driver
      launch_file: driver.launch.py

  localization:
    uses: ros2.launch
    bindings: {session: ros}
    parameters:
      package: example_localization
      launch_file: localization.launch.py
      # Optional mapping from logical ports to launch arguments.
      ros_port_arguments: {scan: input_scan_topic}

nodes: {}

edges:
  - from: driver.scan
    to: localization.scan
    transport:
      uses: ros2.topic
      parameters:
        topic: /scan
        message_type: sensor_msgs/msg/LaserScan
```

Generate a complete editable project with:

```bash
plyctl init my-robot --template ros2
```

The workspace is prepared once, source changes are fingerprinted together with
the toolchain and underlays, and build logs are bounded and rotated. Large
ROS-to-ROS payloads remain in DDS/RMW: a `ros2.topic` transport is a typed topology,
readiness, and remapping contract, not a Python payload copy. For `ros2.node`
and RViz the port is compiled to a ROS remap. A launch process can expose the
same behavior with `ros_port_arguments`. Use a typed source/sink bridge only
when an algorithm inside Plyctl actually needs the data; that compatibility
path is bounded but is not DDS loaned-message zero-copy.

By default the session passes a ROS-focused allowlist of environment variables
to builds and child processes. Add project-specific names with
`pass_environment`, or deliberately opt into the complete parent environment
with `inherit_environment: true`.
