"""Remote execution agent control plane for Nodrix 2.8.

M5 keeps the control plane separate from M4 data transports.  The agent
receives a canonical SystemExecutionPlan plus one ExecutionScope and reuses the
existing M3/M4 process backends on the target host.  No packages are installed
or provisioned here: the target is assumed to be prepared already.

The first agent transport is intentionally loopback-only.  A non-loopback
listener must be introduced together with an authenticated encrypted channel;
plain bearer tokens are not sufficient protection on an untrusted network.
"""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
from pathlib import Path
import socket
import socketserver
import struct
import threading
from typing import Any, Mapping
from uuid import uuid4

from .backend import BackendExecutionStatus, PreparedExecution
from .orchestration import ExecutionScope, backend_context_for_scope
from .planning import SystemExecutionPlan
from .process_backend import ProcessBackend
from .transport_process_backend import TransportProcessBackend


REMOTE_AGENT_PROTOCOL = "nodrix.remote-agent/v1"
DEFAULT_AGENT_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_HEADER = struct.Struct("!I")


class RemoteAgentError(RuntimeError):
    """A remote-agent request failed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class RemoteAgentEndpoint:
    host: str
    port: int
    token: str
    timeout_seconds: float = 10.0
    max_response_bytes: int = DEFAULT_AGENT_MAX_REQUEST_BYTES

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("remote agent host must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("remote agent port must be between 1 and 65535")
        if not self.token:
            raise ValueError("remote agent token must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("remote agent timeout_seconds must be positive")
        if self.max_response_bytes < 1024:
            raise ValueError("remote agent max_response_bytes must be at least 1024")


@dataclass(slots=True)
class _PreparedRemoteScope:
    backend: ProcessBackend
    prepared: PreparedExecution


@dataclass(slots=True)
class _RunningRemoteScope:
    backend: ProcessBackend
    handle: Any


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise EOFError("remote agent connection closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _send_json(sock: socket.socket, document: Mapping[str, Any]) -> None:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    sock.sendall(_HEADER.pack(len(payload)))
    sock.sendall(payload)


def _recv_json(sock: socket.socket, *, max_bytes: int) -> dict[str, Any]:
    length = _HEADER.unpack(_recv_exact(sock, _HEADER.size))[0]
    if length <= 0 or length > max_bytes:
        raise RemoteAgentError(
            "AGENT413",
            f"message size {length} exceeds limit {max_bytes}",
        )
    try:
        value = json.loads(_recv_exact(sock, length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteAgentError("AGENT400", "invalid JSON request") from exc
    if not isinstance(value, dict):
        raise RemoteAgentError("AGENT400", "request must be a JSON object")
    return value


def _status_document(status: BackendExecutionStatus) -> dict[str, Any]:
    return {
        "backend": status.backend,
        "execution_id": status.execution_id,
        "state": status.state.value,
        "message": status.message,
        "details": dict(status.details),
    }


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


class RemoteAgentService:
    """Stateful execution service hosted on one prepared Nodrix machine."""

    def __init__(
        self,
        *,
        token: str,
        working_directory: str | Path,
        run_root: str | Path | None = None,
    ) -> None:
        if not token:
            raise ValueError("remote agent token must not be empty")
        self._token = token
        self.working_directory = Path(working_directory).expanduser().resolve()
        self.run_root = (
            Path(run_root).expanduser().resolve()
            if run_root is not None
            else None
        )
        self._prepared: dict[str, _PreparedRemoteScope] = {}
        self._running: dict[str, _RunningRemoteScope] = {}
        self._lock = threading.RLock()

    def authenticate(self, token: object) -> bool:
        return isinstance(token, str) and hmac.compare_digest(token, self._token)

    def _backend_for(
        self,
        plan: SystemExecutionPlan,
        scope: ExecutionScope,
    ) -> ProcessBackend:
        if scope.backend != "process":
            raise RemoteAgentError(
                "AGENT422",
                f"M5 agent supports process scopes only, got {scope.backend!r}",
            )
        context = backend_context_for_scope(plan, scope)
        backend_type = (
            TransportProcessBackend
            if context.inbound_links or context.outbound_links
            else ProcessBackend
        )
        return backend_type(
            working_directory=self.working_directory,
            run_root=self.run_root,
            scope_name=scope.target,
        )

    def ping(self) -> dict[str, Any]:
        return {
            "protocol": REMOTE_AGENT_PROTOCOL,
            "backends": ["process"],
        }

    def prepare(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            plan = SystemExecutionPlan.model_validate(payload["plan"])
            raw_scope = payload["scope"]
            scope = ExecutionScope(
                target=str(raw_scope["target"]),
                backend=str(raw_scope["backend"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteAgentError("AGENT400", f"invalid prepare payload: {exc}") from exc

        context = backend_context_for_scope(plan, scope)
        backend = self._backend_for(plan, scope)
        report = backend.validate(context)
        if not report.valid:
            detail = "; ".join(
                f"{item.code} {item.path}: {item.message}"
                for item in report.errors
            )
            raise RemoteAgentError("AGENT422", detail or "backend validation failed")

        prepared = backend.prepare(context)
        preparation_id = f"prep-{uuid4().hex[:16]}"
        with self._lock:
            self._prepared[preparation_id] = _PreparedRemoteScope(
                backend=backend,
                prepared=prepared,
            )
        return {
            "preparation_id": preparation_id,
            "backend": scope.backend,
            "target": scope.target,
            "metadata": dict(prepared.metadata),
        }

    def start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        preparation_id = str(payload.get("preparation_id", ""))
        with self._lock:
            item = self._prepared.pop(preparation_id, None)
        if item is None:
            raise RemoteAgentError(
                "AGENT404",
                f"unknown preparation {preparation_id!r}",
            )

        handle = item.backend.start(item.prepared)
        remote_id = f"remote-{uuid4().hex[:16]}"
        with self._lock:
            self._running[remote_id] = _RunningRemoteScope(
                backend=item.backend,
                handle=handle,
            )
        return {
            "remote_execution_id": remote_id,
            "backend_execution_id": handle.execution_id,
        }

    def inspect(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        remote_id = str(payload.get("remote_execution_id", ""))
        with self._lock:
            item = self._running.get(remote_id)
        if item is None:
            raise RemoteAgentError("AGENT404", f"unknown execution {remote_id!r}")
        return _status_document(item.backend.inspect(item.handle))

    def stop(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        remote_id = str(payload.get("remote_execution_id", ""))
        timeout = payload.get("timeout_seconds")
        timeout_seconds = None if timeout is None else float(timeout)
        with self._lock:
            item = self._running.get(remote_id)
        if item is None:
            raise RemoteAgentError("AGENT404", f"unknown execution {remote_id!r}")
        return _status_document(
            item.backend.stop(item.handle, timeout_seconds=timeout_seconds)
        )

    def dispatch(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if operation == "ping":
            return self.ping()
        if operation == "prepare":
            return self.prepare(payload)
        if operation == "start":
            return self.start(payload)
        if operation == "inspect":
            return self.inspect(payload)
        if operation == "stop":
            return self.stop(payload)
        raise RemoteAgentError("AGENT404", f"unknown operation {operation!r}")

    def close(self, *, timeout_seconds: float = 2.0) -> None:
        with self._lock:
            running = tuple(self._running.values())
            self._running.clear()
            self._prepared.clear()
        for item in reversed(running):
            try:
                item.backend.stop(
                    item.handle,
                    timeout_seconds=timeout_seconds,
                )
            except Exception:
                # Agent shutdown is best-effort here; normal lifecycle errors are
                # reported through explicit stop/inspect calls.
                continue


class _AgentRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        assert isinstance(server, _ThreadingAgentServer)
        try:
            request = _recv_json(
                self.request,
                max_bytes=server.max_request_bytes,
            )
            if request.get("protocol") != REMOTE_AGENT_PROTOCOL:
                raise RemoteAgentError("AGENT426", "unsupported agent protocol")
            if not server.service.authenticate(request.get("token")):
                raise RemoteAgentError("AGENT401", "agent authentication failed")
            operation = request.get("op")
            if not isinstance(operation, str) or not operation:
                raise RemoteAgentError("AGENT400", "request operation is required")
            payload = request.get("payload") or {}
            if not isinstance(payload, dict):
                raise RemoteAgentError("AGENT400", "request payload must be an object")
            result = server.service.dispatch(operation, payload)
            response = {"ok": True, "payload": result}
        except RemoteAgentError as exc:
            response = {
                "ok": False,
                "error": {"code": exc.code, "message": exc.message},
            }
        except Exception as exc:
            response = {
                "ok": False,
                "error": {
                    "code": "AGENT500",
                    "message": f"{type(exc).__name__}: {exc}",
                },
            }
        try:
            _send_json(self.request, response)
        except OSError:
            return


class _ThreadingAgentServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        service: RemoteAgentService,
        *,
        max_request_bytes: int,
    ) -> None:
        self.service = service
        self.max_request_bytes = max_request_bytes
        super().__init__(address, _AgentRequestHandler)


class RemoteAgentServer:
    """Loopback-only TCP server exposing :class:`RemoteAgentService`."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        token: str,
        working_directory: str | Path,
        run_root: str | Path | None = None,
        max_request_bytes: int = DEFAULT_AGENT_MAX_REQUEST_BYTES,
    ) -> None:
        if not _is_loopback_host(host):
            raise ValueError(
                "M5a remote agent is loopback-only; non-loopback requires TLS"
            )
        if port < 0 or port > 65535:
            raise ValueError("remote agent port must be between 0 and 65535")
        if max_request_bytes < 1024:
            raise ValueError("remote agent max_request_bytes must be at least 1024")
        self.service = RemoteAgentService(
            token=token,
            working_directory=working_directory,
            run_root=run_root,
        )
        self._server = _ThreadingAgentServer(
            (host, port),
            self.service,
            max_request_bytes=max_request_bytes,
        )
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("remote agent server is already started")
        thread = threading.Thread(
            target=self._server.serve_forever,
            name="nodrix-remote-agent",
            daemon=True,
        )
        thread.start()
        self._thread = thread

    def close(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=2.0)
            self._thread = None
        self._server.server_close()
        self.service.close()

    def __enter__(self) -> "RemoteAgentServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class RemoteAgentClient:
    """One-request-per-connection client for the M5 control protocol."""

    def __init__(self, endpoint: RemoteAgentEndpoint) -> None:
        self.endpoint = endpoint

    def request(
        self,
        operation: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        document = {
            "protocol": REMOTE_AGENT_PROTOCOL,
            "token": self.endpoint.token,
            "op": operation,
            "payload": dict(payload or {}),
        }
        try:
            with socket.create_connection(
                (self.endpoint.host, self.endpoint.port),
                timeout=self.endpoint.timeout_seconds,
            ) as sock:
                sock.settimeout(self.endpoint.timeout_seconds)
                _send_json(sock, document)
                response = _recv_json(
                    sock,
                    max_bytes=self.endpoint.max_response_bytes,
                )
        except RemoteAgentError:
            raise
        except (OSError, EOFError) as exc:
            raise RemoteAgentError(
                "AGENT503",
                f"cannot reach remote agent at "
                f"{self.endpoint.host}:{self.endpoint.port}: {exc}",
            ) from exc

        if response.get("ok") is not True:
            error = response.get("error") or {}
            raise RemoteAgentError(
                str(error.get("code", "AGENT500")),
                str(error.get("message", "remote agent request failed")),
            )
        payload_value = response.get("payload") or {}
        if not isinstance(payload_value, dict):
            raise RemoteAgentError("AGENT500", "agent returned invalid payload")
        return payload_value

    def ping(self) -> dict[str, Any]:
        return self.request("ping")


__all__ = [
    "DEFAULT_AGENT_MAX_REQUEST_BYTES",
    "REMOTE_AGENT_PROTOCOL",
    "RemoteAgentClient",
    "RemoteAgentEndpoint",
    "RemoteAgentError",
    "RemoteAgentServer",
    "RemoteAgentService",
]
