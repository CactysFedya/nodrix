from __future__ import annotations

import json
from pathlib import Path
import struct

import pytest

import nodrix
from nodrix import Message
import nodrix.recording as recording
from nodrix.recording import (
    NdrxReader,
    NdrxWriter,
    RecordingError,
    repair_recording,
)
from nodrix.wire import encode_message


def _messages(count: int) -> list[Message]:
    return [
        Message(
            "core.object",
            {"value": index},
            sequence=index,
            timestamp_ns=1000 + index,
            stream_id="/events",
        )
        for index in range(count)
    ]


def _write_v1(path: Path, messages: list[Message]) -> None:
    file_header = struct.Struct("!4sBI")
    record_header = struct.Struct("!QQ")
    index_header = struct.Struct("!4sQ")
    footer = struct.Struct("!4sQ")
    metadata = json.dumps({"format": "nodrix-recording/1"}).encode("utf-8")
    entries: list[dict[str, object]] = []
    payload_bytes = 0
    with path.open("wb") as handle:
        handle.write(file_header.pack(b"NDRF", 1, len(metadata)))
        handle.write(metadata)
        for arrival_ns, message in enumerate(messages, start=10):
            packet = encode_message(message)
            offset = handle.tell()
            handle.write(record_header.pack(arrival_ns, packet.nbytes))
            for part in packet.parts():
                handle.write(part)
            payload_bytes += packet.nbytes
            entries.append(
                {
                    "offset": offset,
                    "arrival_ns": arrival_ns,
                    "stream_id": message.stream_id,
                    "type": message.type,
                    "sequence": message.sequence,
                    "timestamp_ns": message.timestamp_ns,
                    "packet_bytes": packet.nbytes,
                }
            )
        index_offset = handle.tell()
        index = json.dumps(
            {
                "messages": len(messages),
                "payload_bytes": payload_bytes,
                "streams": {
                    "/events": {
                        "type": "core.object",
                        "messages": len(messages),
                    }
                },
                "entries": entries,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        handle.write(index_header.pack(b"NDXI", len(index)))
        handle.write(index)
        handle.write(footer.pack(b"NDXF", index_offset))


def test_v170_version() -> None:
    assert nodrix.__version__ == "2.3.0a1"


def test_ndrx2_uses_bounded_checkpoints_and_checksums(tmp_path: Path) -> None:
    path = tmp_path / "checkpointed.ndrx"
    writer = NdrxWriter(path, checkpoint_records=3, durable=False)
    for message in _messages(10):
        writer.write(message)
        assert len(writer._chunk_entries) < 3
    writer.close()

    with NdrxReader(path) as reader:
        info = reader.info()
        values = [message.payload["value"] for _, message in reader.iter_messages()]
    assert info["format"] == "nodrix-recording/2"
    assert info["messages"] == 10
    assert info["chunks"] == 4
    assert info["finalized"] is True
    assert "entries" not in reader.index
    assert values == list(range(10))


def test_ndrx2_indexed_seek_and_limit(tmp_path: Path) -> None:
    path = tmp_path / "seek.ndrx"
    with NdrxWriter(path, checkpoint_records=3, durable=False) as writer:
        for message in _messages(10):
            writer.write(message)
    with NdrxReader(path) as reader:
        values = [
            message.payload["value"]
            for _, message in reader.iter_messages(start=4, limit=3)
        ]
    assert values == [4, 5, 6]


def test_ndrx2_recovers_complete_records_after_interruption(tmp_path: Path) -> None:
    path = tmp_path / "interrupted.ndrx"
    writer = NdrxWriter(path, checkpoint_records=2, durable=False)
    for message in _messages(5):
        writer.write(message)
    writer.abort()
    data = path.read_bytes()
    path.write_bytes(data[:-8])

    with NdrxReader(path, recover=True) as reader:
        info = reader.info()
        values = [message.payload["value"] for _, message in reader.iter_messages()]
    assert info["recovered"] is True
    assert info["finalized"] is False
    assert info["messages"] == 4
    assert values == [0, 1, 2, 3]
    with pytest.raises(RecordingError, match="not checkpointed|summary"):
        NdrxReader(path, recover=False)


def test_ndrx2_detects_chunk_corruption(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.ndrx"
    with NdrxWriter(path, checkpoint_records=2, durable=False) as writer:
        for message in _messages(2):
            writer.write(message)
    data = bytearray(path.read_bytes())
    _, _, metadata_len = recording._FILE_HEADER.unpack(
        data[: recording._FILE_HEADER.size]
    )
    payload_offset = (
        recording._FILE_HEADER.size
        + metadata_len
        + recording._V2_CHUNK_HEADER.size
        + recording._RECORD_HEADER.size
    )
    data[payload_offset + 5] ^= 0x01
    path.write_bytes(data)
    with pytest.raises(RecordingError, match="checksum mismatch"):
        NdrxReader(path)


def test_ndrx1_remains_readable(tmp_path: Path) -> None:
    path = tmp_path / "legacy.ndrx"
    _write_v1(path, _messages(3))
    with NdrxReader(path) as reader:
        info = reader.info()
        values = [message.payload["value"] for _, message in reader.iter_messages()]
    assert info["format"] == "nodrix-recording/1"
    assert info["messages"] == 3
    assert info["finalized"] is True
    assert values == [0, 1, 2]


def test_repair_finalizes_recovered_recording(tmp_path: Path) -> None:
    source = tmp_path / "source.ndrx"
    output = tmp_path / "repaired.ndrx"
    writer = NdrxWriter(source, checkpoint_records=2, durable=False)
    for message in _messages(5):
        writer.write(message)
    writer.abort()

    info = repair_recording(source, output, checkpoint_records=2)
    assert info["messages"] == 5
    assert info["recovered"] is False
    assert info["finalized"] is True
