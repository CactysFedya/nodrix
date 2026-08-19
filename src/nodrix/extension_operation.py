"""Canonical Operation boundary for registered Nodrix extensions.

This module owns the durable Run boundary for one extension-backed Operation:

    Operation
        -> ExtensionDispatcher
        -> PlanRecord
        -> PlanExecutor
        -> ExecutionRecord
        -> canonical foreground boundary
        -> RunRecord

The dispatcher, planner and executor deliberately remain free of persistence.

The project storage location is supplied explicitly by the caller.  This
boundary does not infer a project from cwd, Definition identity, package
metadata, or executor state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .execution_history import (
    PersistedRun,
)
from .foreground_operation import (
    execute_foreground_operation,
)
from .extension_dispatcher import (
    ExtensionDispatcher,
)
from .model import (
    ExecutionRecord,
    Operation,
    PlanRecord,
)
from .planner_contract import (
    PlanningContext,
)


@dataclass(frozen=True, slots=True)
class ExtensionOperationResult:
    """Complete result of one persisted extension-backed Operation."""

    plan: PlanRecord
    execution: ExecutionRecord
    history: PersistedRun

    @property
    def successful(self) -> bool:
        return self.execution.successful


def execute_extension_operation(
    operation: Operation,
    *,
    dispatcher: ExtensionDispatcher,
    context: PlanningContext,
    project: str | Path,
    run_id: str | None = None,
    summary: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ExtensionOperationResult:
    """Plan, execute and persist one registered canonical Operation.

    Persistence happens exactly once after the dispatcher returns a canonical
    ExecutionRecord.  Non-terminal executions are rejected by the common
    persistence boundary rather than being converted into incomplete Runs.
    """

    if not isinstance(
        operation,
        Operation,
    ):
        raise TypeError(
            "operation must be an Operation"
        )

    if not isinstance(
        dispatcher,
        ExtensionDispatcher,
    ):
        raise TypeError(
            "dispatcher must be an ExtensionDispatcher"
        )

    if not isinstance(
        context,
        PlanningContext,
    ):
        raise TypeError(
            "context must be a PlanningContext"
        )

    outcome = execute_foreground_operation(
        operation,
        dispatcher=dispatcher,
        context=context,
        project=project,
        run_id=run_id,
        summary=summary,
        metadata=metadata,
    )

    return ExtensionOperationResult(
        plan=outcome.plan,
        execution=outcome.execution,
        history=outcome.history,
    )


__all__ = [
    "ExtensionOperationResult",
    "execute_extension_operation",
]
