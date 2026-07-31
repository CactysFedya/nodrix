from __future__ import annotations

from typing import Any

from nodrix import ProviderRuntime, register_message_type

from .types import OdometryFrame, PointCloudFrame


def register_types() -> None:
    register_message_type(
        "mapping.point_cloud/v1",
        PointCloudFrame,
        description="Timestamped structured point cloud backed by ManagedBuffer",
        version=1,
        replace=True,
    )
    register_message_type(
        "geometry.odometry/v1",
        OdometryFrame,
        description="Timestamped pose and twist with covariance",
        version=1,
        replace=True,
    )


def safe_probe() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": "nodrix.mapping",
        "types": ["mapping.point_cloud/v1", "geometry.odometry/v1"],
        "algorithms": 0,
    }


def provider() -> ProviderRuntime:
    register_types()
    return ProviderRuntime(
        provider_id="nodrix.mapping",
        nodes={},
        probes={"nodrix.mapping.safe": safe_probe},
    )
