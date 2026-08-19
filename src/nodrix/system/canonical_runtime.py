"""Runtime bridge from SystemOrchestrator to canonical ExecutionRecord.

The existing SystemOrchestrator remains responsible for real execution.
This module observes that lifecycle and exposes immutable canonical execution
snapshots without putting canonical history concerns into backend code.

A CanonicalSystemExecution is runtime tracking state, not itself a canonical
record.  ExecutionRecord remains the immutable cross-domain representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from nodrix.model import (
    SYSTEM_EXECUTION,
    ExecutionRecord,
    ExecutionState,
    PlanRecord,
)
from nodrix.run_events import (
    RunEventJournal,
)
from nodrix.run_session import (
    RunSession,
    RunStore,
)

from .execution_events import (
    ExecutionEvent,
    ExecutionEventKind,
    execution_event_from_startup_event,
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
    event_journal: RunEventJournal | None = None
    event_persistence_errors: list[str] = field(
        default_factory=list,
        repr=False,
    )
    terminal_event_recorded: bool = False
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

        if self.event_journal is not None:
            if not isinstance(
                self.event_journal,
                RunEventJournal,
            ):
                raise TypeError(
                    "event_journal must be a RunEventJournal or None"
                )

            if self.run_session is None:
                raise ValueError(
                    "event_journal requires run_session"
                )

            if (
                self.event_journal.run_id
                != self.run_session.run_id
            ):
                raise ValueError(
                    "event_journal belongs to a different RunSession"
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

        details = _status_details(
            status
        )

        if self.event_persistence_errors:
            details[
                "run_event_persistence_errors"
            ] = tuple(
                self.event_persistence_errors
            )

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
            details=details,
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

    event_journal = (
        RunEventJournal(
            run_session
        )
        if run_session is not None
        else None
    )

    def persist_error(
        *,
        stage: str,
        error: Exception,
    ) -> None:
        if event_journal is None:
            return

        observed_at = _now(
            clock
        )

        event_journal.append(
            ExecutionEvent(
                event=ExecutionEventKind.ERROR,
                system=domain_plan.system,
                timestamp=observed_at,
                message=(
                    f"{stage} failed: {error}"
                ),
                details={
                    "stage": stage,
                    "errorType": (
                        type(error).__name__
                    ),
                },
            ).to_dict(),
            recorded_at=observed_at,
        )

    try:
        prepared = orchestrator.prepare_plan(
            domain_plan
        )
    except Exception as exc:
        try:
            persist_error(
                stage="prepare",
                error=exc,
            )
        except Exception as event_exc:
            exc.add_note(
                "failed to persist Run prepare "
                f"error event: {event_exc}"
            )

        raise

    if event_journal is not None:
        prepared_at = _now(
            clock
        )

        event_journal.append(
            ExecutionEvent(
                event=ExecutionEventKind.PREPARED,
                system=domain_plan.system,
                timestamp=prepared_at,
            ).to_dict(),
            recorded_at=prepared_at,
        )

    def startup_event_sink(
        startup_event,
    ) -> None:
        if event_journal is None:
            return

        observed_at = _now(
            clock
        )

        event_journal.append(
            execution_event_from_startup_event(
                startup_event,
                timestamp=observed_at,
            ).to_dict(),
            recorded_at=observed_at,
        )

    started_at = _now(
        clock
    )

    try:
        handle = orchestrator.start(
            prepared,
            startup_event_sink=(
                startup_event_sink
                if event_journal is not None
                else None
            ),
        )
    except Exception as exc:
        try:
            persist_error(
                stage="start",
                error=exc,
            )
        except Exception as event_exc:
            exc.add_note(
                "failed to persist Run start "
                f"error event: {event_exc}"
            )

        raise

    if event_journal is not None:
        started_event_at = _now(
            clock
        )

        try:
            event_journal.append(
                ExecutionEvent(
                    event=ExecutionEventKind.STARTED,
                    system=domain_plan.system,
                    timestamp=started_event_at,
                    execution_id=(
                        handle.execution_id
                    ),
                ).to_dict(),
                recorded_at=started_event_at,
            )
        except Exception as exc:
            # The execution has already started.  If the mandatory durable
            # STARTED event cannot be persisted, stop it again so callers
            # never receive an untracked live execution.
            try:
                orchestrator.stop(
                    handle
                )
            except Exception as rollback_exc:
                exc.add_note(
                    "failed to stop execution after "
                    "Run event persistence failure: "
                    f"{rollback_exc}"
                )

            raise

    return CanonicalSystemExecution(
        plan=plan,
        handle=handle,
        started_at=started_at,
        run_session=run_session,
        event_journal=event_journal,
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

    observed_at = _now(
        clock
    )

    if (
        status.terminal
        and not execution.terminal_event_recorded
        and execution.event_journal is not None
    ):
        try:
            execution.event_journal.append(
                ExecutionEvent(
                    event=ExecutionEventKind.FINISHED,
                    system=(
                        execution.handle
                        .prepared.plan.system
                    ),
                    timestamp=observed_at,
                    status=status,
                ).to_dict(),
                recorded_at=observed_at,
            )
        except Exception as exc:
            execution.event_persistence_errors.append(
                f"{type(exc).__name__}: {exc}"
            )
        else:
            execution.terminal_event_recorded = True

    return execution.record(
        status,
        observed_at=observed_at,
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

    journal = (
        execution.event_journal
    )

    if journal is not None:
        stopping_at = _now(
            clock
        )

        try:
            journal.append(
                ExecutionEvent(
                    event=ExecutionEventKind.STOPPING,
                    system=(
                        execution.handle
                        .prepared.plan.system
                    ),
                    timestamp=stopping_at,
                    execution_id=(
                        execution.execution_id
                    ),
                ).to_dict(),
                recorded_at=stopping_at,
            )
        except Exception as exc:
            # A storage failure must never prevent an explicit stop request.
            execution.event_persistence_errors.append(
                f"{type(exc).__name__}: {exc}"
            )

    try:
        status = orchestrator.stop(
            execution.handle,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        if journal is not None:
            try:
                failed_at = _now(
                    clock
                )

                journal.append(
                    ExecutionEvent(
                        event=ExecutionEventKind.ERROR,
                        system=(
                            execution.handle
                            .prepared.plan.system
                        ),
                        timestamp=failed_at,
                        execution_id=(
                            execution.execution_id
                        ),
                        message=(
                            f"stop failed: {exc}"
                        ),
                        details={
                            "stage": "stop",
                            "errorType": (
                                type(exc).__name__
                            ),
                        },
                    ).to_dict(),
                    recorded_at=failed_at,
                )
            except Exception as event_exc:
                exc.add_note(
                    "failed to persist Run stop "
                    f"error event: {event_exc}"
                )

        raise

    observed_at = _now(
        clock
    )

    if (
        journal is not None
        and status.terminal
        and not execution.terminal_event_recorded
    ):
        try:
            journal.append(
                ExecutionEvent(
                    event=ExecutionEventKind.FINISHED,
                    system=(
                        execution.handle
                        .prepared.plan.system
                    ),
                    timestamp=observed_at,
                    status=status,
                ).to_dict(),
                recorded_at=observed_at,
            )
        except Exception as exc:
            execution.event_persistence_errors.append(
                f"{type(exc).__name__}: {exc}"
            )
        else:
            execution.terminal_event_recorded = True

    return execution.record(
        status,
        observed_at=observed_at,
    )


__all__ = [
    "CanonicalSystemExecution",
    "SYSTEM_ORCHESTRATOR_EXECUTOR",
    "inspect_canonical_system_execution",
    "start_canonical_system_execution",
    "stop_canonical_system_execution",
]
