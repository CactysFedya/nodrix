from __future__ import annotations

from dataclasses import dataclass, field, replace
import time
from typing import Any


@dataclass(slots=True)
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
    metadata: dict[str, Any] = field(default_factory=dict)
    created_ns: int = field(default_factory=time.perf_counter_ns)
    lease: Any | None = field(default=None, repr=False, compare=False)

    def with_updates(self, **changes: Any) -> "Message":
        return replace(self, **changes)
