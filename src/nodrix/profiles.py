from __future__ import annotations

from copy import deepcopy
from typing import Any


PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
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


def profile_names() -> tuple[str, ...]:
    return tuple(PROFILE_DEFAULTS)


def get_profile(name: str | None) -> dict[str, Any]:
    if not name:
        return {}
    try:
        return deepcopy(PROFILE_DEFAULTS[name])
    except KeyError as exc:
        raise ValueError(f"Unknown Nodrix profile {name!r}; choose: {', '.join(profile_names())}") from exc
