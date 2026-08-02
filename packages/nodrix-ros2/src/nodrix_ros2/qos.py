from __future__ import annotations

import importlib
from typing import Any, Mapping


def build_qos_profile(
    parameters: Mapping[str, Any],
    *,
    default_reliability: str = "best_effort",
    default_depth: int = 1,
) -> Any:
    qos = dict(parameters.get("qos") or {})
    for name in (
        "depth",
        "reliability",
        "durability",
        "history",
        "preset",
    ):
        if name not in qos and name in parameters:
            qos[name] = parameters[name]

    qos_module = importlib.import_module("rclpy.qos")
    preset = str(qos.get("preset", "")).lower()
    if preset not in {"", "sensor_data"}:
        raise ValueError(f"Unsupported ROS QoS preset: {preset!r}")

    base = qos_module.qos_profile_sensor_data if preset == "sensor_data" else None

    reliability = str(qos.get("reliability", default_reliability)).lower()
    durability = str(qos.get("durability", "volatile")).lower()
    history = str(qos.get("history", "keep_last")).lower()
    if reliability not in {"reliable", "best_effort"}:
        raise ValueError(f"Unsupported ROS QoS reliability: {reliability!r}")
    if durability not in {"volatile", "transient_local"}:
        raise ValueError(f"Unsupported ROS QoS durability: {durability!r}")
    if history not in {"keep_last", "keep_all"}:
        raise ValueError(f"Unsupported ROS QoS history: {history!r}")

    reliability_policy = (
        qos_module.ReliabilityPolicy.RELIABLE
        if reliability == "reliable"
        else qos_module.ReliabilityPolicy.BEST_EFFORT
    )
    durability_policy = (
        qos_module.DurabilityPolicy.TRANSIENT_LOCAL
        if durability == "transient_local"
        else qos_module.DurabilityPolicy.VOLATILE
    )
    history_policy = (
        qos_module.HistoryPolicy.KEEP_ALL
        if history == "keep_all"
        else qos_module.HistoryPolicy.KEEP_LAST
    )

    return qos_module.QoSProfile(
        depth=max(
            int(qos.get("depth", getattr(base, "depth", default_depth))),
            1,
        ),
        reliability=(
            reliability_policy
            if "reliability" in qos or base is None
            else base.reliability
        ),
        durability=(
            durability_policy
            if "durability" in qos or base is None
            else base.durability
        ),
        history=(
            history_policy
            if "history" in qos or base is None
            else base.history
        ),
    )
