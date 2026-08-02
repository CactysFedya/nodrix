from __future__ import annotations

from typing import Any

from nodrix_spatial import ImuFrame, Quaternion, Vector3
from nodrix_ros2.common import message_frame_id, message_timestamp_ns


def _vector(value: Any) -> Vector3:
    return Vector3(float(value.x), float(value.y), float(value.z))


def imu_to_frame(message: Any) -> ImuFrame:
    orientation = message.orientation
    return ImuFrame(
        timestamp_ns=message_timestamp_ns(message),
        frame_id=message_frame_id(message),
        orientation=Quaternion(
            float(orientation.x),
            float(orientation.y),
            float(orientation.z),
            float(orientation.w),
        ),
        angular_velocity=_vector(message.angular_velocity),
        linear_acceleration=_vector(message.linear_acceleration),
        orientation_covariance=tuple(float(v) for v in message.orientation_covariance),
        angular_velocity_covariance=tuple(float(v) for v in message.angular_velocity_covariance),
        linear_acceleration_covariance=tuple(float(v) for v in message.linear_acceleration_covariance),
        metadata={"ros_message_type": "sensor_msgs/msg/Imu"},
    )
