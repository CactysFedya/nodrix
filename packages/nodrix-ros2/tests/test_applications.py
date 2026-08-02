from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from nodrix import ApplicationContext
from nodrix_ros2.applications import _Ros2ManagedApplication


@dataclass
class _Snapshot:
    running: bool
    returncode: int | None


class _Process:
    def __init__(self) -> None:
        self.snapshot_value = _Snapshot(running=True, returncode=None)

    def snapshot(self) -> _Snapshot:
        return self.snapshot_value

    @staticmethod
    def stderr_tail() -> str:
        return "process failed"


class _FakeProcessNode:
    process_kind = "ros2.launch"

    def __init__(self, parameters: dict[str, object]) -> None:
        self.parameters = parameters
        self._process = _Process()
        self.events: list[str] = []

    def configure(self, context: ApplicationContext) -> None:
        self.context = context
        self.events.append("configure")

    def start(self) -> None:
        self.events.append("start")

    def _start(self) -> None:
        self.events.append("process-start")

    def _restart_if_allowed(self, returncode: int | None) -> bool:
        return False

    def health(self) -> dict[str, object]:
        snapshot = self._process.snapshot()
        return {
            "status": "ok",
            "running": snapshot.running,
            "returncode": snapshot.returncode,
        }

    def stop(self) -> None:
        self.events.append("stop")


class _FakeApplication(_Ros2ManagedApplication):
    process_class = _FakeProcessNode


def _context(tmp_path: Path) -> ApplicationContext:
    return ApplicationContext(
        name="mapping",
        run_dir=tmp_path,
        project_dir=tmp_path,
        runtime_mode="realtime",
    )


def test_managed_ros_application_has_control_plane_lifecycle(
    tmp_path: Path,
) -> None:
    application = _FakeApplication({"package": "demo"})
    application.configure(_context(tmp_path))
    application.start()

    node = application._require_node()
    assert node.events == ["configure", "start", "process-start"]
    assert application.poll()["running"] is True

    application.stop()
    assert node.events[-1] == "stop"
    assert application.lifecycle_state == "stopped"


def test_managed_ros_application_reports_clean_completion(
    tmp_path: Path,
) -> None:
    application = _FakeApplication({"allow_clean_exit": True})
    application.configure(_context(tmp_path))
    application.start()
    application._require_node()._process.snapshot_value = _Snapshot(
        running=False,
        returncode=0,
    )

    assert application.poll()["status"] == "completed"


def test_managed_ros_application_propagates_process_failure(
    tmp_path: Path,
) -> None:
    application = _FakeApplication()
    application.configure(_context(tmp_path))
    application.start()
    application._require_node()._process.snapshot_value = _Snapshot(
        running=False,
        returncode=2,
    )

    with pytest.raises(RuntimeError, match="process failed"):
        application.poll()
