from array import array
from dataclasses import dataclass, field

from nodrix_ros2.adapters import odometry_to_frame, point_cloud2_to_frame


@dataclass
class Stamp:
    sec: int = 1
    nanosec: int = 2


@dataclass
class Header:
    stamp: Stamp = field(default_factory=Stamp)
    frame_id: str = "map"


@dataclass
class Field:
    name: str
    offset: int
    datatype: int = 7
    count: int = 1


class PointCloud:
    header = Header()
    width = 2
    height = 1
    fields = [Field("x", 0), Field("y", 4)]
    is_bigendian = False
    point_step = 8
    row_step = 16
    is_dense = True

    def __init__(self) -> None:
        self.data = array("B", range(16))


@dataclass
class V3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class Q:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0


@dataclass
class Pose:
    position: V3 = field(default_factory=V3)
    orientation: Q = field(default_factory=Q)


@dataclass
class Twist:
    linear: V3 = field(default_factory=V3)
    angular: V3 = field(default_factory=V3)


@dataclass
class WithCovariance:
    pose: Pose = field(default_factory=Pose)
    covariance: list[float] = field(default_factory=lambda: [0.0] * 36)


@dataclass
class TwistWithCovariance:
    twist: Twist = field(default_factory=Twist)
    covariance: list[float] = field(default_factory=lambda: [0.0] * 36)


class Odometry:
    header = Header()
    child_frame_id = "base_link"
    pose = WithCovariance()
    twist = TwistWithCovariance()


def test_point_cloud_adapter_does_not_copy_data() -> None:
    message = PointCloud()
    frame = point_cloud2_to_frame(message)
    assert frame.buffer.owner is message.data
    assert frame.timestamp_ns == 1_000_000_002
    assert frame.point_count == 2


def test_odometry_adapter_is_typed() -> None:
    frame = odometry_to_frame(Odometry())
    assert frame.frame_id == "map"
    assert frame.child_frame_id == "base_link"
    assert frame.pose.orientation.w == 1.0
