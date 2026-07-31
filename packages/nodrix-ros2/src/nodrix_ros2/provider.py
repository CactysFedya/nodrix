from __future__ import annotations

from nodrix import ProviderRuntime
from nodrix_mapping import register_types

from .nodes import (
    Ros2OdometrySource,
    Ros2PointCloud2Source,
    Ros2TopicSink,
    Ros2TopicSource,
)
from .probes import deep_probe, safe_probe


def provider() -> ProviderRuntime:
    register_types()
    return ProviderRuntime(
        provider_id="nodrix.ros2",
        nodes={
            "ros2.topic_source": Ros2TopicSource,
            "ros2.topic_sink": Ros2TopicSink,
            "ros2.point_cloud2_source": Ros2PointCloud2Source,
            "ros2.odometry_source": Ros2OdometrySource,
        },
        probes={
            "nodrix.ros2.safe": safe_probe,
            "nodrix.ros2.deep": deep_probe,
        },
    )
