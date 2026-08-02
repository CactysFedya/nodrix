from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields, is_dataclass, replace
import time
from typing import Any


class FrozenMetadata(dict[str, Any]):
    """JSON-compatible immutable metadata carried by a Message envelope."""

    def __init__(self, value: Any = None, **kwargs: Any) -> None:
        source = dict(value or {}, **kwargs)
        dict.__init__(
            self,
            {
                key: self._freeze(item)
                for key, item in source.items()
            },
        )

    @classmethod
    def _freeze(cls, value: Any) -> Any:
        if isinstance(value, FrozenMetadata):
            return value
        if isinstance(value, dict):
            return cls(value)
        if isinstance(value, (list, tuple)):
            return tuple(cls._freeze(item) for item in value)
        if isinstance(value, (set, frozenset)):
            return frozenset(cls._freeze(item) for item in value)
        return value

    def __copy__(self) -> FrozenMetadata:
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> FrozenMetadata:
        return self

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("Nodrix Message metadata is immutable; use with_updates()")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


@dataclass(frozen=True, slots=True)
class Message:
    """Typed message passed between Nodrix nodes.

    ``payload`` is retained by reference.  ``created_ns`` uses the monotonic
    clock and enables end-to-end latency measurement without changing the user
    payload or relying on wall-clock timestamps.
    """

    type: str
    payload: Any
    sequence: int = 0
    timestamp_ns: int = field(default_factory=time.time_ns)
    stream_id: str = ""
    trace_id: int | str = 0
    span_id: str = ""
    pipeline_id: str = ""
    run_id: str = ""
    source_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_ns: int = field(default_factory=time.perf_counter_ns)
    lease: Any | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, FrozenMetadata):
            object.__setattr__(
                self,
                "metadata",
                FrozenMetadata(copy.deepcopy(self.metadata)),
            )

    def with_updates(self, **changes: Any) -> "Message":
        return replace(self, **changes)

    def fork(self) -> "Message":
        """Create one independently releasable zero-copy delivery envelope."""

        from .cv_types import ManagedBuffer

        payload = self.payload
        direct_buffer = isinstance(payload, ManagedBuffer)
        payload_buffer = payload if direct_buffer else getattr(payload, "buffer", None)
        changes: dict[str, Any] = {}
        if isinstance(payload_buffer, ManagedBuffer):
            shared = payload_buffer.share(readonly=True)
            if direct_buffer:
                payload = shared
            elif is_dataclass(payload):
                changes["buffer"] = shared
            else:
                raise TypeError(
                    f"Payload {type(payload).__name__} exposes a ManagedBuffer "
                    "but is not a dataclass and cannot be shared safely"
                )
        if is_dataclass(payload) and not direct_buffer:
            for definition in fields(payload):
                if definition.name == "buffer":
                    continue
                value = getattr(payload, definition.name)
                if isinstance(value, (dict, list, set, bytearray)):
                    changes[definition.name] = copy.deepcopy(value)
                elif hasattr(value, "flags") and hasattr(value, "view"):
                    view = value.view()
                    try:
                        view.flags.writeable = False
                    except (AttributeError, ValueError):
                        pass
                    changes[definition.name] = view
            payload = replace(payload, **changes)
        elif isinstance(payload, (dict, list, set, bytearray)):
            payload = copy.deepcopy(payload)
        elif hasattr(payload, "flags") and hasattr(payload, "view"):
            payload = payload.view()
            try:
                payload.flags.writeable = False
            except (AttributeError, ValueError):
                pass
        delivery_lease = self.lease
        if isinstance(delivery_lease, ManagedBuffer):
            delivery_lease = delivery_lease.share(readonly=True)
        elif delivery_lease is not None and hasattr(delivery_lease, "retain"):
            delivery_lease = delivery_lease.retain()
        return replace(
            self,
            payload=payload,
            metadata=self.metadata,
            lease=delivery_lease,
        )
