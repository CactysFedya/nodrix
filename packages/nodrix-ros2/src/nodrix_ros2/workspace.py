from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from hashlib import blake2b
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence

from .process import ManagedProcess


_RELEVANT_NAMES = {"package.xml", "CMakeLists.txt", "setup.py", "setup.cfg", "pyproject.toml"}
_RELEVANT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".py", ".xml", ".yaml", ".yml", ".json", ".rviz", ".launch",
}
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _expand_path(
    value: str | os.PathLike[str],
    *,
    base_dir: Path | None = None,
) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve()


def _expand_environment_value(
    value: object,
    *,
    base_dir: Path | None = None,
) -> str:
    text = os.path.expanduser(str(value))
    if base_dir is not None:
        root = str(base_dir.expanduser().resolve())
        text = text.replace("${PROJECT_ROOT}", root)
        text = text.replace("${NODRIX_PROJECT_ROOT}", root)
    return os.path.expandvars(text)


_SAFE_ENVIRONMENT_NAMES = {
    "HOME", "USER", "LOGNAME", "PATH", "SHELL", "LANG", "LANGUAGE",
    "TMPDIR", "TEMP", "TMP", "TERM", "DISPLAY", "XAUTHORITY",
    "WAYLAND_DISPLAY", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
    "PYTHONPATH", "CC", "CXX", "CMAKE_TOOLCHAIN_FILE",
    "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES",
    "CYCLONEDDS_URI", "FASTRTPS_DEFAULT_PROFILES_FILE",
}
_SAFE_ENVIRONMENT_PREFIXES = ("LC_", "ROS_", "RMW_", "AMENT_", "COLCON_")


def base_ros_environment(
    *,
    inherit_all: bool = False,
    pass_names: Sequence[str] = (),
) -> dict[str, str]:
    if inherit_all:
        return dict(os.environ)
    allowed = _SAFE_ENVIRONMENT_NAMES | {str(item) for item in pass_names}
    return {
        name: value
        for name, value in os.environ.items()
        if name in allowed or name.startswith(_SAFE_ENVIRONMENT_PREFIXES)
    }


def _path_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _workspace_file_lock(workspace: Path):
    """Serialize colcon/cache work across independent Nodrix processes."""

    directory = workspace / ".nodrix"
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise PermissionError(f"Unsafe ROS build state directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ros2-build.lock"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PermissionError(f"Unsafe ROS build lock: {path}")
    stream = path.open("a+b")
    try:
        if os.name == "posix":
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        elif os.name == "nt":  # pragma: no cover - Windows ROS is uncommon
            import msvcrt

            stream.seek(0)
            if stream.read(1) == b"":
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            elif os.name == "nt":  # pragma: no cover
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            stream.close()


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
    commands = ["set -eo pipefail", "set +u"]
    commands.extend(f"source {shlex.quote(str(path))}" for path in setup_files)
    commands.append("env -0")
    completed = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", "; ".join(commands)],
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
    timeout_s: float = 1800.0
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
            timeout_s=max(float(data.get("timeout_s", 1800.0)), 1.0),
            extra_args=tuple(str(x) for x in data.get("extra_args", ())),
        )


@dataclass(frozen=True, slots=True)
class RosWorkspaceSpec:
    distro: str = "jazzy"
    underlays: tuple[Path, ...] = ()
    path: Path | None = None
    build: RosBuildSpec = field(default_factory=RosBuildSpec)
    environment: Mapping[str, str] = field(default_factory=dict)
    inherit_environment: bool = False
    pass_environment: tuple[str, ...] = ()
    trust: str = "explicit"

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
        *,
        base_dir: Path | None = None,
    ) -> "RosWorkspaceSpec":
        data = dict(value or {})
        distro = str(data.get("distro") or os.environ.get("ROS_DISTRO") or "jazzy")
        raw_underlays = list(data.get("underlays", ()))
        if not raw_underlays:
            raw_underlays.append(f"/opt/ros/{distro}")
        path_value = data.get("path")
        trust = str(data.get("trust", "explicit")).strip().lower()
        if trust not in {"project", "explicit", "readonly"}:
            raise ValueError("ROS workspace trust must be project, explicit, or readonly")
        return cls(
            distro=distro,
            underlays=tuple(
                _expand_path(item, base_dir=base_dir) for item in raw_underlays
            ),
            path=(
                None
                if not path_value
                else _expand_path(path_value, base_dir=base_dir)
            ),
            build=RosBuildSpec.from_mapping(data.get("build")),
            environment={
                str(k): _expand_environment_value(v, base_dir=base_dir)
                for k, v in dict(data.get("environment") or {}).items()
            },
            inherit_environment=bool(data.get("inherit_environment", False)),
            pass_environment=tuple(
                str(item) for item in data.get("pass_environment", ())
            ),
            trust=trust,
        )


@dataclass(frozen=True, slots=True)
class WorkspacePreparation:
    environment: Mapping[str, str]
    setup_files: tuple[Path, ...]
    built: bool
    fingerprint: str | None
    command: tuple[str, ...] = ()
    duration_s: float = 0.0


