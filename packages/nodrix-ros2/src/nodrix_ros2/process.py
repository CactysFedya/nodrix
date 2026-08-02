from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import IO, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    pid: int | None
    running: bool
    returncode: int | None
    started_ns: int | None
    uptime_s: float
    command_sha256: str


class ManagedProcess:
    """Long-lived child process with process-group shutdown and explicit logs."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        environment: Mapping[str, str],
        stdout_path: Path,
        stderr_path: Path,
        max_log_bytes: int = 50 * 1024 * 1024,
        log_rotations: int = 3,
    ) -> None:
        if not command:
            raise ValueError("process command cannot be empty")
        self.command = tuple(str(item) for item in command)
        self.cwd = cwd
        self.environment = dict(environment)
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path
        self.max_log_bytes = max(int(max_log_bytes), 0)
        self.log_rotations = max(int(log_rotations), 0)
        self.command_sha256 = hashlib.sha256(
            "\0".join(self.command).encode("utf-8")
        ).hexdigest()
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout: IO[bytes] | None = None
        self._stderr: IO[bytes] | None = None
        self._started_ns: int | None = None

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("process already started")
        self.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_log(self.stdout_path)
        self._rotate_log(self.stderr_path)
        self._stdout = self.stdout_path.open("ab", buffering=0)
        self._stderr = self.stderr_path.open("ab", buffering=0)
        kwargs: dict[str, object] = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        elif os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            self._process = subprocess.Popen(
                list(self.command),
                cwd=self.cwd,
                env=self.environment,
                stdin=subprocess.DEVNULL,
                stdout=self._stdout,
                stderr=self._stderr,
                **kwargs,
            )
        except BaseException:
            self._close_logs()
            raise
        self._started_ns = time.time_ns()

    def restart(self) -> None:
        """Restart a process that has already exited, preserving supervision."""

        if self._process is not None and self._process.poll() is None:
            raise RuntimeError("cannot restart a running process")
        self._close_logs()
        self._process = None
        self._started_ns = None
        self.start()

    def _rotate_log(self, path: Path) -> None:
        if (
            self.max_log_bytes <= 0
            or not path.is_file()
            or path.stat().st_size < self.max_log_bytes
        ):
            return
        if self.log_rotations <= 0:
            path.unlink()
            return
        oldest = path.with_name(f"{path.name}.{self.log_rotations}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.log_rotations - 1, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            if source.exists():
                source.replace(path.with_name(f"{path.name}.{index + 1}"))
        path.replace(path.with_name(f"{path.name}.1"))

    def poll(self) -> int | None:
        return None if self._process is None else self._process.poll()

    def snapshot(self) -> ProcessSnapshot:
        process = self._process
        returncode = None if process is None else process.poll()
        uptime = 0.0
        if self._started_ns is not None:
            uptime = max((time.time_ns() - self._started_ns) / 1_000_000_000, 0.0)
        return ProcessSnapshot(
            pid=None if process is None else process.pid,
            running=process is not None and returncode is None,
            returncode=returncode,
            started_ns=self._started_ns,
            uptime_s=uptime,
            command_sha256=self.command_sha256,
        )

    def wait(self, timeout: float | None = None) -> int:
        if self._process is None:
            raise RuntimeError("process is not started")
        return self._process.wait(timeout=timeout)

    def stderr_tail(self, maximum_bytes: int = 8192) -> str:
        try:
            with self.stderr_path.open("rb") as stream:
                size = stream.seek(0, os.SEEK_END)
                stream.seek(max(size - max(int(maximum_bytes), 0), 0))
                return stream.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _send_group_signal(self, sig: int) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif sig == signal.SIGINT:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(sig)

    def stop(
        self,
        *,
        interrupt_timeout_s: float = 8.0,
        terminate_timeout_s: float = 3.0,
    ) -> int | None:
        process = self._process
        if process is None:
            self._close_logs()
            return None
        if process.poll() is None:
            try:
                self._send_group_signal(signal.SIGINT)
            except OSError:
                pass
            try:
                process.wait(timeout=max(interrupt_timeout_s, 0.0))
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            try:
                self._send_group_signal(signal.SIGTERM)
            except OSError:
                pass
            try:
                process.wait(timeout=max(terminate_timeout_s, 0.0))
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            try:
                if os.name == "posix":
                    self._send_group_signal(signal.SIGKILL)
                else:
                    process.kill()
            except OSError:
                pass
            shutdown_error: BaseException | None = None
            try:
                process.wait(timeout=max(terminate_timeout_s, 1.0))
            except subprocess.TimeoutExpired as exc:
                shutdown_error = RuntimeError(
                    f"process group {process.pid} did not stop after SIGKILL"
                )
                shutdown_error.__cause__ = exc
        else:
            shutdown_error = None
        returncode = process.poll()
        self._close_logs()
        if shutdown_error is not None:
            raise shutdown_error
        return returncode

    def _close_logs(self) -> None:
        for stream in (self._stdout, self._stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._stdout = None
        self._stderr = None

    def __enter__(self) -> "ManagedProcess":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
