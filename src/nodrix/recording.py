from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import queue
import struct
import threading
import time
from typing import Any, BinaryIO, Iterable, Iterator

from .messages import Message
from .node import SinkNode, SourceNode
from .streams import StreamClient, StreamPublisher
from .wire import encode_message, read_message

_FILE_MAGIC = b"NDRF"
_FILE_VERSION_V1 = 1
_FILE_VERSION_V2 = 2
_FILE_HEADER = struct.Struct("!4sBI")
_RECORD_HEADER = struct.Struct("!QQ")  # receive monotonic ns, packet bytes

# Legacy NDRX1 structures.
_V1_INDEX_HEADER = struct.Struct("!4sQ")
_V1_FOOTER = struct.Struct("!4sQ")
_V1_INDEX_MAGIC = b"NDXI"
_V1_FOOTER_MAGIC = b"NDXF"

# NDRX2 consists of independently checksummed checkpoint chunks followed by
# an optional final summary. A recording remains readable without the summary.
_V2_CHUNK_MAGIC = b"NDC2"
_V2_CHUNK_HEADER = struct.Struct("!4sQQQ32s")
_V2_SUMMARY_MAGIC = b"NDS2"
_V2_SUMMARY_HEADER = struct.Struct("!4sQ")
_V2_END_MAGIC = b"NDF2"
_V2_END = struct.Struct("!4sQ32s")
_ZERO_DIGEST = b"\0" * 32

_MAX_METADATA_BYTES = 16 * 1024 * 1024
_MAX_INDEX_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_PACKET_BYTES = 1024 * 1024 * 1024
_DEFAULT_MAX_FILE_BYTES = 8 * 1024 * 1024 * 1024 * 1024
_DEFAULT_MAX_CHUNKS = 1_000_000
_DEFAULT_MAX_RECORDS = 100_000_000
_DEFAULT_MAX_STREAMS = 100_000


class RecordingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RecordIndexEntry:
    offset: int
    arrival_ns: int
    stream_id: str
    type: str
    sequence: int
    timestamp_ns: int
    packet_bytes: int


