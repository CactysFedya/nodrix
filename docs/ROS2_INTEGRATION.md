# ROS 2 integration

ROS 2 is an optional Provider API 2 package, not a Core dependency. Existing
ROS launch files, drivers, SLAM algorithms, and RViz configurations can be
supervised directly; an algorithm-specific Nodrix plugin is unnecessary.

## Shared session

Use one `ros2.session` per compatible ROS environment. It sources underlays,
builds an overlay once when needed, owns supervised processes, and starts one
persistent ROS graph worker only when graph information is requested.

```yaml
sessions:
  ros:
    uses: ros2.session
    parameters:
      distro: jazzy
      underlays: [/opt/ros/jazzy]
      path: ${ROBOT_WS}
      trust: explicit
      build:
        mode: if-needed
        symlink_install: true
        timeout_s: 1800

applications:
  driver:
    uses: ros2.launch
    bindings: {session: ros}
    parameters:
      package: example_driver
      launch_file: driver.launch.py
```

`if-needed` fingerprints source metadata and content policy together with the
underlay setup files, colcon command, compiler/toolchain identity, Python, and
selected environment. An inter-process lock prevents concurrent Nodrix runs
from building the same workspace at once. Every process has separate bounded,
rotated stdout and stderr logs and shuts down with
`SIGINT → SIGTERM → SIGKILL` fallback.

## External topic transports

`ros2.topic` is attached to a logical Edge. It expresses a ROS dependency
without creating a Nodrix data queue:

```yaml
edges:
  - from: driver.lidar
    to: slam.lidar
    transport:
      uses: ros2.topic
      parameters:
        topic: /lidar/points
        message_type: sensor_msgs/msg/PointCloud2
```

An incoming transported Edge delays the dependent application until a
publisher of the declared type appears. For `ros2.node`, logical ports can
also become ROS remappings. The execution plan marks the Edge as external with
zero planned Nodrix copies.

`ros2.node`, `ros2.launch`, and `ros2.rviz` are managed Applications in new
manifests. They are control-plane processes and no longer emit artificial
heartbeat messages into the data graph. The old Node declarations and
top-level `links` remain readable throughout Nodrix 2.x; `nodrix migrate`
rewrites `links` to `edges[].transport`.

## Monitoring modes

- `graph` checks type and publisher presence through the shared worker and does
  not subscribe to or deserialize payloads;
- `sample` creates a subscription and measures arrival rate/staleness;
- `statistics` is reserved for middleware statistics and currently reports
  availability explicitly while using graph state.

Use `graph` for large PointCloud2 readiness checks. Use `sample` only when the
rate measurement is worth the subscription and deserialization cost.

## Explicit bridges

`ros2.topic_source` and `ros2.topic_sink` handle generic small messages. Install
`nodrix-spatial-ros2` for typed PointCloud2, IMU, and Odometry sources:

```bash
python -m pip install nodrix-ros2
python -m pip install nodrix-spatial-ros2  # optional
```

The PointCloud2 adapter retains and wraps the Python ROS message buffer without
another adapter-level list conversion or byte copy. This does not claim
end-to-end DDS loaned-message zero-copy: `rclpy` may already have deserialized
the middleware sample.

Generate the maintained project shape with:

```bash
nodrix init my-robot --template ros2
```
