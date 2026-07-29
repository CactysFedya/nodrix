# ROS 2 integration

ROS 2 is an adapter, not a Core dependency. `ros2.source` subscribes to a topic
and `ros2.sink` publishes Nodrix messages:

```yaml
nodes:
  camera:
    uses: ros2.source
    parameters:
      topic: /camera/image
      message_type: sensor_msgs.msg.Image
      reliability: best_effort
      durability: volatile
      depth: 1
      map_timestamp: true
```

`message_type` may be `Image`, `CompressedImage`, `PointCloud2`,
`Detection2DArray`, or another installed ROS message class. Nodrix imports
`rclpy` only when the adapter opens, so non-ROS deployments do not install or
initialize ROS.

For custom conversions, set `mapper` to `module.Symbol`. Source mappers receive
the ROS message; sink mappers receive a Nodrix `Message`. Without a mapper,
standard ROS fields are converted recursively and header timestamps are mapped
from `timestamp_ns`.

QoS parameters map reliability, durability, and queue depth explicitly. The ROS
environment and generated message packages remain the operator's responsibility.
