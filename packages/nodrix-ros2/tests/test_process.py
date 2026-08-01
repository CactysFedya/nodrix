from pathlib import Path
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
