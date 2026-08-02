from __future__ import annotations

from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping

from nodrix import Message, SourceNode

from ..commands import build_ros2_launch_command, build_ros2_run_command, build_rviz_command
from ..process import ManagedProcess
from ..workspace import RosWorkspaceManager, RosWorkspaceSpec


def _context_log_directory(context: Any) -> Path:
    for name in ("run_dir", "artifacts_dir", "output_dir"):
        value = getattr(context, name, None)
        if value:
            return Path(value) / "logs"
    return Path.cwd() / ".nodrix" / "logs"


def _topic_types(environment: Mapping[str, str]) -> dict[str, str]:
    completed = subprocess.run(
        ["ros2", "topic", "list", "-t"],
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=5.0,
    )
    if completed.returncode != 0:
        return {}
    result: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        if " [" in text and text.endswith("]"):
            topic, types = text.split(" [", 1)
            result[topic.strip()] = types[:-1].split(",", 1)[0].strip()
        else:
            result[text] = ""
    return result


class _Ros2ProcessSource(SourceNode):
    output_types = {"status": "core.object"}
    command_builder: Callable[[Mapping[str, Any]], tuple[str, ...]]
    process_kind = "ros2.process"

    def open(self, context: Any) -> None:
        super().open(context)
        self._closed = False
        self._sequence = 0
        self._context = context
        self._session = context.binding("session", required=False)
        workspace_value = self.parameters.get("workspace")
        if workspace_value is not None and not isinstance(workspace_value, Mapping):
            raise TypeError("parameters.workspace must be a mapping")
        log_directory = _context_log_directory(context)
        if self._session is not None:
            preparation = getattr(self._session, "preparation", None)
            if preparation is None:
                raise RuntimeError("Bound ROS 2 session is not prepared")
            self._workspace = preparation
        else:
            self._workspace = RosWorkspaceManager(
                RosWorkspaceSpec.from_mapping(workspace_value),
                project_dir=Path(context.project_dir),
                log_directory=log_directory,
            ).prepare()
        effective_parameters = dict(self.parameters)
        if self.process_kind == "ros2.node":
            remappings = dict(effective_parameters.get("remappings") or {})
            for link in context.external_links:
                if str(link.get("uses")) != "ros2.topic":
                    continue
                parameters = dict(link.get("parameters") or {})
                topic = str(parameters.get("topic", "")).strip()
                if not topic:
                    continue
                source_node, source_port = str(link.get("from", "")).split(".", 1)
                target_node, target_port = str(link.get("to", "")).split(".", 1)
                if source_node == context.name:
                    remappings.setdefault(source_port, topic)
                if target_node == context.name:
                    remappings.setdefault(target_port, topic)
            if remappings:
                effective_parameters["remappings"] = remappings
        self._command = self.command_builder(effective_parameters)
        name = str(getattr(context, "name", self.process_kind)).replace("/", "_")
        cwd_value = self.parameters.get("cwd")
        if cwd_value:
            cwd = Path(str(cwd_value)).expanduser().resolve()
        else:
            cwd = None
            for attribute in ("project_dir", "base_dir", "work_dir"):
                candidate = getattr(context, attribute, None)
                if candidate:
                    cwd = Path(candidate).resolve()
                    break
        self._process = ManagedProcess(
            self._command,
            cwd=cwd,
            environment=self._workspace.environment,
            stdout_path=log_directory / f"{name}.stdout.log",
            stderr_path=log_directory / f"{name}.stderr.log",
            max_log_bytes=int(self.parameters.get("maximum_log_bytes", 50 * 1024 * 1024)),
            log_rotations=int(self.parameters.get("log_rotations", 3)),
        )
        register = getattr(self._session, "register_process", None)
        if callable(register):
            register(self._process)
        self._started = False

    def _requirements(self) -> tuple[dict[str, Any], ...]:
        raw = self.parameters.get("requires_topics", ())
        result: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, str):
                result.append({"name": item})
            elif isinstance(item, Mapping):
                result.append(dict(item))
            else:
                raise TypeError("requires_topics entries must be strings or mappings")
        for link in self._context.external_links:
            if str(link.get("uses")) != "ros2.topic":
                continue
            target_node = str(link.get("to", "")).split(".", 1)[0]
            if target_node != self._context.name:
                continue
            parameters = dict(link.get("parameters") or {})
            topic = str(parameters.get("topic", "")).strip()
            if topic:
                result.append(
                    {
                        "name": topic,
                        "message_type": str(parameters.get("message_type", "")),
                    }
                )
        return tuple(result)

    def _wait_requirements(self) -> None:
        requirements = self._requirements()
        if not requirements:
            return
        timeout = max(float(self.parameters.get("requirements_timeout_s", 30.0)), 0.1)
        graph = getattr(self._session, "graph", None)
        if graph is not None:
            graph.wait_topics(
                requirements,
                timeout_s=timeout,
                cancelled=lambda: self._closed,
            )
            return
        interval = max(float(self.parameters.get("requirements_poll_s", 0.25)), 0.05)
        deadline = time.monotonic() + timeout
        while not self._closed:
            observed = _topic_types(self._workspace.environment)
            missing: list[str] = []
            for requirement in requirements:
                name = str(requirement.get("name", "")).strip()
                expected = str(requirement.get("message_type", "")).strip()
                actual = observed.get(name)
                if actual is None or (expected and actual != expected):
                    missing.append(name)
            if not missing:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "ROS 2 topic requirements were not satisfied: " + ", ".join(missing)
                )
            time.sleep(interval)

    def _start(self) -> None:
        if self._started:
            return
        self._wait_requirements()
        if self._closed:
            return
        self._process.start()
        self._started = True

    def produce(self):
        self._start()
        heartbeat = max(float(self.parameters.get("heartbeat_interval_s", 1.0)), 0.05)
        allow_clean_exit = bool(self.parameters.get("allow_clean_exit", False))
        while not self._closed:
            snapshot = self._process.snapshot()
            payload = {
                "kind": self.process_kind,
                "command": list(self._command),
                "pid": snapshot.pid,
                "running": snapshot.running,
                "returncode": snapshot.returncode,
                "uptime_s": snapshot.uptime_s,
                "workspace_built": self._workspace.built,
                "workspace_fingerprint": self._workspace.fingerprint,
                "command_sha256": snapshot.command_sha256,
                "session": (
                    None
                    if self._session is None
                    else str(getattr(getattr(self._session, "context", None), "name", "ros"))
                ),
            }
            yield {
                "status": Message(
                    type="core.object",
                    payload=payload,
                    sequence=self._sequence,
                    timestamp_ns=time.time_ns(),
                    stream_id=str(getattr(self._context, "name", self.process_kind)),
                    trace_id=self._sequence,
                )
            }
            self._sequence += 1
            if not snapshot.running:
                if snapshot.returncode == 0 and allow_clean_exit:
                    return
                raise RuntimeError(
                    f"{self.process_kind} exited with code {snapshot.returncode}"
                )
            time.sleep(heartbeat)

    def health(self) -> dict[str, Any]:
        value = dict(super().health())
        snapshot = self._process.snapshot() if hasattr(self, "_process") else None
        value.update(
            {
                "kind": self.process_kind,
                "command": list(getattr(self, "_command", ())),
                "started": bool(getattr(self, "_started", False)),
                "pid": None if snapshot is None else snapshot.pid,
                "running": False if snapshot is None else snapshot.running,
                "returncode": None if snapshot is None else snapshot.returncode,
                "workspace_built": bool(
                    getattr(getattr(self, "_workspace", None), "built", False)
                ),
            }
        )
        return value

    def close(self) -> None:
        self._closed = True
        process = getattr(self, "_process", None)
        if process is not None:
            process.stop(
                interrupt_timeout_s=float(self.parameters.get("interrupt_timeout_s", 8.0)),
                terminate_timeout_s=float(self.parameters.get("terminate_timeout_s", 3.0)),
            )
            unregister = getattr(self._session, "unregister_process", None)
            if callable(unregister):
                unregister(process)


class Ros2NodeProcess(_Ros2ProcessSource):
    """Run one installed ROS 2 executable under Nodrix lifecycle control."""

    command_builder = staticmethod(build_ros2_run_command)
    process_kind = "ros2.node"


class Ros2LaunchProcess(_Ros2ProcessSource):
    """Run an existing ROS 2 launch file without an algorithm-specific plugin."""

    command_builder = staticmethod(build_ros2_launch_command)
    process_kind = "ros2.launch"


class Ros2RvizProcess(_Ros2ProcessSource):
    """Run RViz as an optional supervised visualization process."""

    command_builder = staticmethod(build_rviz_command)
    process_kind = "ros2.rviz"
