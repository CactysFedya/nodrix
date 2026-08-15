"""Compatibility imports moved to the optional nodrix-spatial-ros2 package."""

try:
    from nodrix_spatial_ros2.adapters import (
        imu_to_frame,
        odometry_to_frame,
        point_cloud2_to_frame,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by wheel smoke
    raise ModuleNotFoundError(
        "Spatial ROS adapters moved to nodrix-spatial-ros2; install "
        "`nodrix-ros2[spatial]`"
    ) from exc

__all__ = ["point_cloud2_to_frame", "imu_to_frame", "odometry_to_frame"]
