from __future__ import annotations

from typing import Any

from nodrix import ManagedBuffer
from nodrix_spatial import PointCloudFrame, PointFieldSpec

from ..common import message_frame_id, message_timestamp_ns


def point_cloud2_to_frame(message: Any) -> PointCloudFrame:
    data = getattr(message, "data")
    fields = tuple(
        PointFieldSpec(
            name=str(field.name),
            offset=int(field.offset),
            datatype=int(field.datatype),
            count=int(field.count),
        )
        for field in getattr(message, "fields")
    )
    return PointCloudFrame(
        timestamp_ns=message_timestamp_ns(message),
        frame_id=message_frame_id(message),
        width=int(getattr(message, "width")),
        height=int(getattr(message, "height")),
        fields=fields,
        is_bigendian=bool(getattr(message, "is_bigendian")),
        point_step=int(getattr(message, "point_step")),
        row_step=int(getattr(message, "row_step")),
        is_dense=bool(getattr(message, "is_dense")),
        buffer=ManagedBuffer.wrap(data, readonly=True),
        metadata={"ros_message_type": "sensor_msgs/msg/PointCloud2"},
    )
