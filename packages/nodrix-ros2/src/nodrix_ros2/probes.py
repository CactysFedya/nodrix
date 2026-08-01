from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
from typing import Any


def safe_probe() -> dict[str, Any]:
    available = importlib.util.find_spec("rclpy") is not None
    interfaces = importlib.util.find_spec("rosidl_runtime_py") is not None
    ros2_cli = shutil.which("ros2")
    return {
        "status": "ok" if available and interfaces and ros2_cli else "unavailable",
        "rclpy": available,
        "rosidl_runtime_py": interfaces,
        "ros2_cli": ros2_cli,
        "colcon": shutil.which("colcon"),
        "rviz2": shutil.which("rviz2"),
        "ros_distro": os.environ.get("ROS_DISTRO"),
        "rmw_implementation": os.environ.get("RMW_IMPLEMENTATION"),
    }


def deep_probe() -> dict[str, Any]:
    result = safe_probe()
    try:
        rclpy = importlib.import_module("rclpy")
        executors = importlib.import_module("rclpy.executors")
    except ModuleNotFoundError as exc:
        return {**result, "status": "unavailable", "error": str(exc)}
    return {
        **result,
        "status": "ok" if result.get("ros2_cli") else "unavailable",
        "rclpy_version": str(getattr(rclpy, "__version__", "unknown")),
        "executor": executors.MultiThreadedExecutor.__name__,
    }
