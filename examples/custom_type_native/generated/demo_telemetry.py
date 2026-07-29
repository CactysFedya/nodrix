from __future__ import annotations

from dataclasses import dataclass
import struct

from nodrix import register_message_type, register_wire_codec

TYPE_NAME = 'demo.Telemetry'
TYPE_VERSION = 1
_STRUCT = struct.Struct('<Qf3f')


@dataclass(slots=True)
class Telemetry:
    sequence: int
    temperature: float
    position: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.position) != 3:
            raise ValueError("position must contain 3 values")

    def to_bytes(self) -> bytes:
        values = []
        values.append(self.sequence)
        values.append(self.temperature)
        values.extend(self.position)
        return _STRUCT.pack(*values)

    @classmethod
    def from_bytes(cls, data) -> "Telemetry":
        if len(data) != _STRUCT.size:
            raise ValueError(f"{TYPE_NAME} expects {_STRUCT.size} bytes, got {len(data)}")
        values = _STRUCT.unpack(data)
        return cls(**{
            "sequence": values[0],
            "temperature": values[1],
            "position": tuple(values[2:5]),
        })


def _wire_encode(value: Telemetry):
    encoded = value.to_bytes()
    return {"version": TYPE_VERSION}, (memoryview(encoded),)


def _wire_decode(payload, metadata):
    if int(metadata.get("version", TYPE_VERSION)) != TYPE_VERSION:
        raise ValueError(f"Unsupported {TYPE_NAME} schema version")
    return Telemetry.from_bytes(payload)


def register() -> None:
    register_message_type(
        TYPE_NAME,
        Telemetry,
        description='Fixed-layout telemetry passed between Python and C++',
        replace=True,
    )
    register_wire_codec(TYPE_NAME, _wire_encode, _wire_decode)


register()
