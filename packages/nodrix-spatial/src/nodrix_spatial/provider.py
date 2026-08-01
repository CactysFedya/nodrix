from __future__ import annotations

from typing import Any

from nodrix import ProviderRuntime, register_message_type

from .types import ImuFrame, OdometryFrame, PointCloudFrame, TransformFrame


CONTRACTS = {
    "spatial.point_cloud/v1": (
        PointCloudFrame,
        "Timestamped structured point cloud backed by ManagedBuffer",
    ),
    "spatial.imu/v1": (ImuFrame, "Timestamped inertial measurement"),
    "spatial.odometry/v1": (
        OdometryFrame,
        "Timestamped pose and twist with covariance",
    ),
    "spatial.transform/v1": (
        TransformFrame,
        "Timestamped transform between coordinate frames",
    ),
}


def register_types() -> None:
    for type_id, (payload_type, description) in CONTRACTS.items():
        register_message_type(
            type_id,
            payload_type,
            description=description,
            version=1,
            replace=True,
        )


def safe_probe() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": "nodrix.spatial",
        "types": sorted(CONTRACTS),
        "algorithms": 0,
    }


def provider() -> ProviderRuntime:
    register_types()
    return ProviderRuntime(
        provider_id="nodrix.spatial",
        nodes={},
        probes={"nodrix.spatial.safe": safe_probe},
    )
