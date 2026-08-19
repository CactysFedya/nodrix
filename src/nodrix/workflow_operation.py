"""Unified canonical execution path for workflow-backed operations.

This module connects the previously independent layers:

Operation
    -> WorkflowPlanResult
    -> PlanRecord
    -> WorkflowExecutor
    -> ExecutionRecord
    -> RunRecord
    -> nodrix.run/v1

CLI code should use this service instead of invoking run_workflow directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import (
    BENCHMARK,
    BUILD,
    CALIBRATE,
    CLEANUP,
    DIAGNOSE,
    EXPORT,
    OPTIMIZE,
    PACKAGE,
    PREPARE,
    PROFILE,
    TEST,
    VALIDATE,
    ExecutionRecord,
    Operation,
    OperationKind,
    PlanRecord,
)
from .project_canonical import (
    project_entity_ref,
    project_revision_ref,
)
from .workflow_canonical import workflow_plan_record
from .workflow_executor import WorkflowExecutor
from .execution_history import (
    PersistedRun,
)
from .foreground_operation import (
    persist_foreground_execution,
)
from .workflow_planning import (
    WorkflowPlanResult,
    plan_workflow,
)


WORKFLOW_RUN_OPERATION = OperationKind("workflow.run")

WORKFLOW_OPERATION_KINDS = {
    "prepare": PREPARE,
    "build": BUILD,
    "test": TEST,
    "validate": VALIDATE,
    "profile": PROFILE,
    "benchmark": BENCHMARK,
    "optimize": OPTIMIZE,
    "diagnose": DIAGNOSE,
    "calibrate": CALIBRATE,
    "export": EXPORT,
    "package": PACKAGE,
    "cleanup": CLEANUP,
}


@dataclass(frozen=True, slots=True)
class WorkflowOperationResult:
    """Result of one complete canonical workflow-backed operation."""

    plan: PlanRecord
    execution: ExecutionRecord
    history: PersistedRun

    @property
    def successful(self) -> bool:
        return self.execution.successful

    def legacy_result(self) -> dict[str, Any]:
        """Project canonical execution back to the existing CLI result shape."""

        domain_plan = self.plan.payload
        if not isinstance(domain_plan, WorkflowPlanResult):
            raise TypeError(
                "workflow operation plan payload is invalid"
            )

        details = self.execution.details

        started_at = (
            details.get("workflow_started_at")
            or (
                self.execution.started_at.isoformat()
                if self.execution.started_at is not None
                else ""
            )
        )

        finished_at = (
            details.get("workflow_finished_at")
            or (
                self.execution.finished_at.isoformat()
                if self.execution.finished_at is not None
                else ""
            )
        )

        raw_steps = details.get("steps", ())
        steps = [
            dict(item)
            for item in raw_steps
            if isinstance(item, dict)
        ]

        return {
            "name": str(
                details.get(
                    "workflow",
                    domain_plan.name,
                )
            ),
            "status": str(
                details.get(
                    "workflow_status",
                    self.execution.state.value,
                )
            ),
            "root": str(
                details.get(
                    "root",
                    domain_plan.root,
                )
            ),
            "workflow_path": str(
                details.get(
                    "workflow_path",
                    domain_plan.workflow_path,
                )
            ),
            "run_directory": str(
                details.get(
                    "run_directory",
                    "",
                )
            ),
            "started_at": str(started_at),
            "finished_at": str(finished_at),
            "steps": steps,
        }


def resolve_workflow_operation_kind(
    workflow: str,
    *,
    declared: OperationKind | str | None = None,
    requested: OperationKind | str | None = None,
) -> OperationKind:
    """Resolve the canonical OperationKind implemented by one workflow.

    Conventional engineering workflow names map to their canonical built-in
    operation kinds.  Unknown workflow names remain valid and use the generic
    ``workflow.run`` kind.

    A Workflow Definition may bind itself through ``implements``.  Callers
    may still explicitly override that binding through ``requested``.

    Precedence is:

    explicit request -> declared binding -> conventional workflow name
    -> generic ``workflow.run``.
    """

    if not isinstance(workflow, str):
        raise TypeError("workflow must be a string")

    normalized = workflow.strip().lower()
    if not normalized:
        raise ValueError("workflow must be non-empty")

    if requested is not None:
        return OperationKind.parse(requested)

    if declared is not None:
        return OperationKind.parse(declared)

    return WORKFLOW_OPERATION_KINDS.get(
        normalized,
        WORKFLOW_RUN_OPERATION,
    )


def execute_workflow_operation(
    workflow: str,
    *,
    root: str | Path | None = None,
    environment_name: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    operation_kind: OperationKind | str | None = None,
    executor: WorkflowExecutor | None = None,
) -> WorkflowOperationResult:
    """Plan, execute and persist one workflow-backed canonical Operation."""

    domain_plan = plan_workflow(
        workflow,
        root=root,
        environment_name=environment_name,
        dry_run=dry_run,
        force=force,
    )

    entity = project_entity_ref(
        domain_plan.root
    )
    revision = project_revision_ref(
        domain_plan.root
    )

    parameters: dict[str, object] = {
        "workflow": workflow,
        "dry_run": dry_run,
        "force": force,
    }

    if environment_name is not None:
        parameters["environment"] = environment_name

    operation = Operation(
        kind=resolve_workflow_operation_kind(
            workflow,
            declared=domain_plan.implements,
            requested=operation_kind,
        ),
        subject=entity,
        subject_revision=revision,
        parameters=parameters,
    )

    canonical_plan = workflow_plan_record(
        domain_plan,
        operation=operation,
        subject_revision=revision,
        metadata={
            "operation_source": "workflow",
        },
    )

    selected_executor = (
        executor
        if executor is not None
        else WorkflowExecutor()
    )

    execution = selected_executor.execute(
        canonical_plan
    )

    outcome = persist_foreground_execution(
        canonical_plan,
        execution,
        project=domain_plan.root,
        summary={
            "workflow": workflow,
            "workflow_status": execution.details.get(
                "workflow_status",
                execution.state.value,
            ),
            "step_count": execution.details.get(
                "step_count",
                0,
            ),
        },
    )

    return WorkflowOperationResult(
        plan=canonical_plan,
        execution=execution,
        history=outcome.history,
    )


__all__ = [
    "WORKFLOW_RUN_OPERATION",
    "WorkflowOperationResult",
    "execute_workflow_operation",
    "resolve_workflow_operation_kind",
]
