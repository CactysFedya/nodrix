"""Provider-owned, pipeline-scoped integration sessions.

Sessions keep expensive control-plane resources (workspace preparation,
connections, graph watchers, process registries) out of individual Nodes.
They are deliberately small and transport-neutral so optional providers can
implement ROS 2, MQTT, Kafka, Zenoh, or other integrations without adding
provider-specific code to Plyctl Core.
"""

from __future__ import annotations

from typing import Any, Mapping

from .integration import ManagedResource, ResourceContext


SessionContext = ResourceContext


class Session(ManagedResource):
    """Compatibility name for a pipeline-scoped managed resource."""

    def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
        super().__init__(parameters)


__all__ = ["Session", "SessionContext"]
