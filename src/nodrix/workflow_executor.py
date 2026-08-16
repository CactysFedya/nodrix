"""Canonical executor adapter for Nodrix workflows.

WorkflowExecutor executes the exact WorkflowPlanResult carried by the
canonical PlanRecord:

PlanRecord(kind=workflow)
    -> execute_workflow_plan(payload)
    -> ExecutionRecord

It deliberately does not create RunRecord history.  Durable history belongs
to the next layer after execution reaches a terminal canonical state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from .model import (
    WORKFLOW,
    ExecutionRecord,
    ExecutionState,
    PlanRecord,
)
from .workflow_execution import (
    WorkflowRunResult,
    execute_workflow_plan,
)
from .workflow_planning import WorkflowPlanResult


WORKFLOW_EXECUTOR = "nodrix.workflow"

Clock = Callable[[], datetime]
WorkflowRunner = Callable[..., WorkflowRunResult]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now(clock: Clock) -> datetime:
    if not callable(clock):
        raise TypeError("clock must be callable")

    value = clock()

    if not isinstance(value, datetime):
        raise TypeError("clock result must be a datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock result must be timezone-aware")

    return value


def _validate_workflow_plan_record(
    plan: PlanRecord,
) -> WorkflowPlanResult:
    if not isinstance(plan, PlanRecord):
        raise TypeError("plan must be a PlanRecord")

    if plan.kind != WORKFLOW:
        raise ValueError(
            "WorkflowExecutor requires a workflow PlanRecord"
        )

    if not isinstance(plan.payload, WorkflowPlanResult):
        raise TypeError(
            "workflow PlanRecord payload must be a WorkflowPlanResult"
        )

    return plan.payload


def _boolean_parameter(
    plan: PlanRecord,
    name: str,
    *,
    default: bool = False,
) -> bool:
    value = plan.operation.parameters.get(name, default)

    if not isinstance(value, bool):
        raise TypeError(
            f"operation parameter {name!r} must be a boolean"
        )

    return value


class WorkflowExecutor:
    """Execute the exact workflow payload carried by a canonical plan."""

    def __init__(
        self,
        *,
        runner: WorkflowRunner = execute_workflow_plan,
        clock: Clock = _utc_now,
    ) -> None:
        if not callable(runner):
            raise TypeError("runner must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")

        self._runner = runner
        self._clock = clock

    @property
    def executor_id(self) -> str:
        return WORKFLOW_EXECUTOR

    def execute(
        self,
        plan: PlanRecord,
    ) -> ExecutionRecord:
        """Execute one canonical workflow plan to a terminal record."""

        domain_plan = _validate_workflow_plan_record(plan)

        force = _boolean_parameter(
            plan,
            "force",
        )
        dry_run = _boolean_parameter(
            plan,
            "dry_run",
        )

        execution_id = f"workflow-{uuid4().hex[:12]}"
        started_at = _now(self._clock)

        try:
            result = self._runner(
                domain_plan,
                dry_run=dry_run,
                force=force,
            )
        except Exception as exc:
            finished_at = _now(self._clock)

            return ExecutionRecord(
                execution_id=execution_id,
                plan=plan,
                executor=self.executor_id,
                state=ExecutionState.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                details={
                    "workflow": domain_plan.name,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                },
            )

        if not isinstance(result, WorkflowRunResult):
            raise TypeError(
                "workflow runner must return a WorkflowRunResult"
            )

        finished_at = _now(self._clock)

        state = (
            ExecutionState.COMPLETED
            if result.succeeded or dry_run
            else ExecutionState.FAILED
        )

        return ExecutionRecord(
            execution_id=execution_id,
            plan=plan,
            executor=self.executor_id,
            state=state,
            started_at=started_at,
            finished_at=finished_at,
            details={
                "workflow": result.name,
                "workflow_status": result.status,
                "dry_run": dry_run,
                "force": force,
                "root": result.root,
                "workflow_path": result.workflow_path,
                "run_directory": result.run_directory,
                "workflow_started_at": result.started_at,
                "workflow_finished_at": result.finished_at,
                "step_count": len(result.steps),
                "steps": tuple(
                    {
                        "step_id": step.step_id,
                        "status": step.status,
                        "command": step.command,
                        "returncode": step.returncode,
                        "duration_seconds": step.duration_seconds,
                        "log_path": step.log_path,
                        "detail": step.detail,
                    }
                    for step in result.steps
                ),
            },
        )


__all__ = [
    "WORKFLOW_EXECUTOR",
    "WorkflowExecutor",
]
