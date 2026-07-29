from __future__ import annotations

from dataclasses import dataclass
import json
import select
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Any, Callable
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

DISCOVERY_GROUP = "239.255.77.77"
DISCOVERY_PORT = 47777
DISCOVERY_PROTOCOL = "nodrix-discovery/1"


def _local_ipv4_interfaces() -> list[str]:
    """Return active IPv4 interface addresses without external dependencies."""
    addresses: set[str] = set()
    if fcntl is not None:
        # Linux ioctl values. Failure is harmless on other Unix variants.
        for _index, name in socket.if_nameindex():
            try:
                request = struct.pack("256s", name[:15].encode("utf-8"))
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    result = fcntl.ioctl(probe.fileno(), 0x8915, request)  # SIOCGIFADDR
                    address = socket.inet_ntoa(result[20:24])
                    flags_raw = fcntl.ioctl(probe.fileno(), 0x8913, request)  # SIOCGIFFLAGS
                    flags = struct.unpack("H", flags_raw[16:18])[0]
                    if flags & 0x1:  # IFF_UP
                        addresses.add(address)
                finally:
                    probe.close()
            except OSError:
                continue
    if sys.platform == "darwin":
        for _index, name in socket.if_nameindex():
            try:
                result = subprocess.run(
                    ["/usr/sbin/ipconfig", "getifaddr", name],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=0.25,
                )
                address = result.stdout.strip()
                if address:
                    socket.inet_aton(address)
                    addresses.add(address)
            except (OSError, subprocess.SubprocessError):
                continue
    elif sys.platform.startswith("linux") and not addresses:
        try:
            result = subprocess.run(
                ["ip", "-o", "-4", "addr", "show", "up"],
                check=False,
                capture_output=True,
                text=True,
                timeout=0.5,
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if "inet" in parts:
                    address = parts[parts.index("inet") + 1].split("/", 1)[0]
                    addresses.add(address)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
            addresses.add(item[4][0])
    except OSError:
        pass
    # A route probe does not transmit traffic; it asks the kernel which local
    # address it would use and helps on platforms where ioctl is unavailable.
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect((DISCOVERY_GROUP, DISCOVERY_PORT))
            addresses.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    if not addresses:
        addresses.add("127.0.0.1")
    return sorted(addresses, key=lambda item: (item.startswith("127."), item))


def _discovery_socket(*, bind: bool) -> tuple[socket.socket, list[str]]:
    interfaces = _local_ipv4_interfaces()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    if bind:
        sock.bind(("", DISCOVERY_PORT))
        for interface in interfaces:
            try:
                membership = socket.inet_aton(DISCOVERY_GROUP) + socket.inet_aton(interface)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            except OSError:
                continue
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    return sock, interfaces


def _send_multicast(sock: socket.socket, interfaces: list[str], data: bytes) -> None:
    sent = False
    for interface in interfaces:
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface))
            sock.sendto(data, (DISCOVERY_GROUP, DISCOVERY_PORT))
            sent = True
        except OSError:
            continue
    if not sent:
        sock.sendto(data, (DISCOVERY_GROUP, DISCOVERY_PORT))


def _packet(data: dict[str, Any]) -> bytes:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class DiscoveredStream:
    name: str
    type: str
    host: str
    pipeline: str
    instance_id: str
    endpoint: str
    codec: str = "nodrix-wire/1"
    metadata: dict[str, Any] | None = None


