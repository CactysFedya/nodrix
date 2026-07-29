from __future__ import annotations

from dataclasses import dataclass, field
import json
import hmac
import ipaddress
import os
import queue
import socket
import struct
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

from .discovery import DiscoveryAdvertiser, resolve_stream
from .messages import Message
from .wire import WirePacket, encode_message, recv_message, send_packet

_HANDSHAKE_LENGTH = struct.Struct("!I")

try:
    from ._native_queue import BoundedQueue as _NativeBoundedQueue
except Exception:  # pragma: no cover
    _NativeBoundedQueue = None


class _PacketQueue:
    def __init__(self, capacity: int, policy: str) -> None:
        self._native = _NativeBoundedQueue(capacity, policy) if _NativeBoundedQueue is not None else None
        self._queue: queue.Queue[Any] | None = None if self._native is not None else queue.Queue(capacity)
        self.policy = policy
        self.closed = False
        self.dropped = 0

    def put(self, item: Any) -> bool:
        if self.closed:
            return False
        if self._native is not None:
            return bool(self._native.put(item))
        assert self._queue is not None
        if self.policy == "block":
            self._queue.put(item)
            return True
        if self.policy == "drop_newest":
            try:
                self._queue.put_nowait(item)
                return True
            except queue.Full:
                self.dropped += 1
                return False
        if self.policy == "latest":
            while True:
                try:
                    self._queue.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    break
        elif self._queue.full():
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except queue.Empty:
                pass
        self._queue.put_nowait(item)
        return True

    def get(self) -> Any:
        if self._native is not None:
            return self._native.get()
        assert self._queue is not None
        while not self.closed:
            try:
                return self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
        return None

    def stats(self) -> dict[str, int]:
        if self._native is not None:
            return {key: int(value) for key, value in dict(self._native.stats()).items()}
        assert self._queue is not None
        return {"depth": self._queue.qsize(), "dropped": self.dropped}

    def close(self) -> None:
        self.closed = True
        if self._native is not None:
            self._native.close()


@dataclass(slots=True)
class _Client:
    socket: socket.socket
    address: tuple[str, int]
    stream: str
    queue: _PacketQueue
    thread: threading.Thread | None = None
    sent_messages: int = 0
    sent_bytes: int = 0
    errors: int = 0


@dataclass(slots=True)
class StreamDefinition:
    name: str
    type: str
    capacity: int = 2
    policy: str = "latest"
    access_mode: str = "open"
    token: str | None = None
    allow_ips: tuple[str, ...] = ()
    clients: list[_Client] = field(default_factory=list)
    incoming: _PacketQueue | None = None
    thread: threading.Thread | None = None
    published: int = 0
    encoded_messages: int = 0
    encoded_bytes: int = 0
    total_sent_messages: int = 0
    total_sent_bytes: int = 0
    total_client_errors: int = 0


