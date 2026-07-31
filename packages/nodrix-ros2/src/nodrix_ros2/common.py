from __future__ import annotations

from collections.abc import Mapping, Sequence
import importlib
from typing import Any


def load_ros_message_type(reference: str) -> type[Any]:
    text = str(reference).strip()
    if not text:
        raise ValueError("message_type is required")
    if "/" in text:
        try:
            utilities = importlib.import_module("rosidl_runtime_py.utilities")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "ROS interface lookup requires rosidl_runtime_py from a sourced ROS 2 installation"
            ) from exc
        return utilities.get_message(text)

    module_name, separator, symbol = text.replace(":", ".").rpartition(".")
    if not separator:
        raise ValueError(
            "ROS message type must use package/msg/Type or module.Symbol syntax"
        )
    return getattr(importlib.import_module(module_name), symbol)


def stamp_to_ns(stamp: Any) -> int:
    if stamp is None:
        return 0
    return int(getattr(stamp, "sec", 0)) * 1_000_000_000 + int(
        getattr(stamp, "nanosec", 0)
    )


def message_timestamp_ns(message: Any) -> int:
    header = getattr(message, "header", None)
    return stamp_to_ns(getattr(header, "stamp", None))


def message_frame_id(message: Any) -> str:
    header = getattr(message, "header", None)
    return str(getattr(header, "frame_id", "") or "")


def ros_to_python(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, bytes, bytearray)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): ros_to_python(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [ros_to_python(item) for item in value]
    fields = getattr(value, "get_fields_and_field_types", None)
    if callable(fields):
        return {
            name: ros_to_python(getattr(value, name))
            for name in fields()
        }
    return value


def assign_ros(target: Any, values: Mapping[str, Any]) -> Any:
    for name, value in values.items():
        if not hasattr(target, name):
            raise ValueError(f"ROS message has no field {name!r}")
        current = getattr(target, name)
        if isinstance(value, Mapping) and hasattr(
            current, "get_fields_and_field_types"
        ):
            assign_ros(current, value)
        else:
            setattr(target, name, value)
    return target
