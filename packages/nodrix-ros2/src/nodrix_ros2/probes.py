from __future__ import annotations

import importlib
import importlib.util
import os
from typing import Any


def safe_probe() -> dict[str, Any]:
    available = importlib.util.find_spec("rclpy") is not None
    interfaces = importlib.util.find_spec("rosidl_runtime_py") is not None
    return {
        "status": "ok" if available and interfaces else "unavailable",
        "rclpy": available,
        "rosidl_runtime_py": interfaces,
        "ros_distro": os.environ.get("ROS_DISTRO"),
        "rmw_implementation": os.environ.get("RMW_IMPLEMENTATION"),
    }


def deep_probe() -> dict[str, Any]:
    try:
        rclpy = importlib.import_module("rclpy")
        executors = importlib.import_module("rclpy.executors")
    except ModuleNotFoundError as exc:
        return {
            "status": "unavailable",
            "error": str(exc),
            "ros_distro": os.environ.get("ROS_DISTRO"),
        }
    return {
        "status": "ok",
        "rclpy_version": str(getattr(rclpy, "__version__", "unknown")),
        "executor": executors.MultiThreadedExecutor.__name__,
        "ros_distro": os.environ.get("ROS_DISTRO"),
        "rmw_implementation": os.environ.get("RMW_IMPLEMENTATION"),
    }
