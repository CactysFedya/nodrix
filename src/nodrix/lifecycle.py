from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import StrEnum
import threading
import time
from typing import Any


class LifecycleState(StrEnum):
    CREATED = "created"
    CONFIGURING = "configuring"
    READY = "ready"
    CONFIGURED = "configured"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    DRAINING = "draining"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    RESTARTING = "restarting"


class HealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(slots=True)
class HealthSnapshot:
    state: str
    status: str
    alive: bool
    ready: bool
    last_message_ns: int | None
    last_completion_ns: int | None
    last_error: str | None
    restart_count: int
    deadline_misses: int
    queue_pressure: float
    state_reason: str | None
    state_timestamp_ns: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LifecycleTracker:
    """Thread-safe lifecycle and health state shared by all executors."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.state = LifecycleState.CREATED
        self.status = HealthStatus.UNKNOWN
        self.alive = False
        self.ready = False
        self.last_message_ns: int | None = None
        self.last_completion_ns: int | None = None
        self.last_error: str | None = None
        self.restart_count = 0
        self.deadline_misses = 0
        self.queue_pressure = 0.0
        self.state_reason: str | None = None
        self.state_timestamp_ns = time.monotonic_ns()

    def transition(
        self,
        state: LifecycleState,
        *,
        status: HealthStatus | None = None,
        reason: str | None = None,
    ) -> None:
        with self._lock:
            self.state = state
            self.state_reason = reason
            self.state_timestamp_ns = time.monotonic_ns()
            if status is not None:
                self.status = status
            if state in {
                LifecycleState.STARTING,
                LifecycleState.RUNNING,
                LifecycleState.DEGRADED,
                LifecycleState.DRAINING,
            }:
                self.alive = True
            if state in {LifecycleState.READY, LifecycleState.RUNNING}:
                self.ready = True
            if state == LifecycleState.RUNNING:
                if self.status == HealthStatus.UNKNOWN:
                    self.status = HealthStatus.HEALTHY
            if state in {LifecycleState.STOPPING, LifecycleState.STOPPED, LifecycleState.FAILED}:
                self.ready = False
            if state in {LifecycleState.STOPPED, LifecycleState.FAILED}:
                self.alive = False

    def message_started(self) -> None:
        with self._lock:
            self.last_message_ns = time.monotonic_ns()

    def message_completed(self) -> None:
        with self._lock:
            self.last_completion_ns = time.monotonic_ns()
            if (
                self.status != HealthStatus.UNHEALTHY
                and self.state
                not in {LifecycleState.DEGRADED, LifecycleState.RESTARTING}
            ):
                self.status = HealthStatus.HEALTHY

    def error(self, exc: BaseException | str) -> None:
        with self._lock:
            self.last_error = str(exc)
            self.status = HealthStatus.UNHEALTHY
            self.state_reason = str(exc)

    def mark_restart(self) -> None:
        with self._lock:
            self.restart_count += 1
            self.state = LifecycleState.RESTARTING
            self.status = HealthStatus.DEGRADED
            self.ready = False
            self.state_reason = "restart requested"
            self.state_timestamp_ns = time.monotonic_ns()

    def set_queue_pressure(self, value: float) -> None:
        with self._lock:
            self.queue_pressure = max(0.0, min(float(value), 1.0))
            if self.queue_pressure >= 0.9 and self.status == HealthStatus.HEALTHY:
                self.status = HealthStatus.DEGRADED

    def snapshot(self) -> HealthSnapshot:
        with self._lock:
            return HealthSnapshot(
                state=self.state.value,
                status=self.status.value,
                alive=self.alive,
                ready=self.ready,
                last_message_ns=self.last_message_ns,
                last_completion_ns=self.last_completion_ns,
                last_error=self.last_error,
                restart_count=self.restart_count,
                deadline_misses=self.deadline_misses,
                queue_pressure=self.queue_pressure,
                state_reason=self.state_reason,
                state_timestamp_ns=self.state_timestamp_ns,
            )
