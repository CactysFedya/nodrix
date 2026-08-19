"""Runtime bridge from SystemOrchestrator to canonical ExecutionRecord.

The existing SystemOrchestrator remains responsible for real execution.
This module observes that lifecycle and exposes immutable canonical execution
snapshots without putting canonical history concerns into backend code.

A CanonicalSystemExecution is runtime tracking state, not itself a canonical
record.  ExecutionRecord remains the immutable cross-domain representation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from nodrix.model import (
    SYSTEM_EXECUTION,
    ExecutionRecord,
    ExecutionState,
    PlanRecord,
)
from nodrix.run_session import (
    RunSession,
    RunStore,
)

from .orchestration import (
    SystemExecutionHandle,
    SystemExecutionStatus,
    SystemOrchestrator,
)
from .planning import SystemExecutionPlan


SYSTEM_ORCHESTRATOR_EXECUTOR = "nodrix.system.orchestrator"

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(
    value: datetime,
    *,
    field_name: str,
) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field_name} must be a datetime"
        )

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )

    return value


def _now(clock: Clock) -> datetime:
    if not callable(clock):
        raise TypeError("clock must be callable")

    return _timestamp(
        clock(),
        field_name="clock result",
    )


def _execution_state(
    status: SystemExecutionStatus,
) -> ExecutionState:
    return ExecutionState.parse(
        status.state.value
    )


def _status_details(
    status: SystemExecutionStatus,
) -> dict[str, object]:
    details: dict[str, object] = {
        "scope_count": len(status.scopes),
        "scopes": tuple(
            {
                "target": item.scope.target,
                "backend": item.scope.backend,
                "execution_id": item.status.execution_id,
                "state": item.status.state.value,
                "message": item.status.message,
                "details": dict(item.status.details),
            }
            for item in status.scopes
        ),
    }

    if status.message is not None:
        details["message"] = status.message

    if status.details:
        details["status_details"] = dict(
            status.details
        )

    if status.systems:
        details["system_count"] = len(
            status.systems
        )

        details["systems"] = tuple(
            {
                "ordinal": item.ordinal,
                "name": item.name,
                "system": item.instance.plan.system,
                "revision": item.revision,
                "execution_id": item.status.execution_id,
                "state": item.status.state.value,
                "message": item.status.message,
                "status_details": dict(
                    item.status.details
                ),
                "details": _status_details(
                    item.status
                ),
            }
            for item in status.systems
        )

    return details


def _validate_system_plan_record(
    plan: PlanRecord,
) -> SystemExecutionPlan:
    if not isinstance(plan, PlanRecord):
        raise TypeError(
            "plan must be a PlanRecord"
        )

    if plan.kind != SYSTEM_EXECUTION:
        raise ValueError(
            "canonical system execution requires "
            "a system-execution PlanRecord"
        )

    if not isinstance(
        plan.payload,
        SystemExecutionPlan,
    ):
        raise TypeError(
            "system-execution PlanRecord payload must "
            "be a SystemExecutionPlan"
        )

    return plan.payload


@dataclass(slots=True)
class CanonicalSystemExecution:
    """Track one live SystemOrchestrator execution.

    This object is intentionally mutable because it tracks ephemeral runtime
    observation state.  The canonical ExecutionRecord snapshots it produces
    remain immutable.

    ``finished_at`` records the first time the orchestrator observes a terminal
    state.  This is an orchestration observation timestamp, not a backend-
    specific process exit timestamp.
    """

    plan: PlanRecord
    handle: SystemExecutionHandle
    started_at: datetime
    run_session: RunSession | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        domain_plan = _validate_system_plan_record(
            self.plan
        )

        if not isinstance(
            self.handle,
            SystemExecutionHandle,
        ):
            raise TypeError(
                "handle must be a SystemExecutionHandle"
            )

        if self.handle.prepared.plan != domain_plan:
            raise ValueError(
                "execution handle belongs to a different "
                "SystemExecutionPlan"
            )

        if self.run_session is not None:
            if not isinstance(
                self.run_session,
                RunSession,
            ):
                raise TypeError(
                    "run_session must be a RunSession or None"
                )

            if (
                self.run_session.plan_id
                != self.plan.plan_id
            ):
                raise ValueError(
                    "RunSession belongs to a different PlanRecord"
                )

        self.started_at = _timestamp(
            self.started_at,
            field_name="started_at",
        )

        if self.finished_at is not None:
            self.finished_at = _timestamp(
                self.finished_at,
                field_name="finished_at",
            )

            if self.finished_at < self.started_at:
                raise ValueError(
                    "finished_at cannot be earlier than started_at"
                )

    @property
    def execution_id(self) -> str:
        return self.handle.execution_id

    @property
    def run_id(self) -> str | None:
        """Return the persistent Run identity when one is attached."""

        if self.run_session is None:
            return None

        return self.run_session.run_id

    def record(
        self,
        status: SystemExecutionStatus,
        *,
        observed_at: datetime,
    ) -> ExecutionRecord:
        """Create one immutable canonical snapshot of current runtime state."""

        if not isinstance(
            status,
            SystemExecutionStatus,
        ):
            raise TypeError(
                "status must be a SystemExecutionStatus"
            )

        if status.execution_id != self.execution_id:
            raise ValueError(
                "status belongs to a different system execution"
            )

        observed_at = _timestamp(
            observed_at,
            field_name="observed_at",
        )

        if observed_at < self.started_at:
            raise ValueError(
                "observed_at cannot be earlier than started_at"
            )

        state = _execution_state(status)

        if state.terminal and self.finished_at is None:
            self.finished_at = observed_at

        return ExecutionRecord(
            execution_id=self.execution_id,
            plan=self.plan,
            executor=SYSTEM_ORCHESTRATOR_EXECUTOR,
            state=state,
            started_at=self.started_at,
            finished_at=(
                self.finished_at
                if state.terminal
                else None
            ),
            details=_status_details(status),
        )


def start_canonical_system_execution(
    orchestrator: SystemOrchestrator,
    plan: PlanRecord,
    *,
    run_store: RunStore | None = None,
    run_id: str | None = None,
    clock: Clock = _utc_now,
) -> CanonicalSystemExecution:
    """Prepare and start a canonical System execution."""

    if not isinstance(
        orchestrator,
        SystemOrchestrator,
    ):
        raise TypeError(
            "orchestrator must be a SystemOrchestrator"
        )

    domain_plan = _validate_system_plan_record(
        plan
    )

    if (
        run_store is not None
        and not isinstance(
            run_store,
            RunStore,
        )
    ):
        raise TypeError(
            "run_store must be a RunStore or None"
        )

    if (
        run_id is not None
        and run_store is None
    ):
        raise ValueError(
            "run_id requires run_store"
        )

    # Persistent Run identity must exist before any backend preparation or
    # execution starts.  If later preparation/startup fails, the Run directory
    # intentionally remains as evidence of the attempted execution.
    run_session = (
        run_store.create(
            plan,
            run_id=run_id,
        )
        if run_store is not None
        else None
    )

    prepared = orchestrator.prepare_plan(
        domain_plan
    )

    started_at = _now(clock)

    handle = orchestrator.start(
        prepared
    )

    return CanonicalSystemExecution(
        plan=plan,
        handle=handle,
        started_at=started_at,
        run_session=run_session,
    )


def inspect_canonical_system_execution(
    orchestrator: SystemOrchestrator,
    execution: CanonicalSystemExecution,
    *,
    clock: Clock = _utc_now,
) -> ExecutionRecord:
    """Inspect a live system execution and return a canonical snapshot."""

    if not isinstance(
        orchestrator,
        SystemOrchestrator,
    ):
        raise TypeError(
            "orchestrator must be a SystemOrchestrator"
        )

    if not isinstance(
        execution,
        CanonicalSystemExecution,
    ):
        raise TypeError(
            "execution must be a CanonicalSystemExecution"
        )

    status = orchestrator.inspect(
        execution.handle
    )

    return execution.record(
        status,
        observed_at=_now(clock),
    )


def stop_canonical_system_execution(
    orchestrator: SystemOrchestrator,
    execution: CanonicalSystemExecution,
    *,
    timeout_seconds: float | None = None,
    clock: Clock = _utc_now,
) -> ExecutionRecord:
    """Stop a system execution and return its canonical terminal snapshot."""

    if not isinstance(
        orchestrator,
        SystemOrchestrator,
    ):
        raise TypeError(
            "orchestrator must be a SystemOrchestrator"
        )

    if not isinstance(
        execution,
        CanonicalSystemExecution,
    ):
        raise TypeError(
            "execution must be a CanonicalSystemExecution"
        )

    status = orchestrator.stop(
        execution.handle,
        timeout_seconds=timeout_seconds,
    )

    return execution.record(
        status,
        observed_at=_now(clock),
    )


__all__ = [
    "CanonicalSystemExecution",
    "SYSTEM_ORCHESTRATOR_EXECUTOR",
    "inspect_canonical_system_execution",
    "start_canonical_system_execution",
    "stop_canonical_system_execution",
]
