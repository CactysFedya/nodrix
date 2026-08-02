from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from .process import ManagedProcess


class RosGraphWatcher:
    """One persistent ROS graph observer shared by an entire pipeline."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        run_dir: Path,
        command: Sequence[str] | None = None,
        interval_s: float = 0.2,
    ) -> None:
        self.environment = dict(environment)
        self.run_dir = run_dir
        self.snapshot_path = run_dir / "ros2" / "graph.json"
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.command = tuple(
            command
            or (
                sys.executable,
                "-m",
                "nodrix_ros2.worker",
                "--snapshot",
                str(self.snapshot_path),
                "--interval",
                str(max(float(interval_s), 0.05)),
            )
        )
        self._process: ManagedProcess | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._process is not None and self._process.snapshot().running:
                return
            process = ManagedProcess(
                self.command,
                cwd=self.run_dir,
                environment=self.environment,
                stdout_path=self.run_dir / "logs" / "ros-graph.stdout.log",
                stderr_path=self.run_dir / "logs" / "ros-graph.stderr.log",
            )
            process.start()
            self._process = process

    def snapshot(self) -> dict[str, Any]:
        self.start()
        try:
            value = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        if not isinstance(value, dict):
            return {}
        process = self._process
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                "ROS graph worker exited unexpectedly: "
                + process.stderr_tail().strip()
            )
        if value.get("status") == "error":
            raise RuntimeError(
                "ROS graph worker failed: " + str(value.get("error", "unknown"))
            )
        return value

    def wait_topics(
        self,
        requirements: Sequence[Mapping[str, Any]],
        *,
        timeout_s: float,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(float(timeout_s), 0.1)
        missing: list[str] = []
        while cancelled is None or not cancelled():
            snapshot = self.snapshot()
            topics = dict(snapshot.get("topics") or {})
            missing = []
            for requirement in requirements:
                name = str(requirement.get("name", "")).strip()
                expected = str(requirement.get("message_type", "")).strip()
                state = dict(topics.get(name) or {})
                types = {str(item) for item in state.get("types") or []}
                publishers = int(state.get("publishers", 0))
                if not state or publishers <= 0 or (expected and expected not in types):
                    missing.append(name)
            if not missing:
                return snapshot
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "ROS 2 topic requirements were not satisfied: "
                    + ", ".join(missing)
                )
            time.sleep(0.05)
        raise RuntimeError("ROS graph wait was cancelled")

    def health(self) -> dict[str, Any]:
        process = self._process
        snapshot = self.snapshot() if process is not None else {}
        return {
            "status": str(snapshot.get("status", "idle")),
            "worker_running": bool(process and process.snapshot().running),
            "topics": len(dict(snapshot.get("topics") or {})),
            "updated_ns": snapshot.get("updated_ns"),
        }

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is not None:
            process.stop(interrupt_timeout_s=2.0, terminate_timeout_s=1.0)


__all__ = ["RosGraphWatcher"]
