from __future__ import annotations

import os
import sys
import threading
from typing import Any, Mapping, Sequence

from nodrix import Session, SessionContext

from .graph import RosGraphWatcher
from .process import ManagedProcess
from .workspace import RosWorkspaceManager, RosWorkspaceSpec, WorkspacePreparation


_ACTIVATION_LOCK = threading.Lock()
_ACTIVE_ENVIRONMENT_ID: tuple[str, ...] | None = None
_ACTIVE_ENVIRONMENT_USERS = 0
_ACTIVE_PREVIOUS_ENVIRONMENT: dict[str, str | None] = {}
_ACTIVE_SYS_PATH_ENTRIES: list[str] = []


class Ros2Session(Session):
    """One prepared ROS environment, graph worker, and process registry."""

    def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
        super().__init__(parameters)
        self.preparation: WorkspacePreparation | None = None
        self._graph: RosGraphWatcher | None = None
        self._processes: set[ManagedProcess] = set()
        self._lock = threading.RLock()
        self._python_environment_active = False

    def open(self, context: SessionContext) -> None:
        super().open(context)
        spec = RosWorkspaceSpec.from_mapping(self.parameters)
        manager = RosWorkspaceManager(
            spec,
            project_dir=context.project_dir,
            log_directory=context.run_dir / "logs",
        )
        self.preparation = manager.prepare()
        worker_command = self.parameters.get("graph_worker_command")
        command: Sequence[str] | None = None
        if isinstance(worker_command, (list, tuple)):
            command = tuple(str(item) for item in worker_command)
        self._graph = RosGraphWatcher(
            environment=self.preparation.environment,
            run_dir=context.run_dir,
            command=command,
            interval_s=float(self.parameters.get("graph_interval_s", 0.2)),
        )

    @property
    def environment(self) -> Mapping[str, str]:
        if self.preparation is None:
            raise RuntimeError("ROS 2 session is not open")
        return self.preparation.environment

    @property
    def graph(self) -> RosGraphWatcher:
        if self._graph is None:
            raise RuntimeError("ROS 2 session is not open")
        return self._graph

    def activate_python_environment(self) -> None:
        """Make sourced Python packages visible to an explicit rclpy bridge.

        Large ROS-to-ROS paths stay in DDS. This compatibility path exists for
        an explicit in-process bridge and rejects conflicting ROS sessions.
        """

        global _ACTIVE_ENVIRONMENT_ID, _ACTIVE_ENVIRONMENT_USERS
        global _ACTIVE_PREVIOUS_ENVIRONMENT, _ACTIVE_SYS_PATH_ENTRIES
        environment = dict(self.environment)
        identity = tuple(
            environment.get(name, "")
            for name in ("ROS_DISTRO", "AMENT_PREFIX_PATH", "PYTHONPATH")
        )
        with _ACTIVATION_LOCK:
            if self._python_environment_active:
                return
            if _ACTIVE_ENVIRONMENT_ID not in (None, identity):
                raise RuntimeError(
                    "Conflicting ROS Python environments cannot share one "
                    "Nodrix process; use process isolation"
                )
            if _ACTIVE_ENVIRONMENT_ID is None:
                _ACTIVE_ENVIRONMENT_ID = identity
                _ACTIVE_PREVIOUS_ENVIRONMENT = {
                    name: os.environ.get(name) for name in environment
                }
                os.environ.update(environment)
                inserted: list[str] = []
                for entry in reversed(
                    environment.get("PYTHONPATH", "").split(os.pathsep)
                ):
                    if entry and entry not in sys.path:
                        sys.path.insert(0, entry)
                        inserted.append(entry)
                _ACTIVE_SYS_PATH_ENTRIES = inserted
            _ACTIVE_ENVIRONMENT_USERS += 1
            self._python_environment_active = True

    def _deactivate_python_environment(self) -> None:
        global _ACTIVE_ENVIRONMENT_ID, _ACTIVE_ENVIRONMENT_USERS
        global _ACTIVE_PREVIOUS_ENVIRONMENT, _ACTIVE_SYS_PATH_ENTRIES
        with _ACTIVATION_LOCK:
            if not self._python_environment_active:
                return
            self._python_environment_active = False
            _ACTIVE_ENVIRONMENT_USERS = max(_ACTIVE_ENVIRONMENT_USERS - 1, 0)
            if _ACTIVE_ENVIRONMENT_USERS:
                return
            for name, previous in _ACTIVE_PREVIOUS_ENVIRONMENT.items():
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous
            for entry in _ACTIVE_SYS_PATH_ENTRIES:
                try:
                    sys.path.remove(entry)
                except ValueError:
                    pass
            _ACTIVE_PREVIOUS_ENVIRONMENT = {}
            _ACTIVE_SYS_PATH_ENTRIES = []
            _ACTIVE_ENVIRONMENT_ID = None

    def register_process(self, process: ManagedProcess) -> None:
        with self._lock:
            self._processes.add(process)

    def unregister_process(self, process: ManagedProcess) -> None:
        with self._lock:
            self._processes.discard(process)

    def health(self) -> dict[str, Any]:
        graph = self._graph
        with self._lock:
            running = sum(item.snapshot().running for item in self._processes)
        return {
            "status": "ok" if self.preparation is not None else "closed",
            "workspace_built": bool(self.preparation and self.preparation.built),
            "workspace_fingerprint": (
                None if self.preparation is None else self.preparation.fingerprint
            ),
            "managed_processes": running,
            "graph": {} if graph is None else graph.health(),
        }

    def close(self) -> None:
        self._deactivate_python_environment()
        graph = self._graph
        self._graph = None
        if graph is not None:
            graph.close()
        with self._lock:
            processes = tuple(self._processes)
            self._processes.clear()
        for process in reversed(processes):
            process.stop(interrupt_timeout_s=2.0, terminate_timeout_s=1.0)
        self.preparation = None
        super().close()


__all__ = ["Ros2Session"]
