from __future__ import annotations

from typing import Any

from nodrix import ProviderRuntime, register_message_type
from nodrix_spatial import OdometryFrame, PointCloudFrame, register_types as register_spatial_types


LEGACY_CONTRACTS = {
    "mapping.point_cloud/v1": (
        PointCloudFrame,
        "Deprecated alias for spatial.point_cloud/v1",
    ),
    "geometry.odometry/v1": (
        OdometryFrame,
        "Deprecated alias for spatial.odometry/v1",
    ),
}


def register_types() -> None:
    register_spatial_types()
    for type_id, (payload_type, description) in LEGACY_CONTRACTS.items():
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
        "provider": "nodrix.mapping",
        "types": sorted(LEGACY_CONTRACTS),
        "canonical_types": [
            "spatial.point_cloud/v1",
            "spatial.odometry/v1",
        ],
        "algorithms": 0,
    }


def provider() -> ProviderRuntime:
    register_types()
    return ProviderRuntime(
        provider_id="nodrix.mapping",
        nodes={},
        probes={"nodrix.mapping.safe": safe_probe},
    )
