from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math


def _percentile(sorted_values: list[int], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


@dataclass(slots=True)
class LatencyWindow:
    capacity: int = 4096
    count: int = 0
    total_ns: int = 0
    min_ns: int | None = None
    max_ns: int = 0
    samples: deque[int] = field(default_factory=lambda: deque(maxlen=4096))

    def __post_init__(self) -> None:
        if self.samples.maxlen != self.capacity:
            self.samples = deque(maxlen=self.capacity)

    def observe(self, value_ns: int) -> None:
        value_ns = max(0, int(value_ns))
        self.count += 1
        self.total_ns += value_ns
        self.min_ns = value_ns if self.min_ns is None else min(self.min_ns, value_ns)
        self.max_ns = max(self.max_ns, value_ns)
        self.samples.append(value_ns)

    def report_ms(self) -> dict[str, float | int]:
        values = sorted(self.samples)
        mean = self.total_ns / self.count if self.count else 0.0
        return {
            "count": self.count,
            "mean_ms": mean / 1e6,
            "min_ms": (self.min_ns or 0) / 1e6,
            "max_ms": self.max_ns / 1e6,
            "p50_ms": _percentile(values, 0.50) / 1e6,
            "p95_ms": _percentile(values, 0.95) / 1e6,
            "p99_ms": _percentile(values, 0.99) / 1e6,
            "sample_count": len(values),
        }
