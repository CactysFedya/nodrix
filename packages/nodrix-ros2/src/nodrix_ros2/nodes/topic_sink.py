from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nodrix import Message, SinkNode

from ..common import assign_ros, load_ros_message_type
from ..context import RosNodeLease, shared_ros_runtime
from ..qos import build_qos_profile


class Ros2TopicSink(SinkNode):
    """Generic ROS publisher for raw ROS messages or mapping payloads."""

    input_types = {"input": "core.any"}

    def open(self, context: Any) -> None:
        super().open(context)
        session = context.binding("session", required=False)
        activate = getattr(session, "activate_python_environment", None)
        if callable(activate):
            activate()
        topic = str(self.parameters.get("topic", "")).strip()
        message_type = str(self.parameters.get("message_type", "")).strip()
        if not topic:
            raise ValueError("ros2.topic_sink requires parameters.topic")
        if not message_type:
            raise ValueError(
                "ros2.topic_sink requires parameters.message_type"
            )
        self._topic = topic
        self._message_class = load_ros_message_type(message_type)
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
        self._publisher = self._lease.node.create_publisher(
            self._message_class,
            topic,
            build_qos_profile(self.parameters),
        )

    def process(self, inputs: dict[str, Message]) -> None:
        message = inputs["input"]
        payload = message.payload
        if isinstance(payload, self._message_class):
            ros_message = payload
        elif isinstance(payload, Mapping):
            ros_message = assign_ros(self._message_class(), payload)
        else:
            candidate = getattr(payload, "ros_message", None)
            if not isinstance(candidate, self._message_class):
                raise TypeError(
                    "ros2.topic_sink expects a ROS message instance, mapping, "
                    "or payload.ros_message"
                )
            ros_message = candidate

        if bool(self.parameters.get("map_timestamp", True)):
            header = getattr(ros_message, "header", None)
            stamp = getattr(header, "stamp", None)
            if stamp is not None:
                stamp.sec = int(message.timestamp_ns // 1_000_000_000)
                stamp.nanosec = int(message.timestamp_ns % 1_000_000_000)
        self._publisher.publish(ros_message)
        return None

    def close(self) -> None:
        lease = getattr(self, "_lease", None)
        publisher = getattr(self, "_publisher", None)
        if lease is not None and publisher is not None:
            try:
                lease.node.destroy_publisher(publisher)
            except Exception:
                pass
        if lease is not None:
            lease.close()
        self._lease = None
