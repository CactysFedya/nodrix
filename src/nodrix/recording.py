from __future__ import annotations

from dataclasses import dataclass
import json
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
_FILE_VERSION = 1
_FILE_HEADER = struct.Struct("!4sBI")
_RECORD_HEADER = struct.Struct("!QQ")  # receive monotonic ns, packet bytes
_INDEX_HEADER = struct.Struct("!4sQ")
_FOOTER = struct.Struct("!4sQ")
_INDEX_MAGIC = b"NDXI"
_FOOTER_MAGIC = b"NDXF"


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


class NdrxWriter:
    """Append-only universal Nodrix recording writer.

    Wire packet parts are written directly to the file. Large frame/tensor
    payloads are not concatenated into another Python ``bytes`` object.
    """

    def __init__(self, path: str | Path, *, metadata: dict[str, Any] | None = None) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle: BinaryIO = self.path.open("wb", buffering=4 * 1024 * 1024)
        self.metadata = {
            "format": "nodrix-recording/1",
            "created_ns": time.time_ns(),
            **(metadata or {}),
        }
        encoded = json.dumps(self.metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.handle.write(_FILE_HEADER.pack(_FILE_MAGIC, _FILE_VERSION, len(encoded)))
        self.handle.write(encoded)
        self.data_offset = self.handle.tell()
        self.index: list[RecordIndexEntry] = []
        self.closed = False
        self.payload_bytes = 0

    def write(self, message: Message, *, arrival_ns: int | None = None) -> None:
        if self.closed:
            raise RecordingError("Nodrix recording is closed")
        packet = encode_message(message)
        packet_bytes = packet.nbytes
        offset = self.handle.tell()
        arrival = time.perf_counter_ns() if arrival_ns is None else int(arrival_ns)
        self.handle.write(_RECORD_HEADER.pack(arrival, packet_bytes))
        for part in packet.parts():
            self.handle.write(part)
        self.payload_bytes += packet_bytes
        self.index.append(RecordIndexEntry(
            offset=offset,
            arrival_ns=arrival,
            stream_id=message.stream_id,
            type=message.type,
            sequence=message.sequence,
            timestamp_ns=message.timestamp_ns,
            packet_bytes=packet_bytes,
        ))

    def close(self) -> None:
        if self.closed:
            return
        index_offset = self.handle.tell()
        streams: dict[str, dict[str, Any]] = {}
        for entry in self.index:
            value = streams.setdefault(entry.stream_id, {"type": entry.type, "messages": 0})
            value["messages"] += 1
        index_data = {
            "messages": len(self.index),
            "payload_bytes": self.payload_bytes,
            "streams": streams,
            "entries": [entry.__dict__ if hasattr(entry, "__dict__") else {
                "offset": entry.offset,
                "arrival_ns": entry.arrival_ns,
                "stream_id": entry.stream_id,
                "type": entry.type,
                "sequence": entry.sequence,
                "timestamp_ns": entry.timestamp_ns,
                "packet_bytes": entry.packet_bytes,
            } for entry in self.index],
        }
        encoded = json.dumps(index_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.handle.write(_INDEX_HEADER.pack(_INDEX_MAGIC, len(encoded)))
        self.handle.write(encoded)
        self.handle.write(_FOOTER.pack(_FOOTER_MAGIC, index_offset))
        self.handle.flush()
        self.handle.close()
        self.closed = True

    def __enter__(self) -> "NdrxWriter":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class NdrxReader:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.handle: BinaryIO = self.path.open("rb")
        header = self.handle.read(_FILE_HEADER.size)
        if len(header) != _FILE_HEADER.size:
            raise RecordingError("Truncated Nodrix recording header")
        magic, version, metadata_len = _FILE_HEADER.unpack(header)
        if magic != _FILE_MAGIC or version != _FILE_VERSION:
            raise RecordingError("Unsupported Nodrix recording format")
        self.metadata = json.loads(self.handle.read(metadata_len).decode("utf-8"))
        self.data_offset = self.handle.tell()
        self.handle.seek(-_FOOTER.size, 2)
        footer = self.handle.read(_FOOTER.size)
        footer_magic, self.index_offset = _FOOTER.unpack(footer)
        if footer_magic != _FOOTER_MAGIC:
            raise RecordingError("Nodrix recording index footer is missing")
        self.handle.seek(self.index_offset)
        index_magic, index_len = _INDEX_HEADER.unpack(self.handle.read(_INDEX_HEADER.size))
        if index_magic != _INDEX_MAGIC:
            raise RecordingError("Invalid Nodrix recording index")
        self.index = json.loads(self.handle.read(index_len).decode("utf-8"))

    def iter_messages(
        self,
        *,
        streams: set[str] | None = None,
        start: int = 0,
        limit: int = 0,
    ) -> Iterator[tuple[int, Message]]:
        emitted = 0
        entries = self.index.get("entries", [])
        for entry in entries[start:]:
            if streams and entry["stream_id"] not in streams:
                continue
            self.handle.seek(int(entry["offset"]))
            record_header = self.handle.read(_RECORD_HEADER.size)
            if len(record_header) != _RECORD_HEADER.size:
                raise RecordingError("Truncated Nodrix record")
            arrival_ns, packet_bytes = _RECORD_HEADER.unpack(record_header)
            packet_start = self.handle.tell()
            message = read_message(self.handle)
            if self.handle.tell() - packet_start != packet_bytes:
                raise RecordingError("Nodrix recording packet length mismatch")
            yield arrival_ns, message
            emitted += 1
            if limit and emitted >= limit:
                return

    def info(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "metadata": self.metadata,
            **self.index,
            "size_bytes": self.path.stat().st_size,
        }

    def close(self) -> None:
        self.handle.close()

    def __enter__(self) -> "NdrxReader":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


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
    clients = [StreamClient(target, discovery_timeout=discovery_timeout, capacity=64, policy="block") for target in target_list]
    inbox: queue.Queue[tuple[int, Message] | BaseException] = queue.Queue(maxsize=1024)
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
        thread = threading.Thread(target=reader_loop, args=(client,), daemon=True)
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
) -> dict[str, Any]:
    if speed <= 0 and not as_fast_as_possible:
        raise ValueError("speed must be positive")
    total = 0
    with NdrxReader(path) as reader:
        stream_specs = reader.index.get("streams", {})
        exports = []
        for name, spec in stream_specs.items():
            export_name = f"{stream_prefix}{name}" if stream_prefix else name
            exports.append({"name": export_name, "source": name, "type": spec["type"], "capacity": 8, "policy": "block"})
        publisher = StreamPublisher(Path(path).stem, exports)
        publisher.start()
        if startup_delay > 0:
            time.sleep(startup_delay)
        try:
            while True:
                previous_arrival: int | None = None
                for arrival, message in reader.iter_messages():
                    if previous_arrival is not None and not as_fast_as_possible:
                        delay = (arrival - previous_arrival) / 1e9 / speed
                        if delay > 0:
                            time.sleep(delay)
                    previous_arrival = arrival
                    source = message.stream_id
                    publisher.publish(source, message)
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
        self.writer = NdrxWriter(path, metadata={"pipeline": context.name})

    def process(self, inputs: dict[str, Message]) -> None:
        self.writer.write(inputs["input"])
        return None

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
        configured = self.parameters.get("streams") or []
        self.streams = set(configured) if configured else None

    def produce(self):
        previous: int | None = None
        for arrival, message in self.reader.iter_messages(streams=self.streams, limit=self.limit):
            if previous is not None and not self.fast:
                delay = (arrival - previous) / 1e9 / self.speed
                if delay > 0:
                    time.sleep(delay)
            previous = arrival
            yield {"output": message}

    def close(self) -> None:
        self.reader.close()
