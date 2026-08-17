"""Built-in runtime performance presets.

A RuntimePreset is not a project Profile.

Project Profiles are user-owned ``nodrix.profile/v1`` configuration overlays
resolved by the workspace/project layer. Runtime presets are built-in
performance defaults applied while resolving legacy Pipeline manifests.

The historical ``PROFILE_DEFAULTS``, ``profile_names()`` and ``get_profile()``
names remain compatibility aliases throughout the 2.x series.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


RUNTIME_PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "realtime-low-latency": {
        "runtime": {
            "mode": "realtime",
            "engine": "unified",
            "type_validation": "first",
            "metrics": {"enabled": True, "interval_ms": 1000},
            "shutdown": {"mode": "graceful", "timeout_ms": 10_000},
        },
        "node_defaults": {
            "media.ffmpeg_source": {
                "parameters": {
                    "rtsp_transport": "tcp",
                    "low_latency": True,
                    "realtime": False,
                },
                "health": {"timeout_ms": 5000, "on_timeout": "report"},
            },
            "media.ffmpeg_encoder": {
                "parameters": {
                    "codec": "h264",
                    "encoder": "auto",
                    "preset": "ultrafast",
                    "tune": "zerolatency",
                    "crf": 23,
                    "keyint": 15,
                    "chunk_size": 262_144,
                    "read_timeout_ms": 10,
                },
                "health": {"timeout_ms": 5000, "on_timeout": "report"},
            },
        },
        "edge_defaults": {"queue": {"capacity": 1, "policy": "latest"}},
        "stream_defaults": {
            "bind_host": "127.0.0.1",
            "listen_port": 7420,
            "max_message_bytes": 64 * 1024 * 1024,
            "max_handshake_bytes": 64 * 1024,
            "queue": {"capacity": 1, "policy": "latest"},
        },
    },
    "realtime-balanced": {
        "runtime": {
            "mode": "realtime",
            "engine": "unified",
            "type_validation": "first",
            "metrics": {"enabled": True, "interval_ms": 1000},
            "shutdown": {"mode": "graceful", "timeout_ms": 10_000},
        },
        "edge_defaults": {"queue": {"capacity": 2, "policy": "drop_oldest"}},
        "stream_defaults": {"queue": {"capacity": 2, "policy": "latest"}},
    },
    "lossless-recording": {
        "runtime": {
            "mode": "realtime",
            "engine": "unified",
            "type_validation": "first",
            "metrics": {"enabled": True, "interval_ms": 1000},
            "shutdown": {"mode": "graceful", "timeout_ms": 30_000},
        },
        "edge_defaults": {"queue": {"capacity": 32, "policy": "block"}},
        "stream_defaults": {"queue": {"capacity": 4, "policy": "latest"}},
        "node_defaults": {
            "media.ffmpeg_writer": {
                "parameters": {"encoder": "auto", "preset": "fast", "keyint": 30},
                "health": {"timeout_ms": 10_000, "on_timeout": "report"},
            }
        },
    },
    "maximum-throughput": {
        "runtime": {
            "mode": "offline",
            "engine": "unified",
            "type_validation": "first",
            "telemetry_samples": 16_384,
            "metrics": {"enabled": True, "interval_ms": 2000},
            "shutdown": {"mode": "graceful", "timeout_ms": 30_000},
        },
        "edge_defaults": {"queue": {"capacity": 64, "policy": "block"}},
        "stream_defaults": {"queue": {"capacity": 8, "policy": "block"}},
    },
    "debug": {
        "runtime": {
            "mode": "offline",
            "engine": "unified",
            "type_validation": "always",
            "telemetry_samples": 16_384,
            "metrics": {"enabled": True, "interval_ms": 500},
            "shutdown": {"mode": "graceful", "timeout_ms": 10_000},
        },
        "edge_defaults": {"queue": {"capacity": 8, "policy": "block"}},
        "stream_defaults": {"queue": {"capacity": 2, "policy": "latest"}},
    },
}


def runtime_preset_names() -> tuple[str, ...]:
    """Return the names of built-in runtime performance presets."""

    return tuple(RUNTIME_PRESET_DEFAULTS)


def get_runtime_preset(
    name: str | None,
) -> dict[str, Any]:
    """Return one independent copy of a built-in RuntimePreset."""

    if not name:
        return {}

    try:
        return deepcopy(
            RUNTIME_PRESET_DEFAULTS[name]
        )
    except KeyError as exc:
        raise ValueError(
            f"Unknown Plyctl runtime preset {name!r}; choose: "
            f"{', '.join(runtime_preset_names())}"
        ) from exc


# Compatibility names retained for the 2.x Pipeline API.
PROFILE_DEFAULTS = RUNTIME_PRESET_DEFAULTS


def profile_names() -> tuple[str, ...]:
    """Compatibility alias for runtime_preset_names()."""

    return runtime_preset_names()


def get_profile(
    name: str | None,
) -> dict[str, Any]:
    """Compatibility alias for get_runtime_preset()."""

    return get_runtime_preset(name)


__all__ = [
    "PROFILE_DEFAULTS",
    "RUNTIME_PRESET_DEFAULTS",
    "get_profile",
    "get_runtime_preset",
    "profile_names",
    "runtime_preset_names",
]
