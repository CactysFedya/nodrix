"""Compatibility imports for the 2.2 alpha transition.

Spatial payload ownership moved to :mod:`nodrix_spatial`. These names remain
available so existing alpha pipelines and providers do not break.
"""

from nodrix_spatial.types import (
    OdometryFrame,
    PointCloudFrame,
    PointFieldSpec,
    Pose3D,
    Quaternion,
    Twist3D,
    Vector3,
)

__all__ = [
    "PointFieldSpec",
    "PointCloudFrame",
    "Vector3",
    "Quaternion",
    "Pose3D",
    "Twist3D",
    "OdometryFrame",
]
