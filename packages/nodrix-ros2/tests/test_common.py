from dataclasses import dataclass

import pytest

from nodrix_ros2.common import ros_to_python


@dataclass
class LargeMessage:
    data: bytes

    def get_fields_and_field_types(self):
        return {"data": "sequence<uint8>"}


def test_generic_conversion_rejects_large_binary_payload() -> None:
    with pytest.raises(ValueError, match="typed/native adapter"):
        ros_to_python(LargeMessage(b"12345"), maximum_binary_bytes=4)
