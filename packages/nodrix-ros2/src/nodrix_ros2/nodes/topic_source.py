from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

from nodrix import Message, SourceNode

from ..common import (
    load_ros_message_type,
    message_frame_id,
    message_timestamp_ns,
    ros_to_python,
)
from ..context import RosNodeLease, shared_ros_runtime
from ..qos import build_qos_profile


class Ros2TopicSourceBase(SourceNode):
    output_types = {"output": "core.any"}
    output_port = "output"
    nodrix_type = "core.object"
    default_message_type: str | None = None
    adapter: Callable[[Any], Any] | None = None

    def open(self, context: Any) -> None:
        super().open(context)
        session = context.binding("session", required=False)
        self._session = session
        activate = getattr(session, "activate_python_environment", None)
        if callable(activate):
            activate()
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
        self._counter_lock = threading.Lock()
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
            executor_threads=int(
                self.parameters.get(
                    "executor_threads",
                    getattr(session, "executor_threads", 2),
                )
            ),
        )

        def callback(message: Any) -> None:
            with self._counter_lock:
                self._received += 1
            if self._inbox.full():
                try:
                    self._inbox.get_nowait()
                    with self._counter_lock:
                        self._dropped += 1
                except queue.Empty:
                    pass
            try:
                self._inbox.put_nowait(message)
            except queue.Full:
                with self._counter_lock:
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
        return ros_to_python(
            ros_message,
            maximum_binary_bytes=max(
                int(self.parameters.get("maximum_binary_bytes", 1_048_576)),
                0,
            ),
            maximum_sequence_items=max(
                int(self.parameters.get("maximum_sequence_items", 65_536)),
                0,
            ),
        )

    def produce(self):
        timeout = max(float(self.parameters.get("poll_timeout", 0.1)), 0.01)
        while not self._closed:
            try:
                ros_message = self._inbox.get(timeout=timeout)
            except queue.Empty:
                continue
            payload = self._convert(ros_message)
            ros_timestamp_ns = message_timestamp_ns(ros_message)
            timestamp_ns = ros_timestamp_ns or time.time_ns()
            with self._counter_lock:
                received = self._received
                dropped = self._dropped
            metadata = {
                "ros_topic": self._topic,
                "ros_message_type": self._message_type_name,
                "frame_id": message_frame_id(ros_message),
                "received": received,
                "bridge_queue_drops": dropped,
                "timestamp_source": "ros_header" if ros_timestamp_ns else "arrival",
            }
            yield {
                self.output_port: Message(
                    type=self.nodrix_type,
                    payload=payload,
                    sequence=self._sequence,
                    timestamp_ns=timestamp_ns,
                    stream_id=self._topic,
                    source_id=self._topic,
                    trace_id=self._sequence,
                    metadata=metadata,
                )
            }
            self._sequence += 1

    def health(self) -> dict[str, Any]:
        value = dict(super().health())
        counter_lock = getattr(self, "_counter_lock", None)
        if counter_lock is None:
            received = 0
            dropped = 0
        else:
            with counter_lock:
                received = self._received
                dropped = self._dropped
        value.update(
            {
                "ros_topic": getattr(self, "_topic", ""),
                "received": received,
                "dropped": dropped,
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
        super().close()


class Ros2TopicSource(Ros2TopicSourceBase):
    """Generic source for small ROS messages or an explicit custom mapper."""

    output_types = {"output": "core.any"}
    output_port = "output"
    nodrix_type = "core.object"


# Compatibility for alpha.1/alpha.2 extensions that subclassed the private
# base before it became a public bridge SDK surface.
_TopicSourceBase = Ros2TopicSourceBase
