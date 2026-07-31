from __future__ import annotations

import importlib
from typing import Any, Mapping


def build_qos_profile(parameters: Mapping[str, Any]) -> Any:
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
    if preset == "sensor_data":
        return qos_module.qos_profile_sensor_data

    reliability = str(qos.get("reliability", "best_effort")).lower()
    durability = str(qos.get("durability", "volatile")).lower()
    history = str(qos.get("history", "keep_last")).lower()

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
        depth=max(int(qos.get("depth", 1)), 1),
        reliability=reliability_policy,
        durability=durability_policy,
        history=history_policy,
    )
