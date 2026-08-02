from nodrix import ProviderRuntime
from nodrix_spatial import register_types

from .nodes import Ros2ImuSource, Ros2OdometrySource, Ros2PointCloud2Source


def provider() -> ProviderRuntime:
    register_types()
    return ProviderRuntime(
        provider_id="nodrix.ros2.spatial",
        nodes={
            "ros2.point_cloud2_source": Ros2PointCloud2Source,
            "ros2.imu_source": Ros2ImuSource,
            "ros2.odometry_source": Ros2OdometrySource,
        },
    )
