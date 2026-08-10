"""Mutually authenticated TLS transport for the Nodrix remote-agent protocol.

The remote-agent RPC protocol is unchanged; this module only protects the
control-plane socket.  Certificates are expected to be provisioned on the host
before Nodrix starts.  A bearer token remains required by the underlying agent
service as a second authentication factor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import socket
import ssl
import threading
from typing import Any, Mapping

from .remote_agent import (
    DEFAULT_AGENT_MAX_REQUEST_BYTES,
    REMOTE_AGENT_PROTOCOL,
    RemoteAgentEndpoint,
    RemoteAgentError,
    RemoteAgentService,
    _ThreadingAgentServer,
    _recv_json,
    _send_json,
)


def _resolved_file(value: str | Path, *, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} does not exist or is not a file: {path}")
    return path


@dataclass(frozen=True, slots=True)
class RemoteAgentTLSClientConfig:
    """Client credentials for mutually authenticated remote-agent TLS."""

    ca_file: Path
    cert_file: Path
    key_file: Path
    server_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ca_file",
            _resolved_file(self.ca_file, label="remote agent TLS CA file"),
        )
        object.__setattr__(
            self,
            "cert_file",
            _resolved_file(self.cert_file, label="remote agent TLS client certificate"),
        )
        object.__setattr__(
            self,
            "key_file",
            _resolved_file(self.key_file, label="remote agent TLS client key"),
        )
        if self.server_name is not None and not self.server_name.strip():
            raise ValueError("remote agent TLS server_name must not be empty")

    def ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH,
            cafile=str(self.ca_file),
        )
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            certfile=str(self.cert_file),
            keyfile=str(self.key_file),
        )
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        return context


@dataclass(frozen=True, slots=True)
class RemoteAgentTLSServerConfig:
    """Server credentials for a mutually authenticated agent listener."""

    cert_file: Path
    key_file: Path
    ca_file: Path

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "cert_file",
            _resolved_file(self.cert_file, label="remote agent TLS server certificate"),
        )
        object.__setattr__(
            self,
            "key_file",
            _resolved_file(self.key_file, label="remote agent TLS server key"),
        )
        object.__setattr__(
            self,
            "ca_file",
            _resolved_file(self.ca_file, label="remote agent TLS client CA file"),
        )

    def ssl_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            certfile=str(self.cert_file),
            keyfile=str(self.key_file),
        )
        context.load_verify_locations(cafile=str(self.ca_file))
        context.verify_mode = ssl.CERT_REQUIRED
        return context


class TLSRemoteAgentClient:
    """Remote-agent client protected by mutual TLS plus the agent token."""

    def __init__(
        self,
        endpoint: RemoteAgentEndpoint,
        tls: RemoteAgentTLSClientConfig,
    ) -> None:
        self.endpoint = endpoint
        self.tls = tls
        self._ssl_context = tls.ssl_context()

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
        server_name = self.tls.server_name or self.endpoint.host
        try:
            with socket.create_connection(
                (self.endpoint.host, self.endpoint.port),
                timeout=self.endpoint.timeout_seconds,
            ) as raw_sock:
                raw_sock.settimeout(self.endpoint.timeout_seconds)
                with self._ssl_context.wrap_socket(
                    raw_sock,
                    server_hostname=server_name,
                ) as sock:
                    _send_json(sock, document)
                    response = _recv_json(
                        sock,
                        max_bytes=self.endpoint.max_response_bytes,
                    )
        except RemoteAgentError:
            raise
        except (OSError, EOFError, ssl.SSLError) as exc:
            raise RemoteAgentError(
                "AGENT503",
                f"cannot establish authenticated TLS session with remote agent at "
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


class _TLSAgentServer(_ThreadingAgentServer):
    def __init__(self, *args, ssl_context: ssl.SSLContext, **kwargs) -> None:
        self._ssl_context = ssl_context
        super().__init__(*args, **kwargs)

    def get_request(self):
        raw_socket, address = super().get_request()
        try:
            wrapped = self._ssl_context.wrap_socket(raw_socket, server_side=True)
        except BaseException:
            raw_socket.close()
            raise
        return wrapped, address


class TLSRemoteAgentServer:
    """Remote-agent server that permits LAN listeners only under mTLS."""

    def __init__(
        self,
        *,
        host: str,
        port: int = 7843,
        token: str,
        working_directory: str | Path,
        tls: RemoteAgentTLSServerConfig,
        run_root: str | Path | None = None,
        max_request_bytes: int = DEFAULT_AGENT_MAX_REQUEST_BYTES,
    ) -> None:
        if not host.strip():
            raise ValueError("remote agent bind host must not be empty")
        if port < 0 or port > 65535:
            raise ValueError("remote agent port must be between 0 and 65535")
        if max_request_bytes < 1024:
            raise ValueError("remote agent max_request_bytes must be at least 1024")
        self.service = RemoteAgentService(
            token=token,
            working_directory=working_directory,
            run_root=run_root,
        )
        self.tls = tls
        self._server = _TLSAgentServer(
            (host, port),
            self.service,
            max_request_bytes=max_request_bytes,
            ssl_context=tls.ssl_context(),
        )
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("remote agent TLS server is already started")
        thread = threading.Thread(
            target=self._server.serve_forever,
            name="nodrix-remote-agent-tls",
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

    def __enter__(self) -> "TLSRemoteAgentServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = [
    "RemoteAgentTLSClientConfig",
    "RemoteAgentTLSServerConfig",
    "TLSRemoteAgentClient",
    "TLSRemoteAgentServer",
]
