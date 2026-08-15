"""Transport-neutral lifecycle contracts for external integrations.

The classes in this module deliberately know nothing about ROS, DDS, brokers,
containers, or a particular process supervisor.  Providers use resources for
pipeline-scoped dependencies and applications for externally managed work
that has a lifecycle but does not move messages through a Plyctl queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ResourceContext:
    """Context supplied while opening a provider-owned resource."""

    name: str
    run_dir: Path
    project_dir: Path
    runtime_mode: str
    bindings: Mapping[str, Any] = field(default_factory=dict)

    def binding(self, name: str = "session", *, required: bool = True) -> Any:
        value = self.bindings.get(name)
        if value is None and required:
            raise RuntimeError(f"Resource {self.name!r} has no binding {name!r}")
        return value


@dataclass(slots=True)
class ApplicationContext:
    """Context supplied while configuring a managed external application."""

    name: str
    run_dir: Path
    project_dir: Path
    runtime_mode: str
    bindings: Mapping[str, Any] = field(default_factory=dict)
    external_links: tuple[Mapping[str, Any], ...] = ()

    def binding(self, name: str = "session", *, required: bool = True) -> Any:
        value = self.bindings.get(name)
        if value is None and required:
            raise RuntimeError(
                f"Application {self.name!r} has no binding {name!r}"
            )
        return value


class ManagedResource:
    """Base class for one pipeline-scoped integration resource.

    A resource may represent a connection pool, environment, workspace,
    credentials handle, graph watcher, broker client, or any equivalent
    provider-owned dependency.  ``open`` and ``close`` may be synchronous or
    return awaitables; the unified runtime handles both forms.
    """

    def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
        self.parameters = dict(parameters or {})
        self.context: ResourceContext | None = None
        self._resource_lock = threading.RLock()

    def open(self, context: ResourceContext) -> Any:
        with self._resource_lock:
            if self.context is not None:
                raise RuntimeError("Resource is already open")
            self.context = context
        return None

    def close(self) -> Any:
        with self._resource_lock:
            self.context = None
        return None

    def health(self) -> dict[str, Any]:
        with self._resource_lock:
            opened = self.context is not None
        return {
            "status": "ok" if opened else "closed",
            "open": opened,
        }


class ManagedApplication:
    """Base lifecycle for external work supervised by a provider.

    Applications are control-plane objects, not synthetic ``SourceNode``
    instances.  They therefore do not need heartbeat messages or dummy graph
    edges merely to keep an external process alive.
    """

    def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
        self.parameters = dict(parameters or {})
        self.context: ApplicationContext | None = None
        self._application_lock = threading.RLock()
        self._state = "created"

    def configure(self, context: ApplicationContext) -> Any:
        with self._application_lock:
            if self._state != "created":
                raise RuntimeError(
                    f"Application cannot configure from state {self._state!r}"
                )
            self.context = context
            self._state = "ready"
        return None

    def start(self) -> Any:
        with self._application_lock:
            if self._state != "ready":
                raise RuntimeError(
                    f"Application cannot start from state {self._state!r}"
                )
            self._state = "running"
        return None

    def poll(self) -> Mapping[str, Any] | None | Any:
        """Return lightweight state or raise when supervision detects failure."""

        return self.health()

    def stop(self) -> Any:
        with self._application_lock:
            if self._state == "stopped":
                return None
            self._state = "stopped"
            self.context = None
        return None

    @property
    def lifecycle_state(self) -> str:
        with self._application_lock:
            return self._state

    def health(self) -> dict[str, Any]:
        with self._application_lock:
            state = self._state
        return {
            "status": "ok" if state in {"ready", "running"} else state,
            "state": state,
            "running": state == "running",
        }


__all__ = [
    "ApplicationContext",
    "ManagedApplication",
    "ManagedResource",
    "ResourceContext",
]
