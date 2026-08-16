"""Canonical dispatcher for Nodrix planning and execution extensions.

The dispatcher connects the extension contracts without owning their domain
logic:

    Operation
        -> ExtensionRegistry
        -> OperationPlanner
        -> PlanRecord
        -> ExtensionRegistry
        -> PlanExecutor
        -> ExecutionRecord

It deliberately does not persist Run history, discover packages, resolve
storage locations, or reinterpret domain intent.

Planning policy belongs to OperationPlanner and PlanningContext.
Execution policy belongs to PlanExecutor.
Run persistence belongs to the outer Operation boundary.
"""

from __future__ import annotations

from .extension_registry import ExtensionRegistry
from .model import (
    ExecutionRecord,
    Operation,
    PlanRecord,
)
from .planner_contract import PlanningContext


class ExtensionDispatcher:
    """Dispatch canonical Operations through registered extensions."""

    def __init__(
        self,
        registry: ExtensionRegistry,
    ) -> None:
        if not isinstance(
            registry,
            ExtensionRegistry,
        ):
            raise TypeError(
                "registry must be an ExtensionRegistry"
            )

        self._registry = registry

    @property
    def registry(
        self,
    ) -> ExtensionRegistry:
        return self._registry

    def plan(
        self,
        operation: Operation,
        *,
        context: PlanningContext,
    ) -> PlanRecord:
        """Resolve one Operation through its registered planner."""

        if not isinstance(
            operation,
            Operation,
        ):
            raise TypeError(
                "operation must be an Operation"
            )

        if not isinstance(
            context,
            PlanningContext,
        ):
            raise TypeError(
                "context must be a PlanningContext"
            )

        planner = (
            self._registry
            .planner_for(
                operation.kind
            )
        )

        plan = planner.plan(
            operation,
            context=context,
        )

        if not isinstance(
            plan,
            PlanRecord,
        ):
            raise TypeError(
                "OperationPlanner must return "
                "a PlanRecord"
            )

        if (
            plan.operation
            != operation
        ):
            raise ValueError(
                "planner returned a PlanRecord "
                "for a different Operation"
            )

        return plan

    def execute(
        self,
        plan: PlanRecord,
    ) -> ExecutionRecord:
        """Execute one exact PlanRecord through its registered executor."""

        if not isinstance(
            plan,
            PlanRecord,
        ):
            raise TypeError(
                "plan must be a PlanRecord"
            )

        executor = (
            self._registry
            .executor_for(
                plan.kind
            )
        )

        execution = (
            executor.execute(
                plan
            )
        )

        if not isinstance(
            execution,
            ExecutionRecord,
        ):
            raise TypeError(
                "PlanExecutor must return "
                "an ExecutionRecord"
            )

        if execution.plan is not plan:
            raise ValueError(
                "executor returned an ExecutionRecord "
                "for a different PlanRecord"
            )

        if (
            execution.executor
            != executor.executor_id
        ):
            raise ValueError(
                "ExecutionRecord executor must match "
                "the selected PlanExecutor"
            )

        return execution

    def dispatch(
        self,
        operation: Operation,
        *,
        context: PlanningContext,
    ) -> ExecutionRecord:
        """Plan and execute one Operation without persisting Run history."""

        plan = self.plan(
            operation,
            context=context,
        )

        return self.execute(
            plan
        )


__all__ = [
    "ExtensionDispatcher",
]
