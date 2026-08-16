"""Durable canonical history for terminal executions.

Execution domains own execution semantics.  This module owns the common
persistence boundary shared by workflows, systems, benchmarks and future
executors:

ExecutionRecord
    -> RunRecord
    -> lifecycle relations
    -> nodrix.run/v1

No domain-specific PlanKind or executor identity is required here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .model import (
    ExecutionRecord,
    MaterializedRef,
    RelationGraph,
    RunRecord,
    combine_provenance,
    record_run,
    run_io_relations,
    run_lifecycle_relations,
)
from .run_document import write_run_document


@dataclass(frozen=True, slots=True)
class PersistedRun:
    """One canonical Run together with its persisted provenance evidence."""

    run: RunRecord
    provenance: RelationGraph
    path: Path


def persist_execution(
    execution: ExecutionRecord,
    *,
    project: str | Path = ".",
    run_id: str | None = None,
    inputs: Iterable[MaterializedRef] = (),
    outputs: Iterable[MaterializedRef] = (),
    summary: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PersistedRun:
    """Persist one terminal execution as immutable canonical Run history."""

    if not isinstance(execution, ExecutionRecord):
        raise TypeError(
            "execution must be an ExecutionRecord"
        )

    if not execution.terminal:
        raise ValueError(
            "execution history requires a terminal ExecutionRecord"
        )

    if execution.started_at is None:
        raise ValueError(
            "execution history requires execution.started_at"
        )

    if execution.finished_at is None:
        raise ValueError(
            "execution history requires execution.finished_at"
        )

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

    provenance = combine_provenance(
        run_lifecycle_relations(run),
        run_io_relations(
            run,
            inputs=inputs,
            outputs=outputs,
        ),
    )

    path = write_run_document(
        run,
        project=project,
        provenance=provenance,
    )

    return PersistedRun(
        run=run,
        provenance=provenance,
        path=path,
    )


__all__ = [
    "PersistedRun",
    "persist_execution",
]