class DiscoveryAdvertiser:
    """Zero-configuration LAN stream advertisement.

    Discovery belongs to the control plane only. Message payloads never pass
    through this object, so multicast discovery cannot slow the data path.
    """

    def __init__(
        self,
        *,
        pipeline: str,
        endpoint_port: int,
        streams: Callable[[], list[dict[str, Any]]],
        endpoint_scheme: str = "nodrix",
        interval: float = 1.0,
    ) -> None:
        self.pipeline = pipeline
        self.endpoint_port = int(endpoint_port)
        self.streams = streams
        if endpoint_scheme not in {"nodrix", "nodrix+tls"}:
            raise ValueError(f"Unsupported Nodrix endpoint scheme: {endpoint_scheme}")
        self.endpoint_scheme = endpoint_scheme
        self.interval = max(0.2, float(interval))
        self.instance_id = uuid.uuid4().hex
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._interfaces: list[str] = []

    def start(self) -> None:
        if self._thread is not None:
            return
        self._sock, self._interfaces = _discovery_socket(bind=True)
        self._sock.setblocking(False)
        self._thread = threading.Thread(target=self._run, name="nodrix-discovery", daemon=True)
        self._thread.start()

    def _advertisement(self) -> bytes:
        return _packet(
            {
                "protocol": DISCOVERY_PROTOCOL,
                "kind": "advertisement",
                "instance_id": self.instance_id,
                "host": socket.gethostname(),
                "pipeline": self.pipeline,
                "endpoint": {
                    "host": "0.0.0.0",
                    "port": self.endpoint_port,
                    "scheme": self.endpoint_scheme,
                },
                "streams": self.streams(),
                "expires_ms": int(self.interval * 3000),
            }
        )

    def _send(self) -> None:
        if self._sock is None:
            return
        try:
            _send_multicast(self._sock, self._interfaces, self._advertisement())
        except OSError:
            pass

    def _run(self) -> None:
        assert self._sock is not None
        next_send = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_send:
                self._send()
                next_send = now + self.interval
            timeout = max(0.0, min(0.2, next_send - now))
            try:
                readable, _, _ = select.select([self._sock], [], [], timeout)
            except OSError:
                break
            if not readable:
                continue
            try:
                raw, _address = self._sock.recvfrom(65535)
                message = json.loads(raw.decode("utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if message.get("protocol") == DISCOVERY_PROTOCOL and message.get("kind") == "query":
                self._send()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None


def discover_streams(timeout: float = 1.2, name: str | None = None) -> list[DiscoveredStream]:
    sock, interfaces = _discovery_socket(bind=True)
    sock.setblocking(False)
    query = _packet({"protocol": DISCOVERY_PROTOCOL, "kind": "query", "name": name})
    try:
        _send_multicast(sock, interfaces, query)
    except OSError:
        pass
    deadline = time.monotonic() + max(0.05, timeout)
    found: dict[tuple[str, str], DiscoveredStream] = {}
    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                readable, _, _ = select.select([sock], [], [], min(0.2, remaining))
            except OSError:
                break
            if not readable:
                continue
            try:
                raw, address = sock.recvfrom(65535)
                message = json.loads(raw.decode("utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if message.get("protocol") != DISCOVERY_PROTOCOL or message.get("kind") != "advertisement":
                continue
            endpoint = message.get("endpoint") or {}
            endpoint_host = endpoint.get("host") or address[0]
            if endpoint_host in {"0.0.0.0", "::", ""}:
                endpoint_host = address[0]
            endpoint_port = int(endpoint.get("port", 0))
            endpoint_scheme = str(endpoint.get("scheme", "nodrix"))
            if endpoint_scheme not in {"nodrix", "nodrix+tls"}:
                continue
            for stream in message.get("streams") or []:
                stream_name = str(stream.get("name", ""))
                if not stream_name or (name is not None and stream_name != name):
                    continue
                item = DiscoveredStream(
                    name=stream_name,
                    type=str(stream.get("type", "core.any")),
                    host=str(message.get("host", endpoint_host)),
                    pipeline=str(message.get("pipeline", "")),
                    instance_id=str(message.get("instance_id", "")),
                    endpoint=f"{endpoint_scheme}://{endpoint_host}:{endpoint_port}{stream_name}",
                    codec=str(stream.get("codec", "nodrix-wire/1")),
                    metadata=dict(stream.get("metadata") or {}),
                )
                found[(item.instance_id, item.name)] = item
    finally:
        sock.close()
    return sorted(found.values(), key=lambda item: (item.host, item.pipeline, item.name))


def resolve_stream(name: str, timeout: float = 3.0) -> DiscoveredStream:
    streams = discover_streams(timeout=timeout, name=name)
    if not streams:
        raise LookupError(f"Nodrix stream not found on LAN: {name}")
    if len(streams) > 1:
        endpoints = ", ".join(item.endpoint for item in streams)
        raise LookupError(f"Multiple Nodrix streams named {name!r}; use an explicit URI: {endpoints}")
    return streams[0]
