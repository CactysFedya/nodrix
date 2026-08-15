
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import time


@dataclass(frozen=True, slots=True)
class ProcessTreeMetrics:
    cpu_percent: float = 0.0
    rss_bytes: int = 0
    process_count: int = 0
    thread_count: int = 0


@dataclass(frozen=True, slots=True)
class _ProcStat:
    pid: int
    pgrp: int
    cpu_ticks: int
    rss_pages: int
    threads: int


def _read_proc_stat(path: Path) -> _ProcStat | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        pid_text, remainder = text.split(" ", 1)
        closing = remainder.rfind(")")
        if closing < 0:
            return None
        fields = remainder[closing + 2 :].split()
        return _ProcStat(
            pid=int(pid_text),
            pgrp=int(fields[2]),
            cpu_ticks=int(fields[11]) + int(fields[12]),
            threads=max(int(fields[17]), 0),
            rss_pages=max(int(fields[21]), 0),
        )
    except (OSError, ValueError, IndexError):
        return None


def _linux_process_group(root_pid: int) -> tuple[int, int, int, int]:
    proc = Path("/proc")
    if not proc.is_dir():
        return 0, 0, 0, 0

    cpu_ticks = 0
    rss_pages = 0
    process_count = 0
    thread_count = 0

    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        stat = _read_proc_stat(entry / "stat")
        if stat is None or stat.pgrp != root_pid:
            continue
        cpu_ticks += stat.cpu_ticks
        rss_pages += stat.rss_pages
        process_count += 1
        thread_count += stat.threads

    return cpu_ticks, rss_pages, process_count, thread_count


class ProcessTreeSampler:
    'Best-effort Linux sampler for one managed process group.'

    def __init__(self) -> None:
        try:
            self._clock_ticks = max(int(os.sysconf("SC_CLK_TCK")), 1)
        except (AttributeError, OSError, ValueError):
            self._clock_ticks = 100
        try:
            self._page_size = max(int(os.sysconf("SC_PAGE_SIZE")), 1)
        except (AttributeError, OSError, ValueError):
            self._page_size = 4096

        self._last_pid: int | None = None
        self._last_ticks = 0
        self._last_sample_s: float | None = None

    def reset(self) -> None:
        self._last_pid = None
        self._last_ticks = 0
        self._last_sample_s = None

    def sample(self, root_pid: int | None) -> ProcessTreeMetrics:
        if root_pid is None or os.name != "posix":
            self.reset()
            return ProcessTreeMetrics()

        now = time.monotonic()
        ticks, rss_pages, process_count, thread_count = (
            _linux_process_group(root_pid)
        )
        cpu_percent = 0.0

        if (
            self._last_pid == root_pid
            and self._last_sample_s is not None
            and now > self._last_sample_s
            and ticks >= self._last_ticks
        ):
            used_cpu_s = (ticks - self._last_ticks) / self._clock_ticks
            cpu_percent = used_cpu_s / (now - self._last_sample_s) * 100.0

        self._last_pid = root_pid
        self._last_ticks = ticks
        self._last_sample_s = now

        return ProcessTreeMetrics(
            cpu_percent=max(cpu_percent, 0.0),
            rss_bytes=max(rss_pages * self._page_size, 0),
            process_count=max(process_count, 0),
            thread_count=max(thread_count, 0),
        )


__all__ = ["ProcessTreeMetrics", "ProcessTreeSampler"]
