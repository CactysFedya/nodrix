from pathlib import Path
import hashlib
import sys
import time

from nodrix_ros2.process import ManagedProcess


def test_managed_process_stops_process_group(tmp_path: Path) -> None:
    process = ManagedProcess(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
        environment={"PATH": str(Path(sys.executable).parent)},
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )
    process.start()
    time.sleep(0.05)
    assert process.snapshot().running
    process.stop(interrupt_timeout_s=0.2, terminate_timeout_s=0.2)
    assert not process.snapshot().running


def test_managed_process_rotates_logs_and_reports_command_identity(
    tmp_path: Path,
) -> None:
    stdout = tmp_path / "stdout.log"
    stdout.write_text("old log content", encoding="utf-8")
    command = [sys.executable, "-c", "print('new')"]
    process = ManagedProcess(
        command,
        cwd=tmp_path,
        environment={"PATH": str(Path(sys.executable).parent)},
        stdout_path=stdout,
        stderr_path=tmp_path / "stderr.log",
        max_log_bytes=1,
        log_rotations=2,
    )
    process.start()
    assert process.wait(5) == 0
    snapshot = process.snapshot()
    process.stop()
    assert stdout.with_name("stdout.log.1").read_text(encoding="utf-8") == "old log content"
    assert snapshot.command_sha256 == hashlib.sha256(
        "\0".join(command).encode("utf-8")
    ).hexdigest()


def test_managed_process_can_restart_after_clean_exit(tmp_path: Path) -> None:
    process = ManagedProcess(
        [sys.executable, "-c", "print('ready')"],
        cwd=tmp_path,
        environment={"PATH": str(Path(sys.executable).parent)},
        stdout_path=tmp_path / "restart.stdout.log",
        stderr_path=tmp_path / "restart.stderr.log",
    )
    process.start()
    assert process.wait(5) == 0
    process.restart()
    assert process.wait(5) == 0
    process.stop()
    assert (tmp_path / "restart.stdout.log").read_text().count("ready") == 2
