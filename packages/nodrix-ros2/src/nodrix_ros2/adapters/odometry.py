from __future__ import annotations

from typing import Any


def _vector(value: Any):
    from nodrix_mapping import Vector3

    return Vector3(float(value.x), float(value.y), float(value.z))


def odometry_to_frame(message: Any):
    try:
        from nodrix_mapping import (
            OdometryFrame,
            Pose3D,
            Quaternion,
            Twist3D,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "ros2.odometry_source requires the nodrix-mapping package"
        ) from exc

    from ..common import message_frame_id, message_timestamp_ns

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
