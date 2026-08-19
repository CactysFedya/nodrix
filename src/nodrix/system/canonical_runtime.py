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
from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.run_policy import (
    RunPolicyStore,
)
from nodrix.run_environment import (
    RunEnvironmentPolicy,
    RunEnvironmentStore,
)
from nodrix.run_events import (
    RunEventJournal,
)
from nodrix.run_logs import (
    RunLogPolicy,
    RunLogStore,
)
from nodrix.run_metrics import (
    RunMetricJournal,
    RunMetricSink,
)
from nodrix.run_record import (
    RunRecordStore,
)
from nodrix.run_snapshots import (
    DEFINITION_SNAPSHOT,
    PLAN_SNAPSHOT,
    RunSnapshotStore,
)
from nodrix.run_session import (
    RunSession,
    RunStore,
)
from nodrix.run_status import (
    RunStatusStore,
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
from .model import SystemModel
from .planning import SystemExecutionPlan
from .run_snapshots import (
    system_definition_snapshot,
    system_plan_snapshot,
)


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


def _write_run_status(
    store: RunStatusStore | None,
    errors: list[str],
    *,
    state: ExecutionState | str,
    execution_id: str | None,
    message: str | None = None,
    details: dict[str, object] | None = None,
    observed_at: datetime,
) -> None:
    """Persist recoverable live status without controlling execution."""

    if store is None:
        return

    try:
        store.write_if_changed(
            state=state,
            execution_id=execution_id,
            message=message,
            details=details,
            updated_at=observed_at,
        )
    except Exception as exc:
        error = (
            f"{type(exc).__name__}: {exc}"
        )

        # Avoid unbounded growth if a broken filesystem is polled repeatedly.
        if (
            not errors
            or errors[-1] != error
        ):
            errors.append(
                error
            )


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
    snapshot_store: RunSnapshotStore | None = None
    policy_store: RunPolicyStore | None = None
    environment_store: RunEnvironmentStore | None = None
    log_store: RunLogStore | None = None
    event_journal: RunEventJournal | None = None
    status_store: RunStatusStore | None = None
    run_record_store: RunRecordStore | None = None
    event_persistence_errors: list[str] = field(
        default_factory=list,
        repr=False,
    )
    status_persistence_errors: list[str] = field(
        default_factory=list,
        repr=False,
    )
    run_record_persistence_errors: list[str] = field(
        default_factory=list,
        repr=False,
    )
    terminal_event_recorded: bool = False
    final_run_recorded: bool = False
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

        if self.snapshot_store is not None:
            if not isinstance(
                self.snapshot_store,
                RunSnapshotStore,
            ):
                raise TypeError(
                    "snapshot_store must be a RunSnapshotStore or None"
                )

            if self.run_session is None:
                raise ValueError(
                    "snapshot_store requires run_session"
                )

            if (
                self.snapshot_store.run_id
                != self.run_session.run_id
            ):
                raise ValueError(
                    "snapshot_store belongs to a different RunSession"
                )

            if (
                self.snapshot_store.plan_id
                != self.plan.plan_id
            ):
                raise ValueError(
                    "snapshot_store belongs to a different PlanRecord"
                )

        if self.policy_store is not None:
            if not isinstance(
                self.policy_store,
                RunPolicyStore,
            ):
                raise TypeError(
                    "policy_store must be a "
                    "RunPolicyStore or None"
                )

            if self.run_session is None:
                raise ValueError(
                    "policy_store requires run_session"
                )

            if (
                self.policy_store.run_id
                != self.run_session.run_id
            ):
                raise ValueError(
                    "policy_store belongs to "
                    "a different RunSession"
                )

            if (
                self.policy_store.plan_id
                != self.plan.plan_id
            ):
                raise ValueError(
                    "policy_store belongs to "
                    "a different PlanRecord"
                )

        if self.environment_store is not None:
            if not isinstance(
                self.environment_store,
                RunEnvironmentStore,
            ):
                raise TypeError(
                    "environment_store must be a "
                    "RunEnvironmentStore or None"
                )

            if self.run_session is None:
                raise ValueError(
                    "environment_store requires run_session"
                )

            if (
                self.environment_store.run_id
                != self.run_session.run_id
            ):
                raise ValueError(
                    "environment_store belongs to "
                    "a different RunSession"
                )

            if (
                self.environment_store.plan_id
                != self.plan.plan_id
            ):
                raise ValueError(
                    "environment_store belongs to "
                    "a different PlanRecord"
                )

        if self.log_store is not None:
            if not isinstance(
                self.log_store,
                RunLogStore,
            ):
                raise TypeError(
                    "log_store must be a RunLogStore or None"
                )

            if self.run_session is None:
                raise ValueError(
                    "log_store requires run_session"
                )

            if (
                self.log_store.run_id
                != self.run_session.run_id
            ):
                raise ValueError(
                    "log_store belongs to a different RunSession"
                )

            if (
                self.log_store.plan_id
                != self.plan.plan_id
            ):
                raise ValueError(
                    "log_store belongs to a different PlanRecord"
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

        if self.status_store is not None:
            if not isinstance(
                self.status_store,
                RunStatusStore,
            ):
                raise TypeError(
                    "status_store must be a RunStatusStore or None"
                )

            if self.run_session is None:
                raise ValueError(
                    "status_store requires run_session"
                )

            if (
                self.status_store.run_id
                != self.run_session.run_id
            ):
                raise ValueError(
                    "status_store belongs to a different RunSession"
                )

        if self.run_record_store is not None:
            if not isinstance(
                self.run_record_store,
                RunRecordStore,
            ):
                raise TypeError(
                    "run_record_store must be a RunRecordStore or None"
                )

            if self.run_session is None:
                raise ValueError(
                    "run_record_store requires run_session"
                )

            if (
                self.run_record_store.run_id
                != self.run_session.run_id
            ):
                raise ValueError(
                    "run_record_store belongs to a different RunSession"
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

        if self.status_persistence_errors:
            details[
                "run_status_persistence_errors"
            ] = tuple(
                self.status_persistence_errors
            )

        if self.run_record_persistence_errors:
            details[
                "run_record_persistence_errors"
            ] = tuple(
                self.run_record_persistence_errors
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


def _finalize_run_record(
    execution: CanonicalSystemExecution,
    record: ExecutionRecord,
) -> None:
    """Publish immutable run.json once for a terminal execution.

    Final-record persistence belongs to historical durability.  A failure here
    must never change the already-observed terminal execution state.
    """

    if not record.terminal:
        return

    store = execution.run_record_store

    if (
        store is None
        or execution.final_run_recorded
    ):
        return

    try:
        store.create(
            record
        )
    except Exception as exc:
        error = (
            f"{type(exc).__name__}: {exc}"
        )

        if (
            not execution.run_record_persistence_errors
            or execution.run_record_persistence_errors[-1]
            != error
        ):
            execution.run_record_persistence_errors.append(
                error
            )
    else:
        execution.final_run_recorded = True


def start_canonical_system_execution(
    orchestrator: SystemOrchestrator,
    plan: PlanRecord,
    *,
    system_definition: SystemModel | None = None,
    execution_policy: ExecutionPolicy | None = None,
    environment_policy: RunEnvironmentPolicy | None = None,
    log_policy: RunLogPolicy | None = None,
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
        system_definition is not None
        and not isinstance(
            system_definition,
            SystemModel,
        )
    ):
        raise TypeError(
            "system_definition must be a SystemModel or None"
        )

    if (
        execution_policy is not None
        and not isinstance(
            execution_policy,
            ExecutionPolicy,
        )
    ):
        raise TypeError(
            "execution_policy must be an "
            "ExecutionPolicy or None"
        )

    if (
        environment_policy is not None
        and not isinstance(
            environment_policy,
            RunEnvironmentPolicy,
        )
    ):
        raise TypeError(
            "environment_policy must be a "
            "RunEnvironmentPolicy or None"
        )

    if (
        log_policy is not None
        and not isinstance(
            log_policy,
            RunLogPolicy,
        )
    ):
        raise TypeError(
            "log_policy must be a RunLogPolicy or None"
        )

    if (
        execution_policy is not None
        and (
            environment_policy is not None
            or log_policy is not None
        )
    ):
        raise ValueError(
            "execution_policy cannot be combined "
            "with environment_policy or log_policy"
        )

    effective_policy = (
        execution_policy
        if execution_policy is not None
        else ExecutionPolicy(
            environment=(
                environment_policy
                if environment_policy is not None
                else RunEnvironmentPolicy()
            ),
            logs=(
                log_policy
                if log_policy is not None
                else RunLogPolicy()
            ),
        )
    )

    if (
        effective_policy.metrics is not None
        and run_store is None
    ):
        raise ValueError(
            "canonical Metrics require a persistent RunStore"
        )

    if (
        run_store is not None
        and system_definition is None
    ):
        raise ValueError(
            "persistent canonical System execution "
            "requires system_definition"
        )

    definition_snapshot_content = None
    plan_snapshot_content = None

    if system_definition is not None:
        # Both serializers also verify that the supplied Definition and exact
        # resolved Plan belong to the same canonical System revision.
        definition_snapshot_content = (
            system_definition_snapshot(
                system_definition,
                plan,
            )
        )

        plan_snapshot_content = (
            system_plan_snapshot(
                plan
            )
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

    snapshot_store = (
        RunSnapshotStore(
            run_session
        )
        if run_session is not None
        else None
    )

    policy_store = (
        RunPolicyStore(
            run_session,
            policy=effective_policy,
        )
        if run_session is not None
        else None
    )

    environment_store = (
        RunEnvironmentStore(
            run_session,
            policy=effective_policy.environment,
        )
        if run_session is not None
        else None
    )

    log_store = (
        RunLogStore(
            run_session,
            policy=effective_policy.logs,
        )
        if run_session is not None
        else None
    )

    event_journal = (
        RunEventJournal(
            run_session
        )
        if run_session is not None
        else None
    )

    status_store = (
        RunStatusStore(
            run_session
        )
        if run_session is not None
        else None
    )

    run_record_store = (
        RunRecordStore(
            run_session
        )
        if run_session is not None
        else None
    )

    status_persistence_errors: list[
        str
    ] = []

    if run_session is not None:
        _write_run_status(
            status_store,
            status_persistence_errors,
            state=ExecutionState.CREATED,
            execution_id=None,
            observed_at=(
                run_session.created_at
            ),
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

    if snapshot_store is not None:
        if (
            definition_snapshot_content is None
            or plan_snapshot_content is None
        ):
            raise RuntimeError(
                "persistent Run snapshot content "
                "was not prepared"
            )

        try:
            snapshot_store.create(
                DEFINITION_SNAPSHOT,
                definition_snapshot_content,
            )

            snapshot_store.create(
                PLAN_SNAPSHOT,
                plan_snapshot_content,
            )
        except Exception as exc:
            try:
                persist_error(
                    stage="snapshot",
                    error=exc,
                )
            except Exception as event_exc:
                exc.add_note(
                    "failed to persist Run snapshot "
                    f"error event: {event_exc}"
                )

            failed_at = _now(
                clock
            )

            _write_run_status(
                status_store,
                status_persistence_errors,
                state=ExecutionState.FAILED,
                execution_id=None,
                message=str(exc),
                details={
                    "stage": "snapshot",
                    "errorType": (
                        type(exc).__name__
                    ),
                },
                observed_at=failed_at,
            )

            raise

    if policy_store is not None:
        try:
            policy_store.create()
        except Exception as exc:
            try:
                persist_error(
                    stage="policy",
                    error=exc,
                )
            except Exception as event_exc:
                exc.add_note(
                    "failed to persist Run policy "
                    f"error event: {event_exc}"
                )

            failed_at = _now(
                clock
            )

            _write_run_status(
                status_store,
                status_persistence_errors,
                state=ExecutionState.FAILED,
                execution_id=None,
                message=str(exc),
                details={
                    "stage": "policy",
                    "errorType": (
                        type(exc).__name__
                    ),
                },
                observed_at=failed_at,
            )

            raise

    if environment_store is not None:
        try:
            environment_store.capture(
                captured_at=_now(
                    clock
                ),
            )
        except Exception as exc:
            try:
                persist_error(
                    stage="environment",
                    error=exc,
                )
            except Exception as event_exc:
                exc.add_note(
                    "failed to persist Run environment "
                    f"error event: {event_exc}"
                )

            failed_at = _now(
                clock
            )

            _write_run_status(
                status_store,
                status_persistence_errors,
                state=ExecutionState.FAILED,
                execution_id=None,
                message=str(exc),
                details={
                    "stage": "environment",
                    "errorType": (
                        type(exc).__name__
                    ),
                },
                observed_at=failed_at,
            )

            raise

    metric_sink = None

    if effective_policy.metrics is not None:
        if run_session is None:
            raise RuntimeError(
                "canonical Metric policy requires RunSession"
            )

        metric_sink = RunMetricSink(
            RunMetricJournal(
                run_session,
                policy=effective_policy.metrics,
            )
        )

    try:
        prepared = orchestrator.prepare_plan(
            domain_plan,
            metric_sink=metric_sink,
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

        failed_at = _now(
            clock
        )

        _write_run_status(
            status_store,
            status_persistence_errors,
            state=ExecutionState.FAILED,
            execution_id=None,
            message=str(exc),
            details={
                "stage": "prepare",
                "errorType": (
                    type(exc).__name__
                ),
            },
            observed_at=failed_at,
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
    else:
        prepared_at = _now(
            clock
        )

    _write_run_status(
        status_store,
        status_persistence_errors,
        state=ExecutionState.PREPARED,
        execution_id=None,
        observed_at=prepared_at,
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

        failed_at = _now(
            clock
        )

        _write_run_status(
            status_store,
            status_persistence_errors,
            state=ExecutionState.FAILED,
            execution_id=None,
            message=str(exc),
            details={
                "stage": "start",
                "errorType": (
                    type(exc).__name__
                ),
            },
            observed_at=failed_at,
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

    running_at = _now(
        clock
    )

    _write_run_status(
        status_store,
        status_persistence_errors,
        state=ExecutionState.RUNNING,
        execution_id=(
            handle.execution_id
        ),
        observed_at=running_at,
    )

    return CanonicalSystemExecution(
        plan=plan,
        handle=handle,
        started_at=started_at,
        run_session=run_session,
        snapshot_store=snapshot_store,
        policy_store=policy_store,
        environment_store=environment_store,
        log_store=log_store,
        event_journal=event_journal,
        status_store=status_store,
        run_record_store=run_record_store,
        status_persistence_errors=(
            status_persistence_errors
        ),
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

    _write_run_status(
        execution.status_store,
        execution.status_persistence_errors,
        state=_execution_state(
            status
        ),
        execution_id=(
            status.execution_id
        ),
        message=status.message,
        details=_status_details(
            status
        ),
        observed_at=observed_at,
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

    record = execution.record(
        status,
        observed_at=observed_at,
    )

    _finalize_run_record(
        execution,
        record,
    )

    if execution.run_record_persistence_errors:
        # Re-snapshot so the caller sees historical persistence failures
        # discovered during finalization.
        record = execution.record(
            status,
            observed_at=observed_at,
        )

    return record


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

    stopping_at = _now(
        clock
    )

    _write_run_status(
        execution.status_store,
        execution.status_persistence_errors,
        state=ExecutionState.STOPPING,
        execution_id=(
            execution.execution_id
        ),
        observed_at=stopping_at,
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

    _write_run_status(
        execution.status_store,
        execution.status_persistence_errors,
        state=_execution_state(
            status
        ),
        execution_id=(
            status.execution_id
        ),
        message=status.message,
        details=_status_details(
            status
        ),
        observed_at=observed_at,
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

    record = execution.record(
        status,
        observed_at=observed_at,
    )

    _finalize_run_record(
        execution,
        record,
    )

    if execution.run_record_persistence_errors:
        # Re-snapshot so the caller sees historical persistence failures
        # discovered during finalization.
        record = execution.record(
            status,
            observed_at=observed_at,
        )

    return record


__all__ = [
    "CanonicalSystemExecution",
    "SYSTEM_ORCHESTRATOR_EXECUTOR",
    "inspect_canonical_system_execution",
    "start_canonical_system_execution",
    "stop_canonical_system_execution",
]
