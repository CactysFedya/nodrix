# nodrix-spatial-ros2

Optional typed bridges at the ROS 2 ↔ Nodrix Spatial boundary. The package is
not required for ROS-to-ROS orchestration and keeps `nodrix-ros2` independent
from PointCloud, IMU, Odometry, and Transform domain contracts.

PointCloud payload bytes remain owned by the ROS message and are wrapped in a
read-only `ManagedBuffer` without adapter-level copying.

This is not an end-to-end DDS loaned-message zero-copy claim: `rclpy` may
deserialize into the Python message before the adapter receives it.
