from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


def ros_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def ros_arguments(
    *,
    node_name: str | None = None,
    namespace: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    remappings: Mapping[str, str] | None = None,
) -> list[str]:
    result: list[str] = []
    if node_name:
        result.extend(["-r", f"__node:={node_name}"])
    if namespace:
        result.extend(["-r", f"__ns:={namespace}"])
    for source, target in dict(remappings or {}).items():
        result.extend(["-r", f"{source}:={target}"])
    for name, value in dict(parameters or {}).items():
        result.extend(["-p", f"{name}:={ros_value(value)}"])
    return result


def build_ros2_run_command(parameters: Mapping[str, Any]) -> tuple[str, ...]:
    package = str(parameters.get("package", "")).strip()
    executable = str(parameters.get("executable", "")).strip()
    if not package or not executable:
        raise ValueError("ros2.node requires package and executable")
    command = ["ros2", "run", package, executable]
    command.extend(str(item) for item in parameters.get("arguments", ()))
    ros_args = ros_arguments(
        node_name=(str(parameters["name"]) if parameters.get("name") else None),
        namespace=(str(parameters["namespace"]) if parameters.get("namespace") else None),
        parameters=parameters.get("ros_parameters"),
        remappings=parameters.get("remappings"),
    )
    if ros_args:
        command.append("--ros-args")
        command.extend(ros_args)
    return tuple(command)


def build_ros2_launch_command(parameters: Mapping[str, Any]) -> tuple[str, ...]:
    package = str(parameters.get("package", "")).strip()
    launch_file = str(parameters.get("launch_file", "")).strip()
    if not package or not launch_file:
        raise ValueError("ros2.launch requires package and launch_file")
    command = ["ros2", "launch", package, launch_file]
    for name, value in dict(parameters.get("arguments") or {}).items():
        command.append(f"{name}:={ros_value(value)}")
    command.extend(str(item) for item in parameters.get("extra_args", ()))
    return tuple(command)


def build_rviz_command(parameters: Mapping[str, Any]) -> tuple[str, ...]:
    command = [str(parameters.get("executable") or "rviz2")]
    config = parameters.get("config")
    if config:
        command.extend(["-d", str(Path(str(config)).expanduser())])
    fixed_frame = parameters.get("fixed_frame")
    if fixed_frame:
        command.extend(["-f", str(fixed_frame)])
    ros_params = dict(parameters.get("ros_parameters") or {})
    ros_args = ros_arguments(
        node_name=(str(parameters["name"]) if parameters.get("name") else None),
        namespace=(str(parameters["namespace"]) if parameters.get("namespace") else None),
        parameters=ros_params,
        remappings=parameters.get("remappings"),
    )
    if ros_args:
        command.append("--ros-args")
        command.extend(ros_args)
    return tuple(command)
