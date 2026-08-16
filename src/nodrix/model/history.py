"""Canonical execution history helpers.

This module turns a terminal ExecutionRecord into a durable RunRecord and
projects the embedded execution lifecycle into the canonical relation graph.

The helpers are domain-neutral: System execution, workflow execution, user
executors, and future execution domains can all use the same history model.
"""

from __future__ import annotations

from typing import Any, Mapping

from .executions import ExecutionRecord
from .plans import PlanRecord
from .references import RecordRef
from .relations import (
    EXECUTED_AS,
    RECORDED_AS,
    Relation,
    RelationGraph,
)
from .runs import RunRecord


def plan_record_ref(plan: PlanRecord) -> RecordRef:
    """Return the historical reference for one canonical plan."""

    if not isinstance(plan, PlanRecord):
        raise TypeError("plan must be a PlanRecord")

    return RecordRef(
        kind="plan",
        record_id=plan.plan_id,
    )


def execution_record_ref(
    execution: ExecutionRecord,
) -> RecordRef:
    """Return the historical reference for one canonical execution."""

    if not isinstance(execution, ExecutionRecord):
        raise TypeError(
            "execution must be an ExecutionRecord"
        )

    return RecordRef(
        kind="execution",
        record_id=execution.execution_id,
    )


def run_record_ref(run: RunRecord) -> RecordRef:
    """Return the historical reference for one canonical run."""

    if not isinstance(run, RunRecord):
        raise TypeError("run must be a RunRecord")

    return RecordRef(
        kind="run",
        record_id=run.run_id,
    )


def record_run(
    execution: ExecutionRecord,
    *,
    run_id: str,
    summary: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RunRecord:
    """Persist the semantic result of one terminal execution as a RunRecord.

    ID generation deliberately remains outside the canonical model.  CLI,
    executor, storage, or application layers may choose UUID, ULID, database
    sequence, or another compatible policy.
    """

    if not isinstance(execution, ExecutionRecord):
        raise TypeError(
            "execution must be an ExecutionRecord"
        )

    return RunRecord(
        run_id=run_id,
        execution=execution,
        summary=(
            {}
            if summary is None
            else summary
        ),
        metadata=(
            {}
            if metadata is None
            else metadata
        ),
    )


def run_lifecycle_relations(
    run: RunRecord,
) -> RelationGraph:
    """Project Plan -> Execution -> Run lifecycle into canonical relations."""

    if not isinstance(run, RunRecord):
        raise TypeError("run must be a RunRecord")

    plan_ref = plan_record_ref(
        run.plan
    )
    execution_ref = execution_record_ref(
        run.execution
    )
    canonical_run_ref = run_record_ref(
        run
    )

    return RelationGraph(
        relations=(
            Relation(
                source=plan_ref,
                kind=EXECUTED_AS,
                target=execution_ref,
            ),
            Relation(
                source=execution_ref,
                kind=RECORDED_AS,
                target=canonical_run_ref,
            ),
        )
    )


__all__ = [
    "execution_record_ref",
    "plan_record_ref",
    "record_run",
    "run_lifecycle_relations",
    "run_record_ref",
]
