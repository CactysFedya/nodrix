from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nodrix import ManagedBuffer


@dataclass(frozen=True, slots=True)
class PointFieldSpec:
    name: str
    offset: int
    datatype: int
    count: int = 1

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Point field name cannot be empty")
        if self.offset < 0:
            raise ValueError("Point field offset cannot be negative")
        if self.count <= 0:
            raise ValueError("Point field count must be positive")


@dataclass(slots=True)
class PointCloudFrame:
    timestamp_ns: int
    frame_id: str
    width: int
    height: int
    fields: tuple[PointFieldSpec, ...]
    is_bigendian: bool
    point_step: int
    row_step: int
    is_dense: bool
    buffer: ManagedBuffer
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError("Point-cloud timestamp cannot be negative")
        if self.width < 0 or self.height < 0:
            raise ValueError("Point-cloud dimensions cannot be negative")
        if self.point_step <= 0:
            raise ValueError("point_step must be positive")
        if self.row_step < 0:
            raise ValueError("row_step cannot be negative")
        minimum = self.row_step * self.height
        if minimum and self.buffer.nbytes < minimum:
            raise ValueError(
                f"Point-cloud buffer is too small: {self.buffer.nbytes} < {minimum}"
            )

    @property
    def point_count(self) -> int:
        return int(self.width) * int(self.height)

    @property
    def nbytes(self) -> int:
        return self.buffer.nbytes


@dataclass(frozen=True, slots=True)
class Vector3:
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class Quaternion:
    x: float
    y: float
    z: float
    w: float


@dataclass(frozen=True, slots=True)
class Pose3D:
    position: Vector3
    orientation: Quaternion


@dataclass(frozen=True, slots=True)
class Twist3D:
    linear: Vector3
    angular: Vector3


@dataclass(slots=True)
class OdometryFrame:
    timestamp_ns: int
    frame_id: str
    child_frame_id: str
    pose: Pose3D
    twist: Twist3D
    pose_covariance: tuple[float, ...] = ()
    twist_covariance: tuple[float, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError("Odometry timestamp cannot be negative")
        if self.pose_covariance and len(self.pose_covariance) != 36:
            raise ValueError("pose_covariance must contain 36 values")
        if self.twist_covariance and len(self.twist_covariance) != 36:
            raise ValueError("twist_covariance must contain 36 values")
