from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
import json
import hmac
import ipaddress
import os
import queue
import random
import socket
import ssl
import struct
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from .discovery import DiscoveryAdvertiser, resolve_stream
from .messages import Message
from .wire import encode_message, recv_message, send_packet

_HANDSHAKE_LENGTH = struct.Struct("!I")
_TLS_VERSIONS = {
    "TLSv1.2": ssl.TLSVersion.TLSv1_2,
    "TLSv1.3": ssl.TLSVersion.TLSv1_3,
}


def _tls_version(name: str) -> ssl.TLSVersion:
    try:
        return _TLS_VERSIONS[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported minimum TLS version: {name}") from exc


def server_tls_context(
    *,
    certificate: str,
    private_key: str,
    client_ca: str | None = None,
    require_client_certificate: bool = False,
    minimum_version: str = "TLSv1.2",
) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = _tls_version(minimum_version)
    context.load_cert_chain(certificate, private_key)
    if require_client_certificate:
        if not client_ca:
            raise ValueError("Mutual TLS requires a client CA")
        context.load_verify_locations(cafile=client_ca)
        context.verify_mode = ssl.CERT_REQUIRED
    return context


def client_tls_context(
    *,
    ca_file: str | None = None,
    certificate: str | None = None,
    private_key: str | None = None,
    minimum_version: str = "TLSv1.2",
) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
    context.minimum_version = _tls_version(minimum_version)
    if bool(certificate) != bool(private_key):
        raise ValueError("Client TLS certificate and private key must be configured together")
    if certificate and private_key:
        context.load_cert_chain(certificate, private_key)
    return context

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
        tls_context: ssl.SSLContext | None = None,
    ) -> None:
        self.host = host
        self.requested_port = int(port)
        self.max_handshake_bytes = int(max_handshake_bytes)
        self.max_message_bytes = int(max_message_bytes)
        self.handshake_timeout = max(0.1, float(handshake_timeout))
        self.max_clients = max(1, int(max_clients))
        self.tls_context = tls_context
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
        value = json.loads(bytes(data).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Nodrix handshake must be a JSON object")
        return value

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
            if self.tls_context is not None:
                sock = self.tls_context.wrap_socket(sock, server_side=True)
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
                    "transport": "tls" if self.tls_context is not None else "tcp",
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
        tls: dict[str, Any] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.exports = exports
        tls = dict(tls or {})
        tls_context = None
        if tls.get("enabled"):
            tls_context = server_tls_context(
                certificate=str(tls["certificate"]),
                private_key=str(tls["private_key"]),
                client_ca=str(tls["client_ca"]) if tls.get("client_ca") else None,
                require_client_certificate=bool(tls.get("require_client_certificate", False)),
                minimum_version=str(tls.get("minimum_version", "TLSv1.2")),
            )
        self.server = StreamServer(
            host=host,
            port=port,
            max_handshake_bytes=max_handshake_bytes,
            max_message_bytes=max_message_bytes,
            handshake_timeout=handshake_timeout,
            max_handshakes=max_handshakes,
            max_clients=max_clients,
            tls_context=tls_context,
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
            endpoint_scheme="nodrix+tls" if self.server.tls_context is not None else "nodrix",
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
        ca_file: str | None = None,
        certificate: str | None = None,
        private_key: str | None = None,
        server_hostname: str | None = None,
        minimum_tls_version: str = "TLSv1.2",
        reconnect_attempts: int = 0,
        reconnect_backoff: float = 0.1,
        reconnect_max_backoff: float = 5.0,
        reconnect_attempts_per_disconnect: int | None = None,
        reconnect_max_total_attempts: int | None = None,
        reconnect_window_seconds: float = 300.0,
        reconnect_reset_after_stable_seconds: float = 60.0,
        reconnect_jitter: float = 0.2,
    ) -> None:
        if uri_or_name.startswith(("nodrix://", "nodrix+tls://")):
            uri = uri_or_name
        else:
            uri = resolve_stream(uri_or_name, timeout=discovery_timeout).endpoint
        parsed = urlparse(uri)
        if parsed.scheme not in {"nodrix", "nodrix+tls"} or not parsed.hostname or not parsed.port or not parsed.path:
            raise ValueError(f"Invalid Nodrix stream URI: {uri!r}")
        self.uri = uri
        self.host = parsed.hostname
        self.port = parsed.port
        self.stream = parsed.path
        self.tls = parsed.scheme == "nodrix+tls"
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
        attempts_per_disconnect = (
            reconnect_attempts
            if reconnect_attempts_per_disconnect is None
            else reconnect_attempts_per_disconnect
        )
        max_total_attempts = (
            reconnect_attempts
            if reconnect_max_total_attempts is None
            else reconnect_max_total_attempts
        )
        if attempts_per_disconnect < 0 or max_total_attempts < 0:
            raise ValueError("Reconnect attempt limits cannot be negative")
        if reconnect_backoff < 0 or reconnect_max_backoff < reconnect_backoff:
            raise ValueError("Reconnect backoff must be non-negative and bounded")
        if reconnect_window_seconds <= 0:
            raise ValueError("reconnect_window_seconds must be positive")
        if reconnect_reset_after_stable_seconds < 0:
            raise ValueError(
                "reconnect_reset_after_stable_seconds cannot be negative"
            )
        if not 0 <= reconnect_jitter <= 1:
            raise ValueError("reconnect_jitter must be between 0 and 1")
        self.reconnect_attempts = int(attempts_per_disconnect)
        self.reconnect_max_total_attempts = int(max_total_attempts)
        self.reconnect_window_seconds = float(reconnect_window_seconds)
        self.reconnect_reset_after_stable_seconds = float(
            reconnect_reset_after_stable_seconds
        )
        self.reconnect_jitter = float(reconnect_jitter)
        self.reconnect_backoff = float(reconnect_backoff)
        self.reconnect_max_backoff = float(reconnect_max_backoff)
        self.server_hostname = server_hostname or self.host
        ca_file = ca_file or os.environ.get("NODRIX_STREAM_CA")
        certificate = certificate or os.environ.get("NODRIX_STREAM_CERT")
        private_key = private_key or os.environ.get("NODRIX_STREAM_KEY")
        self._tls_context = (
            client_tls_context(
                ca_file=ca_file,
                certificate=certificate,
                private_key=private_key,
                minimum_version=minimum_tls_version,
            )
            if self.tls
            else None
        )
        self.socket: socket.socket | None = None
        self.type: str | None = None
        self.reconnects = 0
        self.reconnect_attempts_total = 0
        self.reconnect_success_total = 0
        self.reconnect_failures_total = 0
        self._reconnect_attempt_times: deque[float] = deque()
        self._connected_since: float | None = None
        self._state = "disconnected"
        self._shutdown = threading.Event()
        self._state_lock = threading.RLock()

    def _prune_reconnect_budget(self, now: float) -> None:
        threshold = now - self.reconnect_window_seconds
        while (
            self._reconnect_attempt_times
            and self._reconnect_attempt_times[0] < threshold
        ):
            self._reconnect_attempt_times.popleft()

    def _refresh_stable_state(self, now: float) -> None:
        if (
            self._connected_since is not None
            and now - self._connected_since
            >= self.reconnect_reset_after_stable_seconds
        ):
            self._reconnect_attempt_times.clear()
            if self._state == "degraded":
                self._state = "connected"

    def _reserve_reconnect_attempt(self) -> None:
        now = time.monotonic()
        with self._state_lock:
            self._prune_reconnect_budget(now)
            self._refresh_stable_state(now)
            if (
                self.reconnect_max_total_attempts <= 0
                or len(self._reconnect_attempt_times)
                >= self.reconnect_max_total_attempts
            ):
                self._state = "budget_exhausted"
                raise ConnectionError(
                    "Nodrix stream reconnect budget exhausted"
                )
            self._reconnect_attempt_times.append(now)
            self.reconnect_attempts_total += 1

    def _mark_disconnect(self) -> None:
        now = time.monotonic()
        with self._state_lock:
            self._refresh_stable_state(now)
            self._connected_since = None
            self._state = "reconnecting"

    def _close_socket(self) -> None:
        if self.socket is not None:
            try:
                self.socket.close()
            finally:
                self.socket = None

    def connect(
        self, timeout: float = 5.0, *, _reconnect: bool = False
    ) -> None:
        last_error: Exception | None = None
        attempt_limit = (
            self.reconnect_attempts
            if _reconnect
            else self.reconnect_attempts + 1
        )
        if attempt_limit <= 0:
            raise ConnectionError(
                "Nodrix stream reconnect is disabled"
            )
        for attempt in range(attempt_limit):
            if self._shutdown.is_set():
                raise ConnectionAbortedError(
                    "Nodrix stream client is shutting down"
                )
            if _reconnect:
                self._reserve_reconnect_attempt()
            sock: socket.socket | None = None
            try:
                sock = socket.create_connection((self.host, self.port), timeout=timeout)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.receive_buffer_bytes)
                if self._tls_context is not None:
                    sock = self._tls_context.wrap_socket(
                        sock,
                        server_hostname=self.server_hostname,
                    )
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
                    raise LookupError(response.get("error", "Nodrix stream subscription failed"))
                sock.settimeout(None)
                self.socket = sock
                self.type = str(response.get("type", "core.any"))
                with self._state_lock:
                    self._state = (
                        "degraded" if _reconnect else "connected"
                    )
                    self._connected_since = time.monotonic()
                    if _reconnect:
                        self.reconnect_success_total += 1
                return
            except (OSError, EOFError, LookupError, ValueError) as exc:
                last_error = exc
                if sock is not None:
                    sock.close()
                if attempt + 1 >= attempt_limit:
                    with self._state_lock:
                        self._state = "failed"
                        if _reconnect:
                            self.reconnect_failures_total += 1
                    raise
                self.reconnects += 1
                delay = min(self.reconnect_backoff * (2**attempt), self.reconnect_max_backoff)
                if delay and self.reconnect_jitter:
                    delay *= random.uniform(
                        1.0 - self.reconnect_jitter,
                        1.0 + self.reconnect_jitter,
                    )
                if delay:
                    if self._shutdown.wait(delay):
                        raise ConnectionAbortedError(
                            "Nodrix stream shutdown interrupted reconnect backoff"
                        )
        assert last_error is not None
        raise last_error

    def receive(self) -> Message:
        if self.socket is None:
            self.connect()
        assert self.socket is not None
        try:
            return recv_message(self.socket, max_message_bytes=self.max_message_bytes)
        except (OSError, EOFError, ConnectionError):
            self._close_socket()
            self._mark_disconnect()
            if self.reconnect_attempts <= 0:
                raise
            self.connect(_reconnect=True)
            assert self.socket is not None
            return recv_message(self.socket, max_message_bytes=self.max_message_bytes)

    def report(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._state_lock:
            self._prune_reconnect_budget(now)
            self._refresh_stable_state(now)
            uptime = (
                0.0
                if self._connected_since is None
                else max(0.0, now - self._connected_since)
            )
            return {
                "state": self._state,
                "transport": "tls" if self.tls else "tcp",
                "reconnect_attempts_total": self.reconnect_attempts_total,
                "reconnect_success_total": self.reconnect_success_total,
                "reconnect_failures_total": self.reconnect_failures_total,
                "reconnect_budget_remaining": max(
                    0,
                    self.reconnect_max_total_attempts
                    - len(self._reconnect_attempt_times),
                ),
                "connection_uptime_seconds": uptime,
            }

    def close(self) -> None:
        self._shutdown.set()
        self._close_socket()
        with self._state_lock:
            self._connected_since = None
            self._state = "closed"
