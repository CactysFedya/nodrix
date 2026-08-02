from .context import SharedRosRuntime, shared_ros_runtime
from .nodes import (
    Ros2LaunchProcess,
    Ros2NodeProcess,
    Ros2RvizProcess,
    Ros2TopicMonitor,
    Ros2TopicSink,
    Ros2TopicSource,
)
from .provider import provider
from .session import Ros2Session
from .applications import (
    Ros2LaunchApplication,
    Ros2NodeApplication,
    Ros2RvizApplication,
)
from .workspace import RosBuildSpec, RosWorkspaceManager, RosWorkspaceSpec


def __getattr__(name: str):
    if name in {
        "Ros2PointCloud2Source",
        "Ros2ImuSource",
        "Ros2OdometrySource",
    }:
        from . import nodes

        return getattr(nodes, name)
    raise AttributeError(name)

__all__ = [
    "SharedRosRuntime",
    "shared_ros_runtime",
    "RosWorkspaceManager",
    "RosWorkspaceSpec",
    "RosBuildSpec",
    "Ros2NodeProcess",
    "Ros2LaunchProcess",
    "Ros2RvizProcess",
    "Ros2TopicMonitor",
    "Ros2TopicSource",
    "Ros2TopicSink",
    "Ros2Session",
    "Ros2LaunchApplication",
    "Ros2NodeApplication",
    "Ros2RvizApplication",
    "provider",
]

__version__ = "0.4.0"
