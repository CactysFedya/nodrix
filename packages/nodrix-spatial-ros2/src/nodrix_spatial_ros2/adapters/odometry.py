from __future__ import annotations

from typing import Any

from nodrix_spatial import OdometryFrame, Pose3D, Quaternion, Twist3D, Vector3
from nodrix_ros2.common import message_frame_id, message_timestamp_ns


def _vector(value: Any) -> Vector3:
    return Vector3(float(value.x), float(value.y), float(value.z))


def odometry_to_frame(message: Any) -> OdometryFrame:
    pose = message.pose.pose
    twist = message.twist.twist
    return OdometryFrame(
        timestamp_ns=message_timestamp_ns(message),
        frame_id=message_frame_id(message),
        child_frame_id=str(getattr(message, "child_frame_id", "") or ""),
        pose=Pose3D(
            position=_vector(pose.position),
            orientation=Quaternion(
                float(pose.orientation.x),
                float(pose.orientation.y),
                float(pose.orientation.z),
                float(pose.orientation.w),
            ),
        ),
        twist=Twist3D(
            linear=_vector(twist.linear),
            angular=_vector(twist.angular),
        ),
        pose_covariance=tuple(float(v) for v in message.pose.covariance),
        twist_covariance=tuple(float(v) for v in message.twist.covariance),
        metadata={"ros_message_type": "nav_msgs/msg/Odometry"},
    )
