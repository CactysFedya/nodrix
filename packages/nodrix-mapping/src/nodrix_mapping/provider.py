from __future__ import annotations

import importlib.util
from typing import Any

from nodrix import ProviderRuntime, register_message_type
from nodrix_spatial import (
    OdometryFrame,
    PointCloudFrame,
    register_types as register_spatial_types,
)

from .voxel_types import VoxelMapDelta, VoxelMapSnapshot


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

MAPPING_CONTRACTS = {
    "mapping.voxel_delta/v1": (
        VoxelMapDelta,
        "Incremental bounded metric voxel-map update",
    ),
    "mapping.voxel_snapshot/v1": (
        VoxelMapSnapshot,
        "Complete bounded metric voxel-map snapshot",
    ),
}


def register_types() -> None:
    register_spatial_types()

    for type_id, (payload_type, description) in {
        **LEGACY_CONTRACTS,
        **MAPPING_CONTRACTS,
    }.items():
        register_message_type(
            type_id,
            payload_type,
            description=description,
            version=1,
            replace=True,
        )


def safe_probe() -> dict[str, Any]:
    native_available = (
        importlib.util.find_spec(
            "nodrix_mapping._mapping_native"
        )
        is not None
    )
    return {
        "status": "ok" if native_available else "degraded",
        "provider": "nodrix.mapping",
        "types": sorted(
            [*LEGACY_CONTRACTS, *MAPPING_CONTRACTS]
        ),
        "canonical_types": [
            "spatial.point_cloud/v1",
            "spatial.odometry/v1",
        ],
        "algorithms": 2,
        "native_backend": "cpp20-flat-hash",
        "native_ply": True,
        "native_available": native_available,
    }


def provider() -> ProviderRuntime:
    register_types()

    # Keep importing the implementation cheap: the compiled extension itself
    # is loaded lazily by node.open(), not while provider metadata is inspected.
    from .nodes.ply_store import PlyStoreNode
    from .nodes.voxel_map import VoxelMapNode

    return ProviderRuntime(
        provider_id="nodrix.mapping",
        nodes={
            "mapping.voxel_map": VoxelMapNode,
            "mapping.ply_store": PlyStoreNode,
        },
        probes={"nodrix.mapping.safe": safe_probe},
    )
