# Known limitations of nodrix-ros2 0.4.0

This alpha is suitable for repeatable orchestration and integration testing,
but it is not yet a complete high-performance ROS transport implementation.

- `ros2.node`, `ros2.launch`, and `ros2.rviz` are managed external
  Applications. ROS lifecycle-node transitions and composable-component
  containers are not implemented yet.
- The graph watcher is isolated in a ROS-system-Python worker. Generic topic
  source/sink bridges still use `rclpy` in the Nodrix process and therefore
  require a Python ABI compatible with the installed ROS distribution.
- ROS-to-ROS data described by an Edge with `ros2.topic` Transport remains in
  DDS. The Python bridges
  are bounded compatibility paths, not DDS loaned-message zero-copy. Large
  payloads should use `nodrix-spatial-ros2` or a future native bridge.
- Generic ROS services, actions, parameters, TF2, rosbag, lifecycle nodes, and
  component containers are future provider packages/nodes rather than hidden
  behavior in the current process nodes.
- The Jazzy CI smoke test covers a real publisher/subscriber graph. Livox,
  FAST-LIVO2, RViz rendering, hardware timing, and RMW-specific performance
  still require an Ubuntu 24.04 robot test host.
- Supported baseline: Python 3.11-3.13 for orchestration; ROS 2 Jazzy is tested
  with its system Python. CycloneDDS/Fast DDS performance and compatibility
  matrices are not yet release gates.
