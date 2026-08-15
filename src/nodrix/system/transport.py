"""Runtime transport adapters for System boundary links.

The System model and planner already describe *what* a boundary link connects
and which transport it requests.  This module is the small runtime registry
that answers *how* a backend should realize that boundary.  A transport adapter
lowers one logical link into a sender SinkNode and a receiver SourceNode while
the existing Nodrix runtime remains responsible for scheduling those nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Mapping


TransportParameterValidator = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True, slots=True)
class TransportRuntimeAdapter:
    """Backend-neutral lowering contract for one transport implementation."""

    id: str
    sender_node: str
    receiver_node: str
    validate_parameters: TransportParameterValidator

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("transport runtime id must not be empty")
        if not self.sender_node.strip() or not self.receiver_node.strip():
            raise ValueError("transport runtime node ids must not be empty")

    def validate(self, parameters: Mapping[str, Any]) -> None:
        self.validate_parameters(parameters)


_TRANSPORTS: dict[str, TransportRuntimeAdapter] = {}
_LOCK = RLock()


def register_transport_runtime(
    adapter: TransportRuntimeAdapter,
    *,
    replace: bool = False,
) -> None:
    """Register a runtime adapter for ``SystemLink.uses``.

    Registration is intentionally explicit.  Provider discovery can wire this
    API later without changing the System model or backend contract.
    """

    key = adapter.id.strip()
    with _LOCK:
        if key in _TRANSPORTS and not replace:
            raise ValueError(f"transport runtime {key!r} is already registered")
        _TRANSPORTS[key] = adapter


def transport_runtime(uses: str | None) -> TransportRuntimeAdapter | None:
    if uses is None:
        return None
    with _LOCK:
        return _TRANSPORTS.get(uses)


def require_transport_runtime(uses: str | None) -> TransportRuntimeAdapter:
    adapter = transport_runtime(uses)
    if adapter is None:
        raise KeyError(uses)
    return adapter


def registered_transport_runtimes() -> tuple[str, ...]:
    with _LOCK:
        return tuple(sorted(_TRANSPORTS))


def _validate_tcp(parameters: Mapping[str, Any]) -> None:
    host = parameters.get("host")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("tcp transport requires non-empty parameter 'host'")

    raw_port = parameters.get("port")
    if isinstance(raw_port, bool):
        raise ValueError("tcp transport parameter 'port' must be an integer")
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("tcp transport requires integer parameter 'port'") from exc
    if not 1 <= port <= 65535:
        raise ValueError("tcp transport parameter 'port' must be between 1 and 65535")

    bind_host = parameters.get("bind_host", "0.0.0.0")
    if not isinstance(bind_host, str) or not bind_host.strip():
        raise ValueError("tcp transport parameter 'bind_host' must be non-empty")

    for name in ("connect_timeout_seconds", "retry_interval_seconds"):
        if name not in parameters:
            continue
        try:
            value = float(parameters[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"tcp transport parameter {name!r} must be numeric") from exc
        if value <= 0:
            raise ValueError(f"tcp transport parameter {name!r} must be positive")

    if "max_message_bytes" in parameters:
        try:
            max_message_bytes = int(parameters["max_message_bytes"])
        except (TypeError, ValueError) as exc:
            raise ValueError("tcp transport parameter 'max_message_bytes' must be an integer") from exc
        if max_message_bytes < 1024:
            raise ValueError("tcp transport 'max_message_bytes' must be at least 1024")


register_transport_runtime(
    TransportRuntimeAdapter(
        id="tcp",
        sender_node="core.transport_tcp_sink",
        receiver_node="core.transport_tcp_source",
        validate_parameters=_validate_tcp,
    )
)


__all__ = [
    "TransportRuntimeAdapter",
    "register_transport_runtime",
    "registered_transport_runtimes",
    "require_transport_runtime",
    "transport_runtime",
]
