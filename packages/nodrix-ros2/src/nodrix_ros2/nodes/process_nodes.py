from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping

from nodrix import Message, SourceNode

from ..commands import build_ros2_launch_command, build_ros2_run_command, build_rviz_command
from ..links import apply_topic_contracts, topic_contracts
from ..process import ManagedProcess
from ..workspace import RosWorkspaceManager, RosWorkspaceSpec


def _context_log_directory(context: Any) -> Path:
    for name in ("run_dir", "artifacts_dir", "output_dir"):
        value = getattr(context, name, None)
        if value:
            return Path(value) / "logs"
    return Path.cwd() / ".nodrix" / "logs"


def _project_path(context: Any, value: Any) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    if not path.is_absolute():
        path = Path(context.project_dir) / path
    return path.resolve()


def _topic_types(
    environment: Mapping[str, str],
    *,
    timeout_s: float,
) -> tuple[dict[str, set[str]], str | None]:
    try:
        completed = subprocess.run(
            ["ros2", "topic", "list", "-t"],
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=max(timeout_s, 0.05),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        return {}, detail
    result: dict[str, set[str]] = {}
    for line in completed.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        if " [" in text and text.endswith("]"):
            topic, types = text.split(" [", 1)
            result[topic.strip()] = {
                item.strip() for item in types[:-1].split(",") if item.strip()
            }
        else:
            result[text] = set()
    return result, None


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
                RosWorkspaceSpec.from_mapping(
                    workspace_value,
                    base_dir=Path(context.project_dir),
                ),
                project_dir=Path(context.project_dir),
                log_directory=log_directory,
            ).prepare()
        self._contracts = topic_contracts(
            context.external_links,
            node_name=str(context.name),
        )
        effective_parameters = apply_topic_contracts(
            self.parameters,
            process_kind=self.process_kind,
            contracts=self._contracts,
        )
        if self.process_kind == "ros2.rviz" and effective_parameters.get("config"):
            config = _project_path(context, effective_parameters["config"])
            if not config.is_file():
                raise FileNotFoundError(f"RViz config does not exist: {config}")
            effective_parameters["config"] = str(config)
        if self.process_kind == "ros2.node":
            parameter_files: list[str] = []
            for item in effective_parameters.get("params_files", ()):
                path = _project_path(context, item)
                if not path.is_file():
                    raise FileNotFoundError(
                        f"ROS parameter file does not exist: {path}"
                    )
                parameter_files.append(str(path))
            if parameter_files:
                effective_parameters["params_files"] = parameter_files
        self._command = self.command_builder(effective_parameters)
        name = str(getattr(context, "name", self.process_kind)).replace("/", "_")
        cwd_value = self.parameters.get("cwd")
        if cwd_value:
            cwd = _project_path(context, cwd_value)
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
        self._restart_count = 0

    def _requirements(self) -> tuple[dict[str, Any], ...]:
        raw = self.parameters.get("requires_topics", ())
        if isinstance(raw, str):
            raw = (raw,)
        elif not isinstance(raw, (list, tuple)):
            raise TypeError("requires_topics must be an array")
        result: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, str):
                result.append({"name": item})
            elif isinstance(item, Mapping):
                result.append(dict(item))
            else:
                raise TypeError("requires_topics entries must be strings or mappings")
        result.extend(
            {"name": item.topic, "message_type": item.message_type}
            for item in self._contracts
            if item.direction == "input"
        )
        deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
        for requirement in result:
            key = (
                str(requirement.get("name", "")).strip(),
                str(requirement.get("message_type", "")).strip(),
            )
            if not key[0]:
                raise ValueError("ROS topic requirement name cannot be empty")
            deduplicated.setdefault(key, requirement)
        return tuple(deduplicated.values())

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
        last_graph_error: str | None = None
        while not self._closed:
            remaining = max(deadline - time.monotonic(), 0.05)
            observed, graph_error = _topic_types(
                self._workspace.environment,
                timeout_s=min(5.0, remaining),
            )
            if graph_error:
                last_graph_error = graph_error
            missing: list[str] = []
            for requirement in requirements:
                name = str(requirement.get("name", "")).strip()
                expected = str(requirement.get("message_type", "")).strip()
                actual = observed.get(name)
                if actual is None or (expected and expected not in actual):
                    missing.append(name)
            if not missing:
                return
            if time.monotonic() >= deadline:
                detail = (
                    f"; ROS graph query failed: {last_graph_error}"
                    if last_graph_error
                    else ""
                )
                raise RuntimeError(
                    "ROS 2 topic requirements were not satisfied: "
                    + ", ".join(missing)
                    + detail
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
        failure = self._startup_failure()
        if failure is not None:
            returncode, detail = failure
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(
                f"{self.process_kind} failed during startup with code "
                f"{returncode}{suffix}"
            )

    def _startup_failure(self) -> tuple[int, str] | None:
        grace = max(float(self.parameters.get("startup_grace_s", 0.25)), 0.0)
        deadline = time.monotonic() + grace
        while not self._closed and time.monotonic() < deadline:
            returncode = self._process.poll()
            if returncode is not None:
                return returncode, self._process.stderr_tail().strip()
            time.sleep(min(0.02, max(deadline - time.monotonic(), 0.0)))
        return None

    def _restart_if_allowed(self, returncode: int | None) -> bool:
        policy = str(self.parameters.get("restart_policy", "none")).strip().lower()
        if policy not in {"none", "on-failure", "always"}:
            raise ValueError("restart_policy must be none, on-failure, or always")
        requested = policy == "always" or (
            policy == "on-failure" and returncode not in (None, 0)
        )
        maximum = max(int(self.parameters.get("max_restarts", 3)), 0)
        if not requested or self._restart_count >= maximum or self._closed:
            return False
        initial = max(float(self.parameters.get("restart_backoff_s", 0.5)), 0.0)
        maximum_backoff = max(
            float(self.parameters.get("restart_max_backoff_s", 30.0)),
            initial,
        )
        delay = min(initial * (2 ** self._restart_count), maximum_backoff)
        deadline = time.monotonic() + delay
        while not self._closed and time.monotonic() < deadline:
            time.sleep(min(0.05, max(deadline - time.monotonic(), 0.0)))
        if self._closed:
            return False
        self._restart_count += 1
        self._process.restart()
        self._startup_failure()
        return True

    def produce(self):
        self._start()
        heartbeat = max(float(self.parameters.get("heartbeat_interval_s", 1.0)), 0.05)
        allow_clean_exit = bool(
            self.parameters.get(
                "allow_clean_exit",
                self.process_kind == "ros2.rviz",
            )
        )
        while not self._closed:
            snapshot = self._process.snapshot()
            payload = {
                "kind": self.process_kind,
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
                "topic_contracts": [item.as_dict() for item in self._contracts],
                "restart_count": self._restart_count,
            }
            if bool(self.parameters.get("expose_command", False)):
                payload["command"] = list(self._command)
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
                if self._restart_if_allowed(snapshot.returncode):
                    continue
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
                "command_sha256": (
                    None if snapshot is None else snapshot.command_sha256
                ),
                "started": bool(getattr(self, "_started", False)),
                "pid": None if snapshot is None else snapshot.pid,
                "running": False if snapshot is None else snapshot.running,
                "returncode": None if snapshot is None else snapshot.returncode,
                "workspace_built": bool(
                    getattr(getattr(self, "_workspace", None), "built", False)
                ),
                "topic_contracts": [
                    item.as_dict() for item in getattr(self, "_contracts", ())
                ],
                "restart_count": int(getattr(self, "_restart_count", 0)),
            }
        )
        if bool(self.parameters.get("expose_command", False)):
            value["command"] = list(getattr(self, "_command", ()))
        return value

    def close(self) -> None:
        self._closed = True
        process = getattr(self, "_process", None)
        error: BaseException | None = None
        try:
            if process is not None:
                process.stop(
                    interrupt_timeout_s=float(
                        self.parameters.get("interrupt_timeout_s", 8.0)
                    ),
                    terminate_timeout_s=float(
                        self.parameters.get("terminate_timeout_s", 3.0)
                    ),
                )
        except BaseException as exc:
            error = exc
        finally:
            unregister = getattr(self._session, "unregister_process", None)
            if process is not None and callable(unregister):
                unregister(process)
            super().close()
        if error is not None:
            raise error


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
