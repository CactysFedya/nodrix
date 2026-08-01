from __future__ import annotations

import queue
import time
from typing import Any, Callable

from nodrix import Message, SourceNode

from ..adapters import imu_to_frame, odometry_to_frame, point_cloud2_to_frame
from ..common import (
    load_ros_message_type,
    message_frame_id,
    message_timestamp_ns,
    ros_to_python,
)
from ..context import RosNodeLease, shared_ros_runtime
from ..qos import build_qos_profile


class _TopicSourceBase(SourceNode):
    output_types = {"output": "core.any"}
    output_port = "output"
    nodrix_type = "core.object"
    default_message_type: str | None = None
    adapter: Callable[[Any], Any] | None = None

    def open(self, context: Any) -> None:
        super().open(context)
        topic = str(self.parameters.get("topic", "")).strip()
        if not topic:
            raise ValueError(f"{type(self).__name__} requires parameters.topic")
        message_type = str(
            self.parameters.get("message_type")
            or self.default_message_type
            or ""
        ).strip()
        if not message_type:
            raise ValueError(
                f"{type(self).__name__} requires parameters.message_type"
            )

        self._topic = topic
        self._message_type_name = message_type
        self._message_class = load_ros_message_type(message_type)
        self._closed = False
        self._sequence = 0
        self._received = 0
        self._dropped = 0
        self._capacity = max(int(self.parameters.get("capacity", 1)), 1)
        self._inbox: queue.Queue[Any] = queue.Queue(self._capacity)
        self._lease: RosNodeLease = shared_ros_runtime().acquire_node(
            name=str(
                self.parameters.get(
                    "node_name",
                    f"nodrix_{context.name}",
                )
            ),
            namespace=str(self.parameters.get("namespace", "")),
            executor_threads=int(self.parameters.get("executor_threads", 2)),
        )

        def callback(message: Any) -> None:
            self._received += 1
            if self._inbox.full():
                try:
                    self._inbox.get_nowait()
                    self._dropped += 1
                except queue.Empty:
                    pass
            try:
                self._inbox.put_nowait(message)
            except queue.Full:
                self._dropped += 1

        self._subscription = self._lease.node.create_subscription(
            self._message_class,
            topic,
            callback,
            build_qos_profile(self.parameters),
        )

    def _convert(self, ros_message: Any) -> Any:
        if self.adapter is not None:
            return self.adapter(ros_message)
        if bool(self.parameters.get("raw_message", False)):
            return ros_message
        return ros_to_python(ros_message)

    def produce(self):
        timeout = max(float(self.parameters.get("poll_timeout", 0.1)), 0.01)
        while not self._closed:
            try:
                ros_message = self._inbox.get(timeout=timeout)
            except queue.Empty:
                continue
            payload = self._convert(ros_message)
            timestamp_ns = message_timestamp_ns(ros_message) or time.time_ns()
            metadata = {
                "ros_topic": self._topic,
                "ros_message_type": self._message_type_name,
                "frame_id": message_frame_id(ros_message),
                "received": self._received,
                "publisher_drops": self._dropped,
            }
            yield {
                self.output_port: Message(
                    type=self.nodrix_type,
                    payload=payload,
                    sequence=self._sequence,
                    timestamp_ns=timestamp_ns,
                    stream_id=self._topic,
                    trace_id=self._sequence,
                    metadata=metadata,
                )
            }
            self._sequence += 1

    def health(self) -> dict[str, Any]:
        value = dict(super().health())
        value.update(
            {
                "ros_topic": getattr(self, "_topic", ""),
                "received": getattr(self, "_received", 0),
                "dropped": getattr(self, "_dropped", 0),
                "queue_depth": (
                    self._inbox.qsize()
                    if getattr(self, "_inbox", None) is not None
                    else 0
                ),
            }
        )
        return value

    def close(self) -> None:
        self._closed = True
        lease = getattr(self, "_lease", None)
        subscription = getattr(self, "_subscription", None)
        if lease is not None and subscription is not None:
            try:
                lease.node.destroy_subscription(subscription)
            except Exception:
                pass
        if lease is not None:
            lease.close()
        self._lease = None


class Ros2TopicSource(_TopicSourceBase):
    """Generic source for small ROS messages or an explicit custom mapper."""

    output_types = {"output": "core.any"}
    output_port = "output"
    nodrix_type = "core.object"


class Ros2PointCloud2Source(_TopicSourceBase):
    """Typed PointCloud2 source preserving the ROS data buffer by reference."""

    output_types = {"cloud": "spatial.point_cloud/v1"}
    output_port = "cloud"
    nodrix_type = "spatial.point_cloud/v1"
    default_message_type = "sensor_msgs/msg/PointCloud2"
    adapter = staticmethod(point_cloud2_to_frame)


class Ros2OdometrySource(_TopicSourceBase):
    """Typed nav_msgs/Odometry source."""

    output_types = {"odometry": "spatial.odometry/v1"}
    output_port = "odometry"
    nodrix_type = "spatial.odometry/v1"
    default_message_type = "nav_msgs/msg/Odometry"
    adapter = staticmethod(odometry_to_frame)


class Ros2ImuSource(_TopicSourceBase):
    """Typed sensor_msgs/Imu source."""

    output_types = {"imu": "spatial.imu/v1"}
    output_port = "imu"
    nodrix_type = "spatial.imu/v1"
    default_message_type = "sensor_msgs/msg/Imu"
    adapter = staticmethod(imu_to_frame)
