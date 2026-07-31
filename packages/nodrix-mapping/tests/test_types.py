from array import array

from nodrix import ManagedBuffer
from nodrix_mapping import PointCloudFrame, PointFieldSpec


def test_point_cloud_retains_buffer_without_copy() -> None:
    raw = array("B", range(16))
    frame = PointCloudFrame(
        timestamp_ns=1,
        frame_id="map",
        width=2,
        height=1,
        fields=(
            PointFieldSpec("x", 0, 7),
            PointFieldSpec("y", 4, 7),
        ),
        is_bigendian=False,
        point_step=8,
        row_step=16,
        is_dense=True,
        buffer=ManagedBuffer.wrap(raw, readonly=True),
    )
    assert frame.buffer.owner is raw
    assert frame.point_count == 2
    assert frame.nbytes == 16
