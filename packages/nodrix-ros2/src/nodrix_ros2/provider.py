from __future__ import annotations

from nodrix import ProviderRuntime
from .nodes import (
    Ros2LaunchProcess,
    Ros2NodeProcess,
    Ros2RvizProcess,
    Ros2TopicMonitor,
    Ros2TopicSink,
    Ros2TopicSource,
)
from .probes import deep_probe, safe_probe
from .session import Ros2Session
from .applications import (
    Ros2LaunchApplication,
    Ros2NodeApplication,
    Ros2RvizApplication,
)


def provider() -> ProviderRuntime:
    return ProviderRuntime(
        provider_id="nodrix.ros2",
        nodes={
            "ros2.node": Ros2NodeProcess,
            "ros2.launch": Ros2LaunchProcess,
            "ros2.rviz": Ros2RvizProcess,
            "ros2.topic_monitor": Ros2TopicMonitor,
            "ros2.topic_source": Ros2TopicSource,
            "ros2.topic_sink": Ros2TopicSink,
            "ros2.source": Ros2TopicSource,
            "ros2.sink": Ros2TopicSink,
        },
        probes={
            "nodrix.ros2.safe": safe_probe,
            "nodrix.ros2.deep": deep_probe,
        },
        sessions={"ros2.session": Ros2Session},
        applications={
            "ros2.node": Ros2NodeApplication,
            "ros2.launch": Ros2LaunchApplication,
            "ros2.rviz": Ros2RvizApplication,
        },
    )
