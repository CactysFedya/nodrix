from __future__ import annotations

import importlib
import queue
from typing import Any, Callable

from .messages import Message
from .node import SinkNode, SourceNode
from .registry import register_builtin


def _load_symbol(reference: str) -> Any:
    module_name, separator, symbol = reference.replace(":", ".").rpartition(".")
    if not separator:
        raise ValueError(f"ROS 2 type/mapper must use module.Symbol: {reference!r}")
    return getattr(importlib.import_module(module_name), symbol)


def _ros_to_python(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, bytes, bytearray)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_ros_to_python(item) for item in value]
    fields = getattr(value, "get_fields_and_field_types", None)
    if callable(fields):
        return {
            name: _ros_to_python(getattr(value, name))
            for name in fields()
        }
    return value


def _assign_ros(target: Any, values: dict[str, Any]) -> Any:
    for name, value in values.items():
        if not hasattr(target, name):
            raise ValueError(f"ROS message has no field {name!r}")
        current = getattr(target, name)
        if isinstance(value, dict) and hasattr(current, "get_fields_and_field_types"):
            _assign_ros(current, value)
        else:
            setattr(target, name, value)
    return target


def _qos_profile(rclpy: Any, parameters: dict[str, Any]) -> Any:
    qos_module = importlib.import_module("rclpy.qos")
    reliability = str(parameters.get("reliability", "best_effort")).lower()
    durability = str(parameters.get("durability", "volatile")).lower()
    return qos_module.QoSProfile(
        depth=max(int(parameters.get("depth", 1)), 1),
        reliability=(
            qos_module.ReliabilityPolicy.RELIABLE
            if reliability == "reliable"
            else qos_module.ReliabilityPolicy.BEST_EFFORT
        ),
        durability=(
            qos_module.DurabilityPolicy.TRANSIENT_LOCAL
            if durability == "transient_local"
            else qos_module.DurabilityPolicy.VOLATILE
        ),
    )


class _Ros2Base:
    def _open_ros(self, context: Any) -> None:
        try:
            self.rclpy = importlib.import_module("rclpy")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "ROS 2 adapters require a ROS 2 installation with rclpy; "
                "rclpy is intentionally not a Nodrix dependency"
            ) from exc
        self._owns_context = not self.rclpy.ok()
        if self._owns_context:
            self.rclpy.init(args=None)
        self.ros_node = self.rclpy.create_node(
            str(self.parameters.get("node_name", f"nodrix_{context.name}"))
        )
        self.message_class = _load_symbol(str(self.parameters["message_type"]))
        mapper = self.parameters.get("mapper")
        self.mapper: Callable[..., Any] | None = (
            _load_symbol(str(mapper)) if mapper else None
        )

    def _close_ros(self) -> None:
        if getattr(self, "ros_node", None) is not None:
            self.ros_node.destroy_node()
            self.ros_node = None
        if getattr(self, "_owns_context", False) and self.rclpy.ok():
            self.rclpy.shutdown()


@register_builtin("ros2.source")
class Ros2Source(_Ros2Base, SourceNode):
    """Optional ROS 2 subscription adapter with a bounded latest-message inbox."""

    output_types = {"output": "core.any"}

    def open(self, context: Any) -> None:
        super().open(context)
        self._open_ros(context)
        capacity = max(int(self.parameters.get("capacity", 1)), 1)
        self.inbox: queue.Queue[Any] = queue.Queue(capacity)

        def callback(message: Any) -> None:
            if self.inbox.full():
                try:
                    self.inbox.get_nowait()
                except queue.Empty:
                    pass
            try:
                self.inbox.put_nowait(message)
            except queue.Full:
                pass

        self.subscription = self.ros_node.create_subscription(
            self.message_class,
            str(self.parameters["topic"]),
            callback,
            _qos_profile(self.rclpy, self.parameters),
        )

    def produce(self):
        sequence = 0
        while True:
            self.rclpy.spin_once(
                self.ros_node,
                timeout_sec=float(self.parameters.get("spin_timeout", 0.1)),
            )
            try:
                ros_message = self.inbox.get_nowait()
            except queue.Empty:
                continue
            payload = (
                self.mapper(ros_message)
                if self.mapper is not None
                else _ros_to_python(ros_message)
            )
            yield {
                "output": Message(
                    str(self.parameters.get("nodrix_type", "core.object")),
                    payload,
                    sequence=sequence,
                    source_id=str(self.parameters["topic"]),
                )
            }
            sequence += 1

    def close(self) -> None:
        self._close_ros()


@register_builtin("ros2.sink")
class Ros2Sink(_Ros2Base, SinkNode):
    """Optional ROS 2 publisher adapter with explicit QoS and timestamp mapping."""

    input_types = {"input": "core.any"}

    def open(self, context: Any) -> None:
        super().open(context)
        self._open_ros(context)
        self.publisher = self.ros_node.create_publisher(
            self.message_class,
            str(self.parameters["topic"]),
            _qos_profile(self.rclpy, self.parameters),
        )

    def process(self, inputs: dict[str, Message]) -> None:
        message = inputs["input"]
        ros_message = (
            self.mapper(message)
            if self.mapper is not None
            else _assign_ros(self.message_class(), dict(message.payload))
        )
        header = getattr(ros_message, "header", None)
        stamp = getattr(header, "stamp", None)
        if stamp is not None and bool(self.parameters.get("map_timestamp", True)):
            stamp.sec = int(message.timestamp_ns // 1_000_000_000)
            stamp.nanosec = int(message.timestamp_ns % 1_000_000_000)
        self.publisher.publish(ros_message)

    def close(self) -> None:
        self._close_ros()