def workspace_fingerprint(
    workspace: Path,
    *,
    strict: bool = False,
    identity: Mapping[str, Any] | None = None,
) -> str:
    source = workspace / "src"
    if not source.is_dir():
        return "missing-src"
    digest = blake2b(digest_size=20)
    if identity:
        digest.update(
            json.dumps(
                dict(identity), sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")
        )
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

    def __init__(
        self,
        spec: RosWorkspaceSpec,
        *,
        project_dir: Path | None = None,
        log_directory: Path | None = None,
    ) -> None:
        self.spec = spec
        self.project_dir = None if project_dir is None else project_dir.resolve()
        self.log_directory = log_directory

    def _validate_trust(self) -> None:
        workspace = self.spec.path
        if workspace is None:
            return
        if self.spec.trust == "readonly" and self.spec.build.mode != "never":
            raise PermissionError(
                "ROS workspace trust=readonly requires build.mode=never"
            )
        if self.spec.trust == "project":
            if self.project_dir is None:
                raise PermissionError(
                    "ROS workspace trust=project requires a project directory"
                )
            if workspace != self.project_dir and self.project_dir not in workspace.parents:
                raise PermissionError(
                    f"ROS workspace is outside the Nodrix project: {workspace}"
                )

    def _identity(
        self,
        underlay_setups: Sequence[Path],
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> dict[str, Any]:
        return {
            "schema": "nodrix.ros2-build-identity/v1",
            "distro": self.spec.distro,
            "underlays": [
                {
                    "path": str(path),
                    "size": path.stat().st_size,
                    "mtime_ns": path.stat().st_mtime_ns,
                }
                for path in underlay_setups
            ],
            "command": list(command),
            "colcon": shutil.which("colcon"),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cc": environment.get("CC"),
            "cxx": environment.get("CXX"),
            "cmake_toolchain_file": environment.get("CMAKE_TOOLCHAIN_FILE"),
            "environment": dict(sorted(self.spec.environment.items())),
        }

    def prepare(self) -> WorkspacePreparation:
        self._validate_trust()
        lock_path = self.spec.path or self.spec.underlays[0]
        with _path_lock(lock_path):
            if self.spec.path is not None and self.spec.build.mode != "never":
                with _workspace_file_lock(self.spec.path):
                    return self._prepare_locked()
            return self._prepare_locked()

    def _prepare_locked(self) -> WorkspacePreparation:
        underlay_setups = tuple(resolve_setup_file(path) for path in self.spec.underlays)
        base_environment = base_ros_environment(
            inherit_all=self.spec.inherit_environment,
            pass_names=self.spec.pass_environment,
        )
        build_environment = capture_sourced_environment(
            underlay_setups,
            base_environment=base_environment,
        )
        build_environment.update(self.spec.environment)
        built = False
        command: tuple[str, ...] = ()
        fingerprint: str | None = None
        duration_s = 0.0

        if self.spec.path is not None:
            workspace = self.spec.path
            if not workspace.is_dir():
                raise FileNotFoundError(f"ROS workspace does not exist: {workspace}")
            planned_command = build_command(self.spec.build)
            identity = self._identity(
                underlay_setups,
                planned_command,
                build_environment,
            )
            fingerprint = workspace_fingerprint(
                workspace,
                strict=self.spec.build.strict_fingerprint,
                identity=identity,
            )
            install_setup = workspace / "install" / "setup.bash"
            cached = _read_cache(workspace)
            needs_build = self.spec.build.mode == "always"
            if self.spec.build.mode == "if-needed":
                needs_build = (
                    not install_setup.is_file()
                    or cached.get("fingerprint") != fingerprint
                    or cached.get("command") != list(planned_command)
                    or cached.get("identity") != identity
                )
            if self.spec.build.mode == "never" and not install_setup.is_file():
                raise RuntimeError(
                    f"ROS workspace is not built and build.mode=never: {workspace}"
                )
            if needs_build:
                if not (workspace / "src").is_dir():
                    raise RuntimeError(f"ROS workspace has no src directory: {workspace}")
                command = planned_command
                started = time.monotonic()
                log_directory = (
                    self.log_directory
                    or workspace / ".nodrix" / "logs"
                )
                build_process = ManagedProcess(
                    command,
                    cwd=workspace,
                    environment=build_environment,
                    stdout_path=log_directory / "colcon.stdout.log",
                    stderr_path=log_directory / "colcon.stderr.log",
                )
                build_process.start()
                try:
                    returncode = build_process.wait(self.spec.build.timeout_s)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    build_process.stop(
                        interrupt_timeout_s=5.0,
                        terminate_timeout_s=2.0,
                    )
                    raise RuntimeError(
                        "ROS workspace build was cancelled or timed out; "
                        f"see {log_directory}"
                    )
                finally:
                    if build_process.poll() is not None:
                        build_process.stop(
                            interrupt_timeout_s=0.0,
                            terminate_timeout_s=0.0,
                        )
                if returncode != 0:
                    tail = build_process.stderr_tail().strip()
                    raise RuntimeError(
                        f"colcon build failed with code {returncode}: {tail}"
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
                        "identity": identity,
                        "trust": self.spec.trust,
                        "built_at_ns": time.time_ns(),
                        "duration_s": duration_s,
                    },
                )
            setup_files = underlay_setups + (install_setup,)
        else:
            setup_files = underlay_setups

        runtime_environment = (
            capture_sourced_environment(
                (install_setup,),
                base_environment=build_environment,
            )
            if self.spec.path is not None
            else dict(build_environment)
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