def _entry(raw: dict[str, Any]) -> RecordIndexEntry:
    try:
        return RecordIndexEntry(
            offset=int(raw["offset"]),
            arrival_ns=int(raw["arrival_ns"]),
            stream_id=str(raw.get("stream_id", "")),
            type=str(raw["type"]),
            sequence=int(raw["sequence"]),
            timestamp_ns=int(raw["timestamp_ns"]),
            packet_bytes=int(raw["packet_bytes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecordingError(f"Invalid NDRX index entry: {raw!r}") from exc


class _LimitedReader:
    def __init__(self, handle: BinaryIO, limit: int) -> None:
        self.handle = handle
        self.remaining = int(limit)
        self.position = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.remaining
        if size > self.remaining:
            return b""
        data = self.handle.read(size)
        self.remaining -= len(data)
        self.position += len(data)
        return data

    def tell(self) -> int:
        return self.position


class NdrxWriter:
    """Bounded-memory, crash-recoverable NDRX2 writer.

    Wire packet parts are streamed directly into independently checksummed
    chunks. Only the current checkpoint index is kept in memory.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        metadata: dict[str, Any] | None = None,
        checkpoint_records: int = 1024,
        durable: bool = True,
    ) -> None:
        if checkpoint_records <= 0:
            raise ValueError("checkpoint_records must be positive")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle: BinaryIO = self.path.open("wb", buffering=4 * 1024 * 1024)
        self.checkpoint_records = int(checkpoint_records)
        self.durable = bool(durable)
        self.metadata = {
            **(metadata or {}),
            "format": "nodrix-recording/2",
            "created_ns": time.time_ns(),
            "checkpoint_records": self.checkpoint_records,
            "checksum": "sha256",
        }
        encoded = json.dumps(
            self.metadata,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_METADATA_BYTES:
            raise RecordingError("NDRX metadata exceeds 16 MiB")
        self.handle.write(
            _FILE_HEADER.pack(_FILE_MAGIC, _FILE_VERSION_V2, len(encoded))
        )
        self.handle.write(encoded)
        self.data_offset = self.handle.tell()
        self.closed = False
        self.payload_bytes = 0
        self.messages = 0
        self.chunks = 0
        self.streams: dict[str, dict[str, Any]] = {}
        self._chunk_offset: int | None = None
        self._chunk_records_bytes = 0
        self._chunk_entries: list[RecordIndexEntry] = []
        self._chunk_hash: Any | None = None

    def _start_chunk(self) -> None:
        if self._chunk_offset is not None:
            return
        self._chunk_offset = self.handle.tell()
        self.handle.write(
            _V2_CHUNK_HEADER.pack(
                _V2_CHUNK_MAGIC,
                0,
                0,
                0,
                _ZERO_DIGEST,
            )
        )
        self._chunk_records_bytes = 0
        self._chunk_entries = []
        self._chunk_hash = hashlib.sha256()

    def write(self, message: Message, *, arrival_ns: int | None = None) -> None:
        if self.closed:
            raise RecordingError("Nodrix recording is closed")
        self._start_chunk()
        packet = encode_message(message)
        packet_bytes = packet.nbytes
        offset = self.handle.tell()
        arrival = time.perf_counter_ns() if arrival_ns is None else int(arrival_ns)
        record_header = _RECORD_HEADER.pack(arrival, packet_bytes)
        self.handle.write(record_header)
        assert self._chunk_hash is not None
        self._chunk_hash.update(record_header)
        for part in packet.parts():
            self.handle.write(part)
            self._chunk_hash.update(part)
        self._chunk_records_bytes += len(record_header) + packet_bytes
        self.payload_bytes += packet_bytes
        self.messages += 1
        entry = RecordIndexEntry(
            offset=offset,
            arrival_ns=arrival,
            stream_id=message.stream_id,
            type=message.type,
            sequence=message.sequence,
            timestamp_ns=message.timestamp_ns,
            packet_bytes=packet_bytes,
        )
        self._chunk_entries.append(entry)
        stream = self.streams.setdefault(
            message.stream_id,
            {"type": message.type, "messages": 0},
        )
        stream["messages"] += 1
        if len(self._chunk_entries) >= self.checkpoint_records:
            self.checkpoint()

    def checkpoint(self) -> None:
        if self.closed:
            raise RecordingError("Nodrix recording is closed")
        if self._chunk_offset is None:
            return
        index_data = {
            "entries": [asdict(entry) for entry in self._chunk_entries],
        }
        encoded = json.dumps(
            index_data,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_INDEX_BYTES:
            raise RecordingError("NDRX checkpoint index exceeds 64 MiB")
        assert self._chunk_hash is not None
        self.handle.write(encoded)
        self._chunk_hash.update(encoded)
        end_offset = self.handle.tell()
        digest = self._chunk_hash.digest()
        self.handle.seek(self._chunk_offset)
        self.handle.write(
            _V2_CHUNK_HEADER.pack(
                _V2_CHUNK_MAGIC,
                len(self._chunk_entries),
                self._chunk_records_bytes,
                len(encoded),
                digest,
            )
        )
        self.handle.seek(end_offset)
        self.handle.flush()
        if self.durable:
            os.fsync(self.handle.fileno())
        self.chunks += 1
        self._chunk_offset = None
        self._chunk_records_bytes = 0
        self._chunk_entries = []
        self._chunk_hash = None

    def close(self) -> None:
        if self.closed:
            return
        self.checkpoint()
        summary_offset = self.handle.tell()
        summary = {
            "format": "nodrix-recording/2",
            "messages": self.messages,
            "payload_bytes": self.payload_bytes,
            "chunks": self.chunks,
            "streams": self.streams,
        }
        encoded = json.dumps(
            summary,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.handle.write(_V2_SUMMARY_HEADER.pack(_V2_SUMMARY_MAGIC, len(encoded)))
        self.handle.write(encoded)
        self.handle.write(
            _V2_END.pack(
                _V2_END_MAGIC,
                summary_offset,
                hashlib.sha256(encoded).digest(),
            )
        )
        self.handle.flush()
        if self.durable:
            os.fsync(self.handle.fileno())
        self.handle.close()
        self.closed = True

    def abort(self) -> None:
        """Close without finalizing the active chunk, simulating interruption."""
        if self.closed:
            return
        self.handle.flush()
        if self.durable:
            os.fsync(self.handle.fileno())
        self.handle.close()
        self.closed = True

    def __enter__(self) -> NdrxWriter:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class NdrxReader:
    def __init__(
        self,
        path: str | Path,
        *,
        recover: bool = True,
        max_packet_bytes: int = _DEFAULT_MAX_PACKET_BYTES,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
        max_chunks: int = _DEFAULT_MAX_CHUNKS,
        max_records: int = _DEFAULT_MAX_RECORDS,
        max_streams: int = _DEFAULT_MAX_STREAMS,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.max_packet_bytes = int(max_packet_bytes)
        self.file_size = self.path.stat().st_size
        self.max_file_bytes = int(max_file_bytes)
        self.max_chunks = int(max_chunks)
        self.max_records = int(max_records)
        self.max_streams = int(max_streams)
        if min(
            self.max_packet_bytes,
            self.max_file_bytes,
            self.max_chunks,
            self.max_records,
            self.max_streams,
        ) <= 0:
            raise ValueError("NDRX reader limits must be positive")
        if self.file_size > self.max_file_bytes:
            raise RecordingError(
                f"NDRX file exceeds configured limit: {self.file_size}"
            )
        self.handle: BinaryIO = self.path.open("rb")
        header = self.handle.read(_FILE_HEADER.size)
        if len(header) != _FILE_HEADER.size:
            raise RecordingError("Truncated Nodrix recording header")
        magic, self.version, metadata_len = _FILE_HEADER.unpack(header)
        if magic != _FILE_MAGIC or self.version not in {
            _FILE_VERSION_V1,
            _FILE_VERSION_V2,
        }:
            raise RecordingError("Unsupported Nodrix recording format")
        if metadata_len > _MAX_METADATA_BYTES:
            raise RecordingError("NDRX metadata exceeds 16 MiB")
        metadata_bytes = self.handle.read(metadata_len)
        if len(metadata_bytes) != metadata_len:
            raise RecordingError("Truncated Nodrix recording metadata")
        try:
            self.metadata = json.loads(metadata_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordingError("Invalid Nodrix recording metadata") from exc
        if not isinstance(self.metadata, dict):
            raise RecordingError("Nodrix recording metadata must be a mapping")
        self.data_offset = self.handle.tell()
        self.recovered = False
        self.finalized = False
        if self.version == _FILE_VERSION_V1:
            self._load_v1()
        else:
            self.index = self._scan_v2(recover=recover)

    def _load_v1(self) -> None:
        if self.file_size < self.data_offset + _V1_FOOTER.size:
            raise RecordingError("NDRX1 recording footer is missing")
        self.handle.seek(-_V1_FOOTER.size, 2)
        footer = self.handle.read(_V1_FOOTER.size)
        footer_magic, self.index_offset = _V1_FOOTER.unpack(footer)
        if footer_magic != _V1_FOOTER_MAGIC:
            raise RecordingError("NDRX1 recording index footer is missing")
        if not self.data_offset <= self.index_offset < self.file_size:
            raise RecordingError("Invalid NDRX1 index offset")
        self.handle.seek(self.index_offset)
        raw = self.handle.read(_V1_INDEX_HEADER.size)
        if len(raw) != _V1_INDEX_HEADER.size:
            raise RecordingError("Truncated NDRX1 index")
        index_magic, index_len = _V1_INDEX_HEADER.unpack(raw)
        if index_magic != _V1_INDEX_MAGIC or index_len > _MAX_INDEX_BYTES:
            raise RecordingError("Invalid NDRX1 recording index")
        encoded = self.handle.read(index_len)
        if len(encoded) != index_len:
            raise RecordingError("Truncated NDRX1 recording index")
        try:
            self.index = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordingError("Invalid NDRX1 recording index") from exc
        if not isinstance(self.index, dict):
            raise RecordingError("NDRX1 recording index must be a mapping")
        entries = self.index.get("entries", [])
        if not isinstance(entries, list) or len(entries) > self.max_records:
            raise RecordingError("NDRX1 record-count limit exceeded")
        self.index["format"] = "nodrix-recording/1"
        self.index["chunks"] = 0
        self.index["recovered"] = False
        self.index["finalized"] = True
        self.finalized = True

    def _hash_region(self, offset: int, length: int) -> bytes:
        self.handle.seek(offset)
        digest = hashlib.sha256()
        remaining = int(length)
        while remaining:
            data = self.handle.read(min(remaining, 1024 * 1024))
            if not data:
                raise RecordingError("Truncated NDRX2 chunk")
            digest.update(data)
            remaining -= len(data)
        return digest.digest()

    def _read_chunk(
        self,
        position: int,
    ) -> tuple[list[RecordIndexEntry] | None, int, int]:
        self.handle.seek(position)
        raw = self.handle.read(_V2_CHUNK_HEADER.size)
        if len(raw) != _V2_CHUNK_HEADER.size:
            raise RecordingError("Truncated NDRX2 chunk header")
        magic, count, records_bytes, index_bytes, checksum = (
            _V2_CHUNK_HEADER.unpack(raw)
        )
        if magic != _V2_CHUNK_MAGIC:
            raise RecordingError("Invalid NDRX2 chunk")
        data_offset = position + _V2_CHUNK_HEADER.size
        if (
            count == 0
            and records_bytes == 0
            and index_bytes == 0
            and checksum == _ZERO_DIGEST
        ):
            return None, data_offset, self.file_size
        if (
            count <= 0
            or count > self.max_records
            or index_bytes <= 0
            or index_bytes > _MAX_INDEX_BYTES
        ):
            raise RecordingError("Invalid NDRX2 chunk lengths")
        end = data_offset + records_bytes + index_bytes
        if end > self.file_size:
            raise RecordingError("Truncated NDRX2 checkpoint")
        if self._hash_region(data_offset, records_bytes + index_bytes) != checksum:
            raise RecordingError("NDRX2 chunk checksum mismatch")
        self.handle.seek(data_offset + records_bytes)
        encoded = self.handle.read(index_bytes)
        try:
            raw_entries = json.loads(encoded.decode("utf-8")).get("entries", [])
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise RecordingError("Invalid NDRX2 checkpoint index") from exc
        entries = [_entry(item) for item in raw_entries]
        if len(entries) != count:
            raise RecordingError("NDRX2 chunk record count mismatch")
        records_end = data_offset + records_bytes
        expected_offset = data_offset
        for item in entries:
            if (
                item.offset != expected_offset
                or item.packet_bytes <= 0
                or item.packet_bytes > self.max_packet_bytes
                or item.offset + _RECORD_HEADER.size + item.packet_bytes
                > records_end
            ):
                raise RecordingError(
                    "NDRX2 index does not exactly cover its chunk"
                )
            self.handle.seek(item.offset)
            record_header = self.handle.read(_RECORD_HEADER.size)
            if len(record_header) != _RECORD_HEADER.size:
                raise RecordingError("Truncated NDRX2 record header")
            _, packet_bytes = _RECORD_HEADER.unpack(record_header)
            if packet_bytes != item.packet_bytes:
                raise RecordingError("NDRX2 index packet size mismatch")
            expected_offset += _RECORD_HEADER.size + item.packet_bytes
        if expected_offset != records_end:
            raise RecordingError(
                "NDRX2 checkpoint contains unindexed record bytes"
            )
        return entries, data_offset, end

    def _read_packet(self, entry: RecordIndexEntry) -> tuple[int, Message]:
        if entry.packet_bytes <= 0 or entry.packet_bytes > self.max_packet_bytes:
            raise RecordingError(
                f"NDRX packet exceeds configured limit: {entry.packet_bytes}"
            )
        self.handle.seek(entry.offset)
        raw = self.handle.read(_RECORD_HEADER.size)
        if len(raw) != _RECORD_HEADER.size:
            raise RecordingError("Truncated Nodrix record")
        arrival_ns, packet_bytes = _RECORD_HEADER.unpack(raw)
        if packet_bytes != entry.packet_bytes:
            raise RecordingError("NDRX index packet size mismatch")
        limited = _LimitedReader(self.handle, packet_bytes)
        try:
            message = read_message(limited)
        except Exception as exc:
            raise RecordingError("Invalid Nodrix wire packet in recording") from exc
        if limited.tell() != packet_bytes:
            raise RecordingError("Nodrix recording packet length mismatch")
        return arrival_ns, message

    def _recover_tail(
        self,
        start: int,
        *,
        remaining_records: int | None = None,
    ) -> list[RecordIndexEntry]:
        entries: list[RecordIndexEntry] = []
        position = start
        limit = (
            self.max_records
            if remaining_records is None
            else min(self.max_records, remaining_records)
        )
        while position + _RECORD_HEADER.size <= self.file_size:
            if len(entries) >= limit:
                raise RecordingError("NDRX2 record-count limit exceeded")
            self.handle.seek(position)
            raw = self.handle.read(_RECORD_HEADER.size)
            if len(raw) != _RECORD_HEADER.size:
                break
            arrival_ns, packet_bytes = _RECORD_HEADER.unpack(raw)
            if (
                packet_bytes <= 0
                or packet_bytes > self.max_packet_bytes
                or position + _RECORD_HEADER.size + packet_bytes > self.file_size
            ):
                break
            limited = _LimitedReader(self.handle, packet_bytes)
            try:
                message = read_message(limited)
            except Exception:
                break
            if limited.tell() != packet_bytes:
                break
            entries.append(
                RecordIndexEntry(
                    offset=position,
                    arrival_ns=arrival_ns,
                    stream_id=message.stream_id,
                    type=message.type,
                    sequence=message.sequence,
                    timestamp_ns=message.timestamp_ns,
                    packet_bytes=packet_bytes,
                )
            )
            position += _RECORD_HEADER.size + packet_bytes
        return entries

    @staticmethod
    def _summarize(
        entries: Iterable[RecordIndexEntry],
        streams: dict[str, dict[str, Any]],
    ) -> tuple[int, int]:
        messages = 0
        payload_bytes = 0
        for entry in entries:
            messages += 1
            payload_bytes += entry.packet_bytes
            stream = streams.setdefault(
                entry.stream_id,
                {"type": entry.type, "messages": 0},
            )
            stream["messages"] += 1
        return messages, payload_bytes

    def _read_summary(self, position: int) -> dict[str, Any]:
        self.handle.seek(position)
        raw = self.handle.read(_V2_SUMMARY_HEADER.size)
        if len(raw) != _V2_SUMMARY_HEADER.size:
            raise RecordingError("Truncated NDRX2 summary header")
        magic, length = _V2_SUMMARY_HEADER.unpack(raw)
        if magic != _V2_SUMMARY_MAGIC or length > _MAX_INDEX_BYTES:
            raise RecordingError("Invalid NDRX2 summary")
        encoded = self.handle.read(length)
        end = self.handle.read(_V2_END.size)
        if len(encoded) != length or len(end) != _V2_END.size:
            raise RecordingError("Truncated NDRX2 summary")
        end_magic, summary_offset, checksum = _V2_END.unpack(end)
        if (
            end_magic != _V2_END_MAGIC
            or summary_offset != position
            or hashlib.sha256(encoded).digest() != checksum
        ):
            raise RecordingError("Invalid NDRX2 final checksum")
        if self.handle.tell() != self.file_size:
            raise RecordingError("NDRX2 has trailing data after final summary")
        try:
            summary = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordingError("Invalid NDRX2 summary JSON") from exc
        if not isinstance(summary, dict):
            raise RecordingError("NDRX2 summary must be a mapping")
        return summary

    def _scan_v2(self, *, recover: bool) -> dict[str, Any]:
        position = self.data_offset
        messages = 0
        payload_bytes = 0
        chunks = 0
        streams: dict[str, dict[str, Any]] = {}
        while position < self.file_size:
            self.handle.seek(position)
            magic = self.handle.read(4)
            if magic == _V2_CHUNK_MAGIC:
                entries, tail_start, next_position = self._read_chunk(position)
                if entries is None:
                    if not recover:
                        raise RecordingError("NDRX2 active chunk was not checkpointed")
                    entries = self._recover_tail(
                        tail_start,
                        remaining_records=self.max_records - messages,
                    )
                    added_messages, added_bytes = self._summarize(entries, streams)
                    messages += added_messages
                    payload_bytes += added_bytes
                    self.recovered = True
                    break
                added_messages, added_bytes = self._summarize(entries, streams)
                messages += added_messages
                payload_bytes += added_bytes
                chunks += 1
                if chunks > self.max_chunks:
                    raise RecordingError("NDRX2 chunk-count limit exceeded")
                if messages > self.max_records:
                    raise RecordingError("NDRX2 record-count limit exceeded")
                if len(streams) > self.max_streams:
                    raise RecordingError("NDRX2 stream-count limit exceeded")
                position = next_position
                continue
            if magic == _V2_SUMMARY_MAGIC:
                summary = self._read_summary(position)
                if (
                    int(summary.get("messages", -1)) != messages
                    or int(summary.get("payload_bytes", -1)) != payload_bytes
                    or int(summary.get("chunks", -1)) != chunks
                ):
                    raise RecordingError("NDRX2 final summary does not match chunks")
                self.finalized = True
                break
            if not magic:
                self.recovered = True
                break
            raise RecordingError(f"Unknown NDRX2 section magic: {magic!r}")
        if not self.finalized:
            if not recover:
                raise RecordingError("NDRX2 final summary is missing")
            self.recovered = True
        return {
            "format": "nodrix-recording/2",
            "messages": messages,
            "payload_bytes": payload_bytes,
            "chunks": chunks,
            "streams": streams,
            "recovered": self.recovered,
            "finalized": self.finalized,
        }

    def _iter_v1_entries(self) -> Iterator[RecordIndexEntry]:
        for raw in self.index.get("entries", []):
            yield _entry(raw)

    def _iter_v2_entries(self) -> Iterator[RecordIndexEntry]:
        position = self.data_offset
        chunks = 0
        records = 0
        while position < self.file_size:
            self.handle.seek(position)
            magic = self.handle.read(4)
            if magic == _V2_CHUNK_MAGIC:
                entries, tail_start, next_position = self._read_chunk(position)
                if entries is None:
                    yield from self._recover_tail(
                        tail_start,
                        remaining_records=self.max_records - records,
                    )
                    return
                chunks += 1
                records += len(entries)
                if chunks > self.max_chunks:
                    raise RecordingError("NDRX2 chunk-count limit exceeded")
                if records > self.max_records:
                    raise RecordingError("NDRX2 record-count limit exceeded")
                yield from entries
                position = next_position
                continue
            return

    def iter_messages(
        self,
        *,
        streams: set[str] | None = None,
        start: int = 0,
        limit: int = 0,
    ) -> Iterator[tuple[int, Message]]:
        if start < 0 or limit < 0:
            raise ValueError("start and limit must be non-negative")
        emitted = 0
        entries = (
            self._iter_v1_entries()
            if self.version == _FILE_VERSION_V1
            else self._iter_v2_entries()
        )
        for position, entry in enumerate(entries):
            if position < start:
                continue
            if streams and entry.stream_id not in streams:
                continue
            yield self._read_packet(entry)
            emitted += 1
            if limit and emitted >= limit:
                return

    def info(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "metadata": self.metadata,
            **{key: value for key, value in self.index.items() if key != "entries"},
            "size_bytes": self.path.stat().st_size,
        }

    def close(self) -> None:
        self.handle.close()

    def __enter__(self) -> NdrxReader:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def repair_recording(
    source: str | Path,
    output: str | Path,
    *,
    checkpoint_records: int = 1024,
) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path == output_path:
        raise ValueError("repair output must differ from source")
    with NdrxReader(source_path, recover=True) as reader:
        metadata = {
            **reader.metadata,
            "repaired_from": str(source_path),
            "source_format": reader.index.get("format"),
        }
        with NdrxWriter(
            output_path,
            metadata=metadata,
            checkpoint_records=checkpoint_records,
        ) as writer:
            for arrival_ns, message in reader.iter_messages():
                writer.write(message, arrival_ns=arrival_ns)
    with NdrxReader(output_path) as repaired:
        return repaired.info()


def record_streams(
    targets: Iterable[str],
    output: str | Path,
    *,
    duration: float = 0.0,
    count: int = 0,
    discovery_timeout: float = 3.0,
) -> dict[str, Any]:
    target_list = list(targets)
    if not target_list:
        raise ValueError("At least one stream is required")
    clients = [
        StreamClient(
            target,
            discovery_timeout=discovery_timeout,
            capacity=64,
            policy="block",
        )
        for target in target_list
    ]
    inbox: queue.Queue[tuple[int, Message] | BaseException] = queue.Queue(
        maxsize=1024
    )
    stop = threading.Event()
    threads: list[threading.Thread] = []

    def reader_loop(client: StreamClient) -> None:
        try:
            client.connect()
            while not stop.is_set():
                inbox.put((time.perf_counter_ns(), client.receive()))
        except BaseException as exc:
            if not stop.is_set():
                inbox.put(exc)

    for client in clients:
        thread = threading.Thread(
            target=reader_loop,
            args=(client,),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    started = time.monotonic()
    written = 0
    metadata = {"requested_streams": target_list}
    try:
        with NdrxWriter(output, metadata=metadata) as writer:
            while True:
                if duration and time.monotonic() - started >= duration:
                    break
                if count and written >= count:
                    break
                try:
                    item = inbox.get(timeout=0.2)
                except queue.Empty:
                    continue
                if isinstance(item, BaseException):
                    raise item
                arrival, message = item
                writer.write(message, arrival_ns=arrival)
                written += 1
    finally:
        stop.set()
        for client in clients:
            client.close()
        for thread in threads:
            thread.join(timeout=1.0)
    with NdrxReader(output) as reader:
        return reader.info()


def play_recording(
    path: str | Path,
    *,
    speed: float = 1.0,
    as_fast_as_possible: bool = False,
    stream_prefix: str = "",
    loop: bool = False,
    startup_delay: float = 1.0,
    linger: float = 0.25,
    start: int = 0,
    count: int = 0,
    fixed_fps: float = 0.0,
) -> dict[str, Any]:
    if speed <= 0 and not as_fast_as_possible:
        raise ValueError("speed must be positive")
    if start < 0 or count < 0 or fixed_fps < 0:
        raise ValueError("start, count, and fixed_fps must be non-negative")
    total = 0
    with NdrxReader(path) as reader:
        stream_specs = reader.index.get("streams", {})
        exports = []
        for name, spec in stream_specs.items():
            export_name = f"{stream_prefix}{name}" if stream_prefix else name
            exports.append(
                {
                    "name": export_name,
                    "source": name,
                    "type": spec["type"],
                    "capacity": 8,
                    "policy": "block",
                }
            )
        publisher = StreamPublisher(Path(path).stem, exports)
        publisher.start()
        if startup_delay > 0:
            time.sleep(startup_delay)
        try:
            while True:
                previous_arrival: int | None = None
                for arrival, message in reader.iter_messages(
                    start=start,
                    limit=count,
                ):
                    if previous_arrival is not None and not as_fast_as_possible:
                        delay = (
                            1.0 / fixed_fps
                            if fixed_fps > 0
                            else (arrival - previous_arrival) / 1e9 / speed
                        )
                        if delay > 0:
                            time.sleep(delay)
                    previous_arrival = arrival
                    publisher.publish(message.stream_id, message)
                    total += 1
                if not loop:
                    break
            if linger > 0:
                time.sleep(linger)
        finally:
            report = publisher.report()
            publisher.close()
    return {"messages": total, "streams": list(stream_specs), "publisher": report}


class NdrxWriterNode(SinkNode):
    input_types = {"input": "core.any"}

    def open(self, context) -> None:
        super().open(context)
        path = Path(str(self.parameters.get("path", "recording.ndrx")))
        if not path.is_absolute():
            path = context.run_dir / path
        self.writer = NdrxWriter(
            path,
            metadata={"pipeline": context.name},
            checkpoint_records=int(
                self.parameters.get("checkpoint_records", 1024)
            ),
            durable=bool(self.parameters.get("durable", True)),
        )

    def process(self, inputs: dict[str, Message]) -> None:
        self.writer.write(inputs["input"])

    def close(self) -> None:
        self.writer.close()


class NdrxSourceNode(SourceNode):
    output_types = {"output": "core.any"}

    def open(self, context) -> None:
        super().open(context)
        path = Path(str(self.parameters["path"]))
        if not path.is_absolute():
            path = context.project_dir / path
        self.reader = NdrxReader(path)
        self.speed = float(self.parameters.get("speed", 1.0))
        self.fast = bool(self.parameters.get("as_fast_as_possible", False))
        self.limit = int(self.parameters.get("max_messages", 0))
        self.start = int(self.parameters.get("start", 0))
        self.fixed_fps = float(self.parameters.get("fixed_fps", 0.0))
        configured = self.parameters.get("streams") or []
        self.streams = set(configured) if configured else None

    def produce(self):
        previous: int | None = None
        for arrival, message in self.reader.iter_messages(
            streams=self.streams,
            start=self.start,
            limit=self.limit,
        ):
            if previous is not None and not self.fast:
                delay = (
                    1.0 / self.fixed_fps
                    if self.fixed_fps > 0
                    else (arrival - previous) / 1e9 / self.speed
                )
                if delay > 0:
                    time.sleep(delay)
            previous = arrival
            yield {"output": message}

    def close(self) -> None:
        self.reader.close()
