"""Remote target backend for Nodrix 2.8 M5.

``RemoteProcessBackend`` keeps the public backend id ``process``: execution is
still process-isolated, only the Target location changes.  Lifecycle requests
are delegated to a prepared Nodrix remote agent while M4 transports continue
to carry data between scopes independently.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping

from .backend import (
    BackendCapabilities,
    BackendContext,
    BackendDiagnostic,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    PreparedExecution,
)
from .remote_agent import (
    REMOTE_AGENT_PROTOCOL,
    RemoteAgentClient,
    RemoteAgentEndpoint,
    RemoteAgentError,
)
from .remote_tls import (
    RemoteAgentTLSClientConfig,
    TLSRemoteAgentClient,
)


@dataclass(frozen=True, slots=True)
class RemotePreparedPayload:
    client: RemoteAgentClient | TLSRemoteAgentClient
    preparation_id: str
    target: str


@dataclass(frozen=True, slots=True)
class RemoteExecutionPayload:
    client: RemoteAgentClient | TLSRemoteAgentClient
    remote_execution_id: str
    backend_execution_id: str
    target: str


def _agent_mapping(context: BackendContext) -> Mapping[str, Any] | None:
    if len(context.targets) != 1:
        return None
    raw = context.targets[0].properties.get("agent")
    return raw if isinstance(raw, Mapping) else None


def _tls_from_context(
    context: BackendContext,
) -> RemoteAgentTLSClientConfig | None:
    raw = _agent_mapping(context)
    if raw is None:
        return None

    raw_tls = raw.get("tls")
    if raw_tls is None:
        return None
    if not isinstance(raw_tls, Mapping):
        raise ValueError("remote agent property 'tls' must be a mapping")

    def required_path(name: str) -> Path:
        value = raw_tls.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"remote agent TLS property {name!r} must be a non-empty string"
            )
        return Path(value.strip())

    server_name = raw_tls.get("server_name")
    if server_name is not None and not isinstance(server_name, str):
        raise ValueError(
            "remote agent TLS property 'server_name' must be a string"
        )

    return RemoteAgentTLSClientConfig(
        ca_file=required_path("ca_file"),
        cert_file=required_path("cert_file"),
        key_file=required_path("key_file"),
        server_name=server_name,
    )


def _endpoint_from_context(context: BackendContext) -> RemoteAgentEndpoint:
    if len(context.targets) != 1:
        raise ValueError("remote process scope must resolve exactly one Target")
    target = context.targets[0]
    raw = target.properties.get("agent")
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"Target {target.name!r} requires an 'agent' mapping for remote execution"
        )

    host = raw.get("host")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("remote agent property 'host' must be a non-empty string")

    raw_port = raw.get("port")
    if isinstance(raw_port, bool):
        raise ValueError("remote agent property 'port' must be an integer")
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("remote agent property 'port' must be an integer") from exc

    token_env = raw.get("token_env")
    if not isinstance(token_env, str) or not token_env.strip():
        raise ValueError(
            "remote agent property 'token_env' must name an environment variable"
        )
    token = os.environ.get(token_env.strip())
    if not token:
        raise ValueError(
            f"remote agent token environment variable {token_env.strip()!r} is not set"
        )

    raw_timeout = raw.get("timeout_seconds", 10.0)
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("remote agent 'timeout_seconds' must be numeric") from exc

    return RemoteAgentEndpoint(
        host=host.strip(),
        port=port,
        token=token,
        timeout_seconds=timeout,
    )


def _loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


class RemoteProcessBackend(ExecutionBackend):
    """Execute a ``process`` scope through a Nodrix agent on another Target."""

    def __init__(
        self,
        *,
        working_directory: str | Path | None = None,
    ) -> None:
        super().__init__(
            "process",
            capabilities=BackendCapabilities(
                target_kinds=frozenset({"host"}),
                features=frozenset(
                    {
                        "remote_agent",
                        "process_isolation",
                        "graphs",
                        "resources",
                        "applications",
                        "system_transport",
                    }
                ),
                metadata={
                    "remote_protocol": REMOTE_AGENT_PROTOCOL,
                    "control_plane": "mtls-or-loopback-token-m5b",
                },
            ),
        )
        self.working_directory = (
            Path(working_directory).expanduser().resolve()
            if working_directory is not None
            else Path.cwd().resolve()
        )

    def _validate(self, context: BackendContext):
        diagnostics: list[BackendDiagnostic] = []
        if len(context.targets) != 1:
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="REMOTE101",
                    path="targets",
                    message="remote process scope must resolve exactly one Target",
                )
            )
            return diagnostics

        target = context.targets[0]
        raw = _agent_mapping(context)
        if raw is None:
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="REMOTE102",
                    path=f"targets.{target.name}.properties.agent",
                    message="remote Target requires an agent mapping",
                )
            )
            return diagnostics

        try:
            endpoint = _endpoint_from_context(context)
        except ValueError as exc:
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="REMOTE103",
                    path=f"targets.{target.name}.properties.agent",
                    message=str(exc),
                )
            )
            return diagnostics

        try:
            tls = _tls_from_context(context)
        except ValueError as exc:
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="REMOTE105",
                    path=f"targets.{target.name}.properties.agent.tls",
                    message=str(exc),
                )
            )
            return diagnostics

        if not _loopback_host(endpoint.host) and tls is None:
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="REMOTE104",
                    path=f"targets.{target.name}.properties.agent.host",
                    message=(
                        "non-loopback remote execution requires mutually "
                        "authenticated TLS configuration"
                    ),
                )
            )
        return diagnostics

    def _prepare(self, context: BackendContext) -> PreparedExecution:
        endpoint = _endpoint_from_context(context)
        tls = _tls_from_context(context)
        client = (
            TLSRemoteAgentClient(endpoint, tls)
            if tls is not None
            else RemoteAgentClient(endpoint)
        )
        ping = client.ping()
        if ping.get("protocol") != REMOTE_AGENT_PROTOCOL:
            raise RemoteAgentError(
                "REMOTE201",
                "remote agent protocol does not match this Nodrix runtime",
            )
        backends = ping.get("backends") or []
        if "process" not in backends:
            raise RemoteAgentError(
                "REMOTE202",
                "remote agent does not advertise process execution",
            )

        scope_target = context.targets[0].name
        response = client.request(
            "prepare",
            {
                "plan": context.plan.model_dump(by_alias=True, mode="json"),
                "scope": {
                    "target": scope_target,
                    "backend": context.backend,
                },
            },
        )
        preparation_id = str(response.get("preparation_id", ""))
        if not preparation_id:
            raise RemoteAgentError(
                "REMOTE203",
                "remote agent returned no preparation id",
            )
        return PreparedExecution(
            backend=self.backend_id,
            context=context,
            payload=RemotePreparedPayload(
                client=client,
                preparation_id=preparation_id,
                target=scope_target,
            ),
            metadata={
                "remote": True,
                "target": scope_target,
                "agent_host": endpoint.host,
                "agent_port": endpoint.port,
                "agent_tls": tls is not None,
                "preparation_id": preparation_id,
                "remote_metadata": dict(response.get("metadata") or {}),
            },
        )

    def _start(self, prepared: PreparedExecution) -> BackendExecutionHandle:
        payload = prepared.payload
        if not isinstance(payload, RemotePreparedPayload):
            raise TypeError("RemoteProcessBackend requires RemotePreparedPayload")
        response = payload.client.request(
            "start",
            {"preparation_id": payload.preparation_id},
        )
        remote_id = str(response.get("remote_execution_id", ""))
        backend_id = str(response.get("backend_execution_id", ""))
        if not remote_id or not backend_id:
            raise RemoteAgentError(
                "REMOTE204",
                "remote agent returned an invalid execution handle",
            )
        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id=f"{payload.target}:{backend_id}",
            prepared=prepared,
            payload=RemoteExecutionPayload(
                client=payload.client,
                remote_execution_id=remote_id,
                backend_execution_id=backend_id,
                target=payload.target,
            ),
        )

    def _execution_payload(
        self,
        handle: BackendExecutionHandle,
    ) -> RemoteExecutionPayload:
        payload = handle.payload
        if not isinstance(payload, RemoteExecutionPayload):
            raise TypeError("RemoteProcessBackend handle contains invalid payload")
        return payload

    def _status(
        self,
        handle: BackendExecutionHandle,
        document: Mapping[str, Any],
    ) -> BackendExecutionStatus:
        try:
            state = BackendExecutionState(str(document["state"]))
        except (KeyError, ValueError) as exc:
            raise RemoteAgentError(
                "REMOTE205",
                "remote agent returned an invalid execution state",
            ) from exc
        details = dict(document.get("details") or {})
        details.update(
            {
                "remote": True,
                "remote_execution_id": self._execution_payload(
                    handle
                ).remote_execution_id,
            }
        )
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=state,
            message=(
                str(document["message"])
                if document.get("message") is not None
                else None
            ),
            details=details,
        )

    def _inspect(self, handle: BackendExecutionHandle) -> BackendExecutionStatus:
        payload = self._execution_payload(handle)
        document = payload.client.request(
            "inspect",
            {"remote_execution_id": payload.remote_execution_id},
        )
        return self._status(handle, document)

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        payload = self._execution_payload(handle)
        document = payload.client.request(
            "stop",
            {
                "remote_execution_id": payload.remote_execution_id,
                "timeout_seconds": timeout_seconds,
            },
        )
        return self._status(handle, document)


__all__ = [
    "RemoteExecutionPayload",
    "RemotePreparedPayload",
    "RemoteProcessBackend",
]
