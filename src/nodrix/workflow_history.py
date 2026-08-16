"""Durable canonical history for completed workflow executions.

WorkflowExecutor owns execution.  This module owns the next boundary:
turning one terminal workflow ExecutionRecord into immutable canonical history.

The existing domain-neutral history and run-document primitives remain the
source of truth:

ExecutionRecord
    -> RunRecord
    -> lifecycle relations
    -> nodrix.run/v1
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .model import (
    WORKFLOW,
    ExecutionRecord,
    RelationGraph,
    RunRecord,
    record_run,
    run_lifecycle_relations,
)
from .run_document import write_run_document
from .workflow_executor import WORKFLOW_EXECUTOR


@dataclass(frozen=True, slots=True)
class PersistedWorkflowRun:
    """One workflow Run together with its canonical persisted evidence."""

    run: RunRecord
    provenance: RelationGraph
    path: Path


def _validate_workflow_execution(
    execution: ExecutionRecord,
) -> None:
    if not isinstance(execution, ExecutionRecord):
        raise TypeError(
            "execution must be an ExecutionRecord"
        )

    if execution.plan.kind != WORKFLOW:
        raise ValueError(
            "workflow history requires a workflow PlanRecord"
        )

    if execution.executor != WORKFLOW_EXECUTOR:
        raise ValueError(
            "workflow history requires a WorkflowExecutor execution"
        )

    if not execution.terminal:
        raise ValueError(
            "workflow history requires a terminal ExecutionRecord"
        )


def persist_workflow_execution(
    execution: ExecutionRecord,
    *,
    project: str | Path = ".",
    run_id: str | None = None,
    summary: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PersistedWorkflowRun:
    """Persist one terminal workflow execution as canonical Run history.

    By default the Run reuses the execution id.  Record kind keeps
    ``execution/<id>`` and ``run/<id>`` unambiguous while making retries
    deterministic and therefore compatible with immutable idempotent storage.
    """

    _validate_workflow_execution(execution)

    canonical_run_id = (
        execution.execution_id
        if run_id is None
        else run_id
    )

    run = record_run(
        execution,
        run_id=canonical_run_id,
        summary=summary,
        metadata=metadata,
    )

    provenance = run_lifecycle_relations(run)

    path = write_run_document(
        run,
        project=project,
        provenance=provenance,
    )

    return PersistedWorkflowRun(
        run=run,
        provenance=provenance,
        path=path,
    )


__all__ = [
    "PersistedWorkflowRun",
    "persist_workflow_execution",
]
