from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import blake2b
import json
import os
from pathlib import Path
import shlex
import subprocess
import threading
import time
from typing import Any, Mapping, Sequence


_RELEVANT_NAMES = {"package.xml", "CMakeLists.txt", "setup.py", "setup.cfg", "pyproject.toml"}
_RELEVANT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".py", ".xml", ".yaml", ".yml", ".json", ".rviz", ".launch",
}
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _expand_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def _path_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def resolve_setup_file(value: str | os.PathLike[str]) -> Path:
    path = _expand_path(value)
    candidates = (
        path,
        path / "setup.bash",
        path / "install" / "setup.bash",
        path / "local_setup.bash",
        path / "install" / "local_setup.bash",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"ROS 2 setup file not found for {path}")


def capture_sourced_environment(
    setup_files: Sequence[Path],
    *,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if base_environment is None else base_environment)
    commands = ["set -euo pipefail"]
    commands.extend(f"source {shlex.quote(str(path))}" for path in setup_files)
    commands.append("env -0")
    completed = subprocess.run(
        ["bash", "-lc", "; ".join(commands)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    result: dict[str, str] = {}
    for item in completed.stdout.split(b"\0"):
        if not item or b"=" not in item:
            continue
        name, value = item.split(b"=", 1)
        result[name.decode(errors="surrogateescape")] = value.decode(
            errors="surrogateescape"
        )
    return result


@dataclass(frozen=True, slots=True)
class RosBuildSpec:
    mode: str = "if-needed"
    symlink_install: bool = True
    packages_select: tuple[str, ...] = ()
    packages_up_to: tuple[str, ...] = ()
    parallel_workers: int | None = None
    strict_fingerprint: bool = False
    extra_args: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RosBuildSpec":
        data = dict(value or {})
        mode = str(data.get("mode", "if-needed")).strip().lower()
        if mode not in {"never", "if-needed", "always"}:
            raise ValueError("ROS build mode must be never, if-needed, or always")
        workers = data.get("parallel_workers")
        packages_select = tuple(str(x) for x in data.get("packages_select", ()))
        packages_up_to = tuple(str(x) for x in data.get("packages_up_to", ()))
        if packages_select and packages_up_to:
            raise ValueError("Use either packages_select or packages_up_to, not both")
        return cls(
            mode=mode,
            symlink_install=bool(data.get("symlink_install", True)),
            packages_select=packages_select,
            packages_up_to=packages_up_to,
            parallel_workers=(None if workers in (None, "auto") else max(int(workers), 1)),
            strict_fingerprint=bool(data.get("strict_fingerprint", False)),
            extra_args=tuple(str(x) for x in data.get("extra_args", ())),
        )


@dataclass(frozen=True, slots=True)
class RosWorkspaceSpec:
    distro: str = "jazzy"
    underlays: tuple[Path, ...] = ()
    path: Path | None = None
    build: RosBuildSpec = field(default_factory=RosBuildSpec)
    environment: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RosWorkspaceSpec":
        data = dict(value or {})
        distro = str(data.get("distro") or os.environ.get("ROS_DISTRO") or "jazzy")
        raw_underlays = list(data.get("underlays", ()))
        if not raw_underlays:
            raw_underlays.append(f"/opt/ros/{distro}")
        path_value = data.get("path")
        return cls(
            distro=distro,
            underlays=tuple(_expand_path(item) for item in raw_underlays),
            path=None if not path_value else _expand_path(path_value),
            build=RosBuildSpec.from_mapping(data.get("build")),
            environment={str(k): str(v) for k, v in dict(data.get("environment") or {}).items()},
        )


@dataclass(frozen=True, slots=True)
class WorkspacePreparation:
    environment: Mapping[str, str]
    setup_files: tuple[Path, ...]
    built: bool
    fingerprint: str | None
    command: tuple[str, ...] = ()
    duration_s: float = 0.0


def workspace_fingerprint(workspace: Path, *, strict: bool = False) -> str:
    source = workspace / "src"
    if not source.is_dir():
        return "missing-src"
    digest = blake2b(digest_size=20)
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if path.name not in _RELEVANT_NAMES and path.suffix.lower() not in _RELEVANT_SUFFIXES:
            continue
        relative = path.relative_to(workspace).as_posix().encode()
        stat = path.stat()
        digest.update(relative)
        digest.update(str(stat.st_size).encode())
        digest.update(str(stat.st_mtime_ns).encode())
        if strict:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _cache_file(workspace: Path) -> Path:
    return workspace / ".nodrix" / "ros2-build.json"


def _read_cache(workspace: Path) -> dict[str, Any]:
    path = _cache_file(workspace)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_cache(workspace: Path, value: Mapping[str, Any]) -> None:
    path = _cache_file(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_command(spec: RosBuildSpec) -> tuple[str, ...]:
    command: list[str] = ["colcon", "build"]
    if spec.symlink_install:
        command.append("--symlink-install")
    if spec.parallel_workers:
        command.extend(["--parallel-workers", str(spec.parallel_workers)])
    if spec.packages_select:
        command.append("--packages-select")
        command.extend(spec.packages_select)
    if spec.packages_up_to:
        command.append("--packages-up-to")
        command.extend(spec.packages_up_to)
    command.extend(spec.extra_args)
    return tuple(command)


class RosWorkspaceManager:
    """Prepare one ROS 2 environment and build an overlay only when required."""

    def __init__(self, spec: RosWorkspaceSpec) -> None:
        self.spec = spec

    def prepare(self) -> WorkspacePreparation:
        lock_path = self.spec.path or self.spec.underlays[0]
        with _path_lock(lock_path):
            return self._prepare_locked()

    def _prepare_locked(self) -> WorkspacePreparation:
        underlay_setups = tuple(resolve_setup_file(path) for path in self.spec.underlays)
        build_environment = capture_sourced_environment(underlay_setups)
        build_environment.update(self.spec.environment)
        built = False
        command: tuple[str, ...] = ()
        fingerprint: str | None = None
        duration_s = 0.0

        if self.spec.path is not None:
            workspace = self.spec.path
            if not workspace.is_dir():
                raise FileNotFoundError(f"ROS workspace does not exist: {workspace}")
            fingerprint = workspace_fingerprint(
                workspace,
                strict=self.spec.build.strict_fingerprint,
            )
            install_setup = workspace / "install" / "setup.bash"
            cached = _read_cache(workspace)
            needs_build = self.spec.build.mode == "always"
            if self.spec.build.mode == "if-needed":
                needs_build = (
                    not install_setup.is_file()
                    or cached.get("fingerprint") != fingerprint
                    or cached.get("command") != list(build_command(self.spec.build))
                )
            if self.spec.build.mode == "never" and not install_setup.is_file():
                raise RuntimeError(
                    f"ROS workspace is not built and build.mode=never: {workspace}"
                )
            if needs_build:
                if not (workspace / "src").is_dir():
                    raise RuntimeError(f"ROS workspace has no src directory: {workspace}")
                command = build_command(self.spec.build)
                started = time.monotonic()
                subprocess.run(
                    list(command),
                    cwd=workspace,
                    env=build_environment,
                    check=True,
                )
                duration_s = time.monotonic() - started
                built = True
                if not install_setup.is_file():
                    raise RuntimeError(
                        f"colcon completed but install/setup.bash is missing: {workspace}"
                    )
                _write_cache(
                    workspace,
                    {
                        "schema": "nodrix.ros2-build/v1",
                        "fingerprint": fingerprint,
                        "command": list(command),
                        "built_at_ns": time.time_ns(),
                        "duration_s": duration_s,
                    },
                )
            setup_files = underlay_setups + (install_setup,)
        else:
            setup_files = underlay_setups

        runtime_environment = capture_sourced_environment(
            setup_files,
            base_environment=build_environment,
        )
        runtime_environment.update(self.spec.environment)
        return WorkspacePreparation(
            environment=runtime_environment,
            setup_files=setup_files,
            built=built,
            fingerprint=fingerprint,
            command=command,
            duration_s=duration_s,
        )
