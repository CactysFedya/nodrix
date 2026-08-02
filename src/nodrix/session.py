"""Provider-owned, pipeline-scoped integration sessions.

Sessions keep expensive control-plane resources (workspace preparation,
connections, graph watchers, process registries) out of individual Nodes.
They are deliberately small and transport-neutral so optional providers can
implement ROS 2, MQTT, Kafka, Zenoh, or other integrations without adding
provider-specific code to Nodrix Core.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SessionContext:
    name: str
    run_dir: Path
    project_dir: Path
    runtime_mode: str


class Session:
    """Base class for one pipeline-scoped provider resource."""

    def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
        self.parameters = dict(parameters or {})
        self.context: SessionContext | None = None

    def open(self, context: SessionContext) -> Any:
        self.context = context
        return None

    def close(self) -> Any:
        self.context = None
        return None

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "open": self.context is not None}


__all__ = ["Session", "SessionContext"]
