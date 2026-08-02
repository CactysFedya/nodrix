from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

try:
    import resource as _resource
except ImportError:  # Windows has no POSIX resource module.
    _resource = None


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
    rss_bytes = int(statm[1]) * page
    vms_bytes = int(statm[0]) * page
    # A process can exit between reading stat and statm. In that narrow
    # window Linux may expose an all-zero statm before stat reports Z.
    # Reject the transitional sample so it cannot erase a valid live one.
    if rss_bytes <= 0 or vms_bytes <= 0:
        return None
    return {
        "pid": pid,
        "cpu_time_seconds": (int(stat[13]) + int(stat[14])) / ticks,
        "rss_bytes": rss_bytes,
        "vms_bytes": vms_bytes,
        "threads": int(stat[19]),
    }


def _ps_process(pid: int) -> dict[str, Any] | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "stat=,time=,rss=,vsz=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=0.25,
            check=False,
        )
        parts = result.stdout.strip().split()
        if len(parts) < 4:
            return None
        status, time_text, rss, vms = parts[-4:]
        rss_bytes = int(rss) * 1024
        vms_bytes = int(vms) * 1024
        # ps can still expose a child briefly after exit. Never let a zombie
        # or a transient zero sample erase the last valid live measurement.
        if status.startswith(("Z", "X")) or rss_bytes <= 0:
            return None
        segments = [float(item) for item in time_text.split(":")]
        cpu_seconds = segments[-1] + (segments[-2] * 60 if len(segments) >= 2 else 0)
        if len(segments) >= 3:
            cpu_seconds += segments[-3] * 3600
        return {
            "pid": pid,
            "cpu_time_seconds": cpu_seconds,
            "rss_bytes": rss_bytes,
            "vms_bytes": vms_bytes,
            "threads": None,
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _windows_process(pid: int) -> dict[str, Any] | None:
    """Read a child process snapshot using Win32 without an optional psutil dependency."""
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCountersEx(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCountersEx),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ. Plyctl owns the child,
        # so these rights do not require elevation.
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, int(pid))
        if not handle:
            return None
        try:
            memory = ProcessMemoryCountersEx()
            memory.cb = ctypes.sizeof(memory)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                return None
            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None

            def filetime_value(value: Any) -> int:
                return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

            rss_bytes = int(memory.WorkingSetSize)
            if rss_bytes <= 0:
                return None
            return {
                "pid": pid,
                "cpu_time_seconds": (
                    filetime_value(kernel) + filetime_value(user)
                ) / 10_000_000.0,
                "rss_bytes": rss_bytes,
                "vms_bytes": int(memory.PrivateUsage or memory.PagefileUsage),
                "threads": None,
            }
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def process_snapshot(pid: int) -> dict[str, Any] | None:
    if sys.platform.startswith("linux"):
        return _linux_process(pid)
    if sys.platform == "win32":
        return _windows_process(pid)
    return _ps_process(pid)


def _windows_physical_memory_total_bytes() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GlobalMemoryStatusEx.argtypes = [
            ctypes.POINTER(MemoryStatusEx),
        ]
        kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            value = int(status.ullTotalPhys)
            return value if value > 0 else None
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return None


def _physical_memory_total_bytes() -> int | None:
    """Return installed physical memory without optional dependencies."""
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        if pages > 0 and page_size > 0:
            return pages * page_size
    except (AttributeError, OSError, TypeError, ValueError):
        pass

    if sys.platform == "win32":
        return _windows_physical_memory_total_bytes()
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=0.25,
                check=False,
            )
            if result.returncode == 0:
                value = int(result.stdout.strip())
                if value > 0:
                    return value
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    return None


def system_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {
        "cpu_count": os.cpu_count() or 1,
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
    }

    physical_memory = _physical_memory_total_bytes()
    if physical_memory is not None:
        result["memory_total_bytes"] = physical_memory
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
    elif _resource is not None:
        usage = _resource.getrusage(_resource.RUSAGE_SELF)
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
