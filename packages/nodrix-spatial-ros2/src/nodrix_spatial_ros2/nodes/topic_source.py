from nodrix_ros2.nodes import Ros2TopicSourceBase

from ..adapters import imu_to_frame, odometry_to_frame, point_cloud2_to_frame


class Ros2PointCloud2Source(Ros2TopicSourceBase):
    """Typed PointCloud2 source preserving the ROS data buffer by reference."""

    output_types = {"cloud": "spatial.point_cloud/v1"}
    output_port = "cloud"
    nodrix_type = "spatial.point_cloud/v1"
    default_message_type = "sensor_msgs/msg/PointCloud2"
    adapter = staticmethod(point_cloud2_to_frame)


class Ros2OdometrySource(Ros2TopicSourceBase):
    output_types = {"odometry": "spatial.odometry/v1"}
    output_port = "odometry"
    nodrix_type = "spatial.odometry/v1"
    default_message_type = "nav_msgs/msg/Odometry"
    adapter = staticmethod(odometry_to_frame)


class Ros2ImuSource(Ros2TopicSourceBase):
    output_types = {"imu": "spatial.imu/v1"}
    output_port = "imu"
    nodrix_type = "spatial.imu/v1"
    default_message_type = "sensor_msgs/msg/Imu"
    adapter = staticmethod(imu_to_frame)
