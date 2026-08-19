"""Canonical foreground execution boundary for Nodrix Operations.

Foreground execution means that the caller does not receive a successful
operation result until one exact PlanRecord has produced a terminal
ExecutionRecord and that execution has been persisted as canonical Run history.

This module deliberately does not own domain execution semantics.

Registered extension operations may use the full path:

    Operation
        -> ExtensionDispatcher.plan()
        -> PlanRecord
        -> ExtensionDispatcher.execute()
        -> terminal ExecutionRecord
        -> persist_foreground_execution()
        -> RunRecord

Built-in domains with specialized executors may join at the exact
PlanRecord + ExecutionRecord boundary without forcing domain-specific executor
arguments into ExtensionDispatcher.

No background, detach, daemon, supervisor or process ownership semantics are
introduced here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .execution_history import (
    PersistedRun,
    persist_execution,
)
from .extension_dispatcher import (
    ExtensionDispatcher,
)
from .model import (
    ExecutionRecord,
    MaterializedRef,
    Operation,
    PlanRecord,
    RelationGraph,
)
from .planner_contract import (
    PlanningContext,
)


@dataclass(frozen=True, slots=True)
class ForegroundOperationResult:
    """Canonical foreground service result.

    This is an invocation result, not a new persistent domain record.
    Canonical persisted history remains RunRecord.
    """

    plan: PlanRecord
    execution: ExecutionRecord
    history: PersistedRun

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.plan,
            PlanRecord,
        ):
            raise TypeError(
                "plan must be a PlanRecord"
            )

        if not isinstance(
            self.execution,
            ExecutionRecord,
        ):
            raise TypeError(
                "execution must be an ExecutionRecord"
            )

        if not isinstance(
            self.history,
            PersistedRun,
        ):
            raise TypeError(
                "history must be a PersistedRun"
            )

        if (
            self.execution.plan
            is not self.plan
        ):
            raise ValueError(
                "execution must belong to "
                "the exact foreground PlanRecord"
            )

        if not self.execution.terminal:
            raise ValueError(
                "foreground operation requires "
                "a terminal ExecutionRecord"
            )

        if (
            self.history.run.execution
            is not self.execution
        ):
            raise ValueError(
                "persisted Run must contain "
                "the exact foreground ExecutionRecord"
            )

    @property
    def successful(
        self,
    ) -> bool:
        return self.execution.successful


def persist_foreground_execution(
    plan: PlanRecord,
    execution: ExecutionRecord,
    *,
    project: str | Path = ".",
    run_id: str | None = None,
    inputs: Iterable[MaterializedRef] = (),
    outputs: Iterable[MaterializedRef] = (),
    additional_provenance: RelationGraph | None = None,
    summary: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ForegroundOperationResult:
    """Persist one exact terminal foreground execution.

    The explicit ``plan`` argument freezes the service boundary invariant:
    persistence must describe the same exact PlanRecord that was executed.

    Non-terminal execution is rejected before Run persistence.
    """

    if not isinstance(
        plan,
        PlanRecord,
    ):
        raise TypeError(
            "plan must be a PlanRecord"
        )

    if not isinstance(
        execution,
        ExecutionRecord,
    ):
        raise TypeError(
            "execution must be an ExecutionRecord"
        )

    if execution.plan is not plan:
        raise ValueError(
            "execution must belong to "
            "the exact foreground PlanRecord"
        )

    if not execution.terminal:
        raise ValueError(
            "foreground operation requires "
            "a terminal ExecutionRecord"
        )

    history = persist_execution(
        execution,
        project=project,
        run_id=run_id,
        inputs=inputs,
        outputs=outputs,
        additional_provenance=(
            additional_provenance
        ),
        summary=summary,
        metadata=metadata,
    )

    return ForegroundOperationResult(
        plan=plan,
        execution=execution,
        history=history,
    )


def execute_foreground_operation(
    operation: Operation,
    *,
    dispatcher: ExtensionDispatcher,
    context: PlanningContext,
    project: str | Path = ".",
    run_id: str | None = None,
    inputs: Iterable[MaterializedRef] = (),
    outputs: Iterable[MaterializedRef] = (),
    additional_provenance: RelationGraph | None = None,
    summary: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ForegroundOperationResult:
    """Plan, execute and persist one registered Operation synchronously."""

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

    # Keep planning and execution explicit instead of using dispatch().
    # This makes the exact PlanRecord a first-class boundary value.
    plan = dispatcher.plan(
        operation,
        context=context,
    )

    execution = dispatcher.execute(
        plan
    )

    return persist_foreground_execution(
        plan,
        execution,
        project=project,
        run_id=run_id,
        inputs=inputs,
        outputs=outputs,
        additional_provenance=(
            additional_provenance
        ),
        summary=summary,
        metadata=metadata,
    )


__all__ = [
    "ForegroundOperationResult",
    "execute_foreground_operation",
    "persist_foreground_execution",
]
