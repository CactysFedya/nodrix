# nodrix-ros2

Universal ROS 2 platform provider and orchestrator for Nodrix.

ROS 2 and `rclpy` remain system dependencies; they are intentionally not
installed from PyPI. Existing ROS 2 drivers and algorithms do not need a custom
Nodrix plugin. Use `ros2.node` or `ros2.launch` in the same `nodes + edges`
pipeline format used by every other Nodrix graph.

## 0.2 nodes

- `ros2.node` — supervise `ros2 run package executable`;
- `ros2.launch` — supervise any existing launch file;
- `ros2.rviz` — supervised RViz process;
- `ros2.topic_monitor` — readiness, rate and staleness monitoring without
  converting payloads;
- `ros2.topic_source` / `ros2.topic_sink` — generic bridge for small messages;
- `ros2.point_cloud2_source`, `ros2.imu_source`, `ros2.odometry_source` — typed
  bridges into `nodrix-spatial`.

`parameters.workspace` supports ROS underlays, an optional colcon overlay and
`build.mode: never|if-needed|always`. Nodrix captures sourced environment
variables for child processes, so a normal launch requires only:

```bash
nodrix run pipeline.yaml
```

Heavy ROS-to-ROS data remains in DDS/RMW and does not pass through Python.
