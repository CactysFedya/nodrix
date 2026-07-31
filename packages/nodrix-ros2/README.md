# nodrix-ros2

Independent ROS 2 integration for Nodrix Provider API 1.

ROS 2 and `rclpy` are system dependencies and are intentionally not installed
from PyPI.

## Development installation

```bash
source /opt/ros/${ROS_DISTRO:-jazzy}/setup.bash
python -m pip install -e packages/nodrix-mapping
python -m pip install -e packages/nodrix-ros2
```

## Nodes

- `ros2.topic_source` — generic source for small messages;
- `ros2.topic_sink` — generic publisher;
- `ros2.point_cloud2_source` — typed, buffer-backed PointCloud2 source;
- `ros2.odometry_source` — typed Odometry source.

All ROS nodes use one shared context and one shared multithreaded executor.