class StreamServer:
    """Direct publisher-to-subscriber data plane for named streams."""

    def __init__(
        self, host: str = "127.0.0.1", port: int = 0, *,
        max_handshake_bytes: int = 64 * 1024, max_message_bytes: int = 256 * 1024 * 1024,
        handshake_timeout: float = 5.0, max_handshakes: int = 32, max_clients: int = 128,
    ) -> None:
        self.host = host
        self.requested_port = int(port)
        self.max_handshake_bytes = int(max_handshake_bytes)
        self.max_message_bytes = int(max_message_bytes)
        self.handshake_timeout = max(0.1, float(handshake_timeout))
        self.max_clients = max(1, int(max_clients))
        self._handshake_slots = threading.BoundedSemaphore(max(1, int(max_handshakes)))
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._streams: dict[str, StreamDefinition] = {}

    @property
    def port(self) -> int:
        if self._socket is None:
            return self.requested_port
        return int(self._socket.getsockname()[1])

    def register(
        self, name: str, type_name: str, *, capacity: int = 2, policy: str = "latest",
        access_mode: str = "open", token: str | None = None, allow_ips: list[str] | tuple[str, ...] = (),
    ) -> None:
        if not name.startswith("/"):
            raise ValueError(f"Stream name must start with '/': {name!r}")
        with self._lock:
            if name in self._streams:
                raise ValueError(f"Duplicate Nodrix stream: {name}")
            self._streams[name] = StreamDefinition(
                name, type_name, capacity, policy, access_mode, token, tuple(allow_ips),
                incoming=_PacketQueue(capacity, policy),
            )

    def definitions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": item.name,
                    "type": item.type,
                    "codec": "nodrix-wire/1",
                    "metadata": {
                        "queue_policy": item.policy, "queue_capacity": item.capacity,
                        "access": item.access_mode,
                    },
                }
                for item in self._streams.values()
            ]

    def start(self) -> None:
        if self._thread is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.bind((self.host, self.requested_port))
        sock.listen(32)
        sock.settimeout(0.2)
        self._socket = sock
        self._thread = threading.Thread(target=self._accept_loop, name="nodrix-stream-server", daemon=True)
        self._thread.start()
        with self._lock:
            definitions = tuple(self._streams.values())
        for definition in definitions:
            definition.thread = threading.Thread(
                target=self._broadcast_loop,
                args=(definition,),
                name=f"nodrix-broadcast:{definition.name}",
                daemon=True,
            )
            definition.thread.start()


    def _broadcast_loop(self, definition: StreamDefinition) -> None:
        assert definition.incoming is not None
        while not self._stop.is_set():
            message = definition.incoming.get()
            if message is None:
                break
            with self._lock:
                clients = tuple(definition.clients)
            if not clients:
                continue
            try:
                packet = encode_message(message.with_updates(stream_id=definition.name))
                if packet.nbytes > self.max_message_bytes:
                    raise ValueError(
                        f"stream message exceeds max_message_bytes: {packet.nbytes} > {self.max_message_bytes}"
                    )
            except Exception:
                definition.total_client_errors += 1
                continue
            definition.encoded_messages += 1
            definition.encoded_bytes += packet.nbytes
            for client in clients:
                client.queue.put(packet)

    def _accept_loop(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                client_socket, address = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if not self._handshake_slots.acquire(blocking=False):
                client_socket.close()
                continue
            threading.Thread(
                target=self._handshake_client,
                args=(client_socket, address),
                name=f"nodrix-handshake:{address[0]}",
                daemon=True,
            ).start()

    @staticmethod
    def _receive_exact(sock: socket.socket, size: int) -> bytes:
        data = bytearray(size)
        view = memoryview(data)
        offset = 0
        while offset < size:
            count = sock.recv_into(view[offset:])
            if count <= 0:
                raise EOFError("incomplete Nodrix handshake")
            offset += count
        return bytes(data)

    @classmethod
    def _receive_json(cls, sock: socket.socket, max_handshake_bytes: int = 64 * 1024) -> dict[str, Any]:
        raw_length = cls._receive_exact(sock, _HANDSHAKE_LENGTH.size)
        length = _HANDSHAKE_LENGTH.unpack(raw_length)[0]
        if length <= 0 or length > int(max_handshake_bytes):
            raise ValueError(f"invalid Nodrix handshake length: {length}")
        data = bytearray(length)
        view = memoryview(data)
        offset = 0
        while offset < length:
            count = sock.recv_into(view[offset:])
            if count <= 0:
                raise EOFError("incomplete Nodrix handshake")
            offset += count
        return json.loads(bytes(data).decode("utf-8"))

    @staticmethod
    def _send_json(sock: socket.socket, value: dict[str, Any]) -> None:
        data = json.dumps(value, separators=(",", ":")).encode("utf-8")
        sock.sendall(_HANDSHAKE_LENGTH.pack(len(data)) + data)

    def _handshake_client(self, sock: socket.socket, address: tuple[str, int]) -> None:
        try:
            self._configure_client(sock, address)
        finally:
            self._handshake_slots.release()

    def _configure_client(self, sock: socket.socket, address: tuple[str, int]) -> None:
        try:
            sock.settimeout(self.handshake_timeout)
            request = self._receive_json(sock, self.max_handshake_bytes)
            if request.get("protocol") != "nodrix-stream/1" or request.get("action") != "subscribe":
                raise ValueError("unsupported handshake")
            name = str(request.get("stream", ""))
            with self._lock:
                definition = self._streams.get(name)
                if definition is None:
                    self._send_json(sock, {"ok": False, "error": f"unknown stream: {name}"})
                    sock.close()
                    return
                if definition.allow_ips:
                    client_ip = ipaddress.ip_address(address[0])
                    allowed = False
                    for item in definition.allow_ips:
                        try:
                            if client_ip in ipaddress.ip_network(item, strict=False):
                                allowed = True
                                break
                        except ValueError:
                            if address[0] == item:
                                allowed = True
                                break
                    if not allowed:
                        self._send_json(sock, {"ok": False, "error": "client IP is not allowed"})
                        sock.close()
                        return
                if definition.access_mode == "token":
                    supplied = str(request.get("token", ""))
                    if not definition.token or not hmac.compare_digest(supplied, definition.token):
                        self._send_json(sock, {"ok": False, "error": "authentication failed"})
                        sock.close()
                        return
                active_clients = sum(len(item.clients) for item in self._streams.values())
                if active_clients >= self.max_clients:
                    self._send_json(sock, {"ok": False, "error": "stream server client limit reached"})
                    sock.close()
                    return
                requested_capacity = int(request.get("capacity", definition.capacity))
                capacity = max(1, min(requested_capacity, 1024))
                requested_policy = str(request.get("policy", definition.policy))
                policy = requested_policy if requested_policy in {"block", "latest", "drop_oldest", "drop_newest"} else definition.policy
                client = _Client(
                    socket=sock,
                    address=address,
                    stream=name,
                    queue=_PacketQueue(capacity, policy),
                )
                definition.clients.append(client)
            self._send_json(sock, {"ok": True, "stream": name, "type": definition.type})
            sock.settimeout(None)
            client.thread = threading.Thread(
                target=self._sender_loop,
                args=(client,),
                name=f"nodrix-send:{name}:{address[0]}",
                daemon=True,
            )
            client.thread.start()
        except Exception:
            try:
                sock.close()
            except OSError:
                pass

    def _sender_loop(self, client: _Client) -> None:
        try:
            while not self._stop.is_set():
                packet = client.queue.get()
                if packet is None:
                    break
                client.sent_bytes += send_packet(client.socket, packet)
                client.sent_messages += 1
        except (OSError, EOFError, ConnectionError):
            client.errors += 1
        finally:
            client.queue.close()
            try:
                client.socket.close()
            except OSError:
                pass
            with self._lock:
                definition = self._streams.get(client.stream)
                if definition is not None:
                    definition.total_sent_messages += client.sent_messages
                    definition.total_sent_bytes += client.sent_bytes
                    definition.total_client_errors += client.errors
                    if client in definition.clients:
                        definition.clients.remove(client)

    def publish(self, name: str, message: Message) -> None:
        with self._lock:
            definition = self._streams.get(name)
            if definition is None:
                raise KeyError(name)
        definition.published += 1
        assert definition.incoming is not None
        definition.incoming.put(message)

    def report(self) -> dict[str, Any]:
        with self._lock:
            return {
                name: {
                    "type": item.type,
                    "published": item.published,
                    "encoded_messages": item.encoded_messages,
                    "encoded_bytes": item.encoded_bytes,
                    "subscribers": len(item.clients),
                    "queue": item.incoming.stats() if item.incoming is not None else {},
                    "sent_messages": item.total_sent_messages + sum(client.sent_messages for client in item.clients),
                    "sent_bytes": item.total_sent_bytes + sum(client.sent_bytes for client in item.clients),
                    "client_errors": item.total_client_errors + sum(client.errors for client in item.clients),
                }
                for name, item in self._streams.items()
            }

    def close(self) -> None:
        self._stop.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        with self._lock:
            definitions = tuple(self._streams.values())
            clients = [client for definition in definitions for client in definition.clients]
        for definition in definitions:
            if definition.incoming is not None:
                definition.incoming.close()
        for definition in definitions:
            if definition.thread is not None:
                definition.thread.join(timeout=1.0)
                definition.thread = None
        for client in clients:
            client.queue.close()
            try:
                client.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.socket.close()
            except OSError:
                pass


class StreamPublisher:
    def __init__(
        self, pipeline: str, exports: list[dict[str, Any]], *, host: str = "127.0.0.1", port: int = 0,
        max_handshake_bytes: int = 64 * 1024, max_message_bytes: int = 256 * 1024 * 1024,
        handshake_timeout: float = 5.0, max_handshakes: int = 32, max_clients: int = 128,
    ) -> None:
        self.pipeline = pipeline
        self.exports = exports
        self.server = StreamServer(
            host=host,
            port=port,
            max_handshake_bytes=max_handshake_bytes,
            max_message_bytes=max_message_bytes,
            handshake_timeout=handshake_timeout,
            max_handshakes=max_handshakes,
            max_clients=max_clients,
        )
        self._by_source: dict[str, list[str]] = {}
        for export in exports:
            self.server.register(
                export["name"],
                export["type"],
                capacity=int(export.get("capacity", 2)),
                policy=str(export.get("policy", "latest")),
                access_mode=str(export.get("access_mode", "open")),
                token=export.get("token"),
                allow_ips=tuple(export.get("allow_ips", ())),
            )
            self._by_source.setdefault(export["source"], []).append(export["name"])
        self.advertiser: DiscoveryAdvertiser | None = None

    def start(self) -> None:
        self.server.start()
        self.advertiser = DiscoveryAdvertiser(
            pipeline=self.pipeline,
            endpoint_port=self.server.port,
            streams=self.server.definitions,
        )
        self.advertiser.start()

    def publish(self, source: str, message: Message) -> None:
        for name in self._by_source.get(source, ()):
            self.server.publish(name, message)

    def report(self) -> dict[str, Any]:
        return self.server.report()

    def close(self) -> None:
        if self.advertiser is not None:
            self.advertiser.close()
            self.advertiser = None
        self.server.close()


class StreamClient:
    def __init__(
        self,
        uri_or_name: str,
        *,
        discovery_timeout: float = 3.0,
        capacity: int = 2,
        policy: str = "latest",
        receive_buffer_bytes: int = 262144,
        token: str | None = None,
        max_message_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        if uri_or_name.startswith("nodrix://"):
            uri = uri_or_name
        else:
            uri = resolve_stream(uri_or_name, timeout=discovery_timeout).endpoint
        parsed = urlparse(uri)
        if parsed.scheme != "nodrix" or not parsed.hostname or not parsed.port or not parsed.path:
            raise ValueError(f"Invalid Nodrix stream URI: {uri!r}")
        self.uri = uri
        self.host = parsed.hostname
        self.port = parsed.port
        self.stream = parsed.path
        if capacity <= 0:
            raise ValueError("StreamClient capacity must be positive")
        if policy not in {"block", "latest", "drop_oldest", "drop_newest"}:
            raise ValueError(f"Unsupported StreamClient policy: {policy}")
        self.capacity = int(capacity)
        self.policy = policy
        query = parse_qs(parsed.query)
        if query.get("token"):
            raise ValueError("Stream tokens in URI query strings are forbidden; use --token or NODRIX_STREAM_TOKEN")
        self.token = token or os.environ.get("NODRIX_STREAM_TOKEN")
        self.max_message_bytes = int(max_message_bytes)
        self.receive_buffer_bytes = max(16384, int(receive_buffer_bytes))
        self.socket: socket.socket | None = None
        self.type: str | None = None

    def connect(self, timeout: float = 5.0) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.receive_buffer_bytes)
        request = {
            "protocol": "nodrix-stream/1",
            "action": "subscribe",
            "stream": self.stream,
            "capacity": self.capacity,
            "policy": self.policy,
            "token": self.token,
        }
        StreamServer._send_json(sock, request)
        response = StreamServer._receive_json(sock)
        if not response.get("ok"):
            sock.close()
            raise LookupError(response.get("error", "Nodrix stream subscription failed"))
        sock.settimeout(None)
        self.socket = sock
        self.type = str(response.get("type", "core.any"))

    def receive(self) -> Message:
        if self.socket is None:
            self.connect()
        assert self.socket is not None
        return recv_message(self.socket, max_message_bytes=self.max_message_bytes)

    def close(self) -> None:
        if self.socket is not None:
            try:
                self.socket.close()
            finally:
                self.socket = None
