"""Managed ROS 2 applications that stay outside the Nodrix data plane."""

from __future__ import annotations

from typing import Any, Mapping

from nodrix import ApplicationContext, ManagedApplication

from .nodes.process_nodes import (
    Ros2LaunchProcess,
    Ros2NodeProcess,
    Ros2RvizProcess,
    _Ros2ProcessSource,
)


class _Ros2ManagedApplication(ManagedApplication):
    process_class: type[_Ros2ProcessSource]

    def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
        super().__init__(parameters)
        self._process_node: _Ros2ProcessSource | None = None

    def configure(self, context: ApplicationContext) -> None:
        super().configure(context)
        node = self.process_class(dict(self.parameters))
        self._process_node = node
        node.configure(context)

    def start(self) -> None:
        node = self._require_node()
        super().start()
        node.start()
        node._start()

    def poll(self) -> dict[str, Any]:
        node = self._require_node()
        snapshot = node._process.snapshot()
        if snapshot.running:
            return node.health()
        if node._restart_if_allowed(snapshot.returncode):
            return node.health()
        allow_clean_exit = bool(
            node.parameters.get(
                "allow_clean_exit",
                node.process_kind == "ros2.rviz",
            )
        )
        if snapshot.returncode == 0 and allow_clean_exit:
            return {
                **node.health(),
                "status": "completed",
                "running": False,
            }
        raise RuntimeError(
            f"{node.process_kind} exited with code {snapshot.returncode}: "
            f"{node._process.stderr_tail().strip()}"
        )

    def health(self) -> dict[str, Any]:
        node = self._process_node
        if node is None:
            return super().health()
        return node.health()

    def stop(self) -> None:
        node = self._process_node
        self._process_node = None
        error: BaseException | None = None
        if node is not None:
            try:
                node.stop()
            except BaseException as exc:
                error = exc
        super().stop()
        if error is not None:
            raise error

    def _require_node(self) -> _Ros2ProcessSource:
        if self._process_node is None:
            raise RuntimeError("ROS 2 application is not configured")
        return self._process_node


class Ros2NodeApplication(_Ros2ManagedApplication):
    process_class = Ros2NodeProcess


class Ros2LaunchApplication(_Ros2ManagedApplication):
    process_class = Ros2LaunchProcess


class Ros2RvizApplication(_Ros2ManagedApplication):
    process_class = Ros2RvizProcess


__all__ = [
    "Ros2LaunchApplication",
    "Ros2NodeApplication",
    "Ros2RvizApplication",
]
