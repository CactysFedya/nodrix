from .process_nodes import Ros2LaunchProcess, Ros2NodeProcess, Ros2RvizProcess
from .topic_monitor import Ros2TopicMonitor
from .topic_sink import Ros2TopicSink
from .topic_source import (
    Ros2TopicSource,
    Ros2TopicSourceBase,
)


def __getattr__(name: str):
    if name in {
        "Ros2PointCloud2Source",
        "Ros2ImuSource",
        "Ros2OdometrySource",
    }:
        try:
            from nodrix_spatial_ros2 import nodes as spatial_nodes
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "Typed ROS Spatial nodes moved to nodrix-spatial-ros2; "
                "install `nodrix-ros2[spatial]`"
            ) from exc
        return getattr(spatial_nodes, name)
    raise AttributeError(name)

__all__ = [
    "Ros2NodeProcess",
    "Ros2LaunchProcess",
    "Ros2RvizProcess",
    "Ros2TopicMonitor",
    "Ros2TopicSource",
    "Ros2TopicSourceBase",
    "Ros2TopicSink",
]
