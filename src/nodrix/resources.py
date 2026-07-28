from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Any


def _linux_process(pid: int) -> dict[str, Any] | None:
    proc = Path(f"/proc/{pid}")
    try:
        stat = (proc / "stat").read_text().split()
        statm = (proc / "statm").read_text().split()
    except (OSError, IndexError):
        return None
    # A terminated child can remain visible briefly as a zombie. Linux then
    # reports RSS=0; treating it as a fresh sample would erase the last valid
    # per-node memory snapshot captured while the worker was alive.
    if len(stat) > 2 and stat[2] in {"Z", "X"}:
        return None
    ticks = float(os.sysconf("SC_CLK_TCK"))
    page = int(os.sysconf("SC_PAGE_SIZE"))
    return {
        "pid": pid,
        "cpu_time_seconds": (int(stat[13]) + int(stat[14])) / ticks,
        "rss_bytes": int(statm[1]) * page,
        "vms_bytes": int(statm[0]) * page,
        "threads": int(stat[19]),
    }


def _ps_process(pid: int) -> dict[str, Any] | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "time=,rss=,vsz=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=0.25,
            check=False,
        )
        parts = result.stdout.strip().split()
        if len(parts) < 3:
            return None
        time_text, rss, vms = parts[-3:]
        segments = [float(item) for item in time_text.split(":")]
        cpu_seconds = segments[-1] + (segments[-2] * 60 if len(segments) >= 2 else 0)
        if len(segments) >= 3:
            cpu_seconds += segments[-3] * 3600
        return {
            "pid": pid,
            "cpu_time_seconds": cpu_seconds,
            "rss_bytes": int(rss) * 1024,
            "vms_bytes": int(vms) * 1024,
            "threads": None,
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def process_snapshot(pid: int) -> dict[str, Any] | None:
    if sys.platform.startswith("linux"):
        return _linux_process(pid)
    return _ps_process(pid)


def system_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {
        "cpu_count": os.cpu_count() or 1,
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
    }
    if sys.platform.startswith("linux"):
        try:
            values: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0]) * 1024
            result["memory_total_bytes"] = values.get("MemTotal", 0)
            result["memory_available_bytes"] = values.get("MemAvailable", 0)
        except (OSError, ValueError):
            pass
        temperatures: list[float] = []
        for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            try:
                value = float(path.read_text().strip())
                temperatures.append(value / 1000.0 if value > 1000 else value)
            except (OSError, ValueError):
                continue
        if temperatures:
            result["temperature_c"] = max(temperatures)
        try:
            throttled = Path("/sys/devices/platform/soc/soc:firmware/get_throttled")
            if throttled.is_file():
                result["throttled"] = throttled.read_text().strip()
        except OSError:
            pass
    else:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        result["process_max_rss_bytes"] = int(usage.ru_maxrss) * (1 if sys.platform == "darwin" else 1024)
    return result


@dataclass(slots=True)
class ResourceSampler:
    _last_process: dict[int, tuple[float, float]] = field(default_factory=dict)
    _last_node_cpu_ns: dict[str, tuple[int, float]] = field(default_factory=dict)

    def process(self, pid: int) -> dict[str, Any]:
        snapshot = process_snapshot(pid)
        if snapshot is None:
            return {"pid": pid, "available": False}
        now = time.monotonic()
        cpu_time = float(snapshot.get("cpu_time_seconds", 0.0))
        previous = self._last_process.get(pid)
        cpu_percent = 0.0
        if previous is not None:
            previous_cpu, previous_time = previous
            elapsed = max(now - previous_time, 1e-9)
            cpu_percent = max(0.0, (cpu_time - previous_cpu) / elapsed * 100.0)
        self._last_process[pid] = (cpu_time, now)
        return {**snapshot, "available": True, "cpu_percent": cpu_percent}

    def in_process_node(self, name: str, total_processing_ns: int) -> dict[str, Any]:
        now = time.monotonic()
        previous = self._last_node_cpu_ns.get(name)
        cpu_percent = 0.0
        if previous is not None:
            previous_total, previous_time = previous
            elapsed = max(now - previous_time, 1e-9)
            cpu_percent = max(0.0, (total_processing_ns - previous_total) / 1e9 / elapsed * 100.0)
        self._last_node_cpu_ns[name] = (int(total_processing_ns), now)
        executor = self.process(os.getpid())
        return {
            "scope": "executor_shared",
            "pid": os.getpid(),
            "cpu_percent": cpu_percent,
            "executor_cpu_percent": executor.get("cpu_percent", 0.0),
            "executor_rss_bytes": executor.get("rss_bytes", 0),
            "executor_vms_bytes": executor.get("vms_bytes", 0),
            "threads": executor.get("threads"),
        }
