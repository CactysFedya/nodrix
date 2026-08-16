"""Canonical contract for Nodrix domain Plan executors.

A PlanExecutor executes an already resolved canonical PlanRecord and returns
an ExecutionRecord describing the factual execution.

The contract intentionally starts *after* planning:

    Operation
        -> Planner
        -> PlanRecord
        -> PlanExecutor
        -> ExecutionRecord

Executors must not reconstruct Operation intent, resolve Definitions, create
top-level Run history, or act as System execution backends.

ExecutionBackend is a separate System-level control-plane contract.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import (
    ExecutionRecord,
    PlanRecord,
)


@runtime_checkable
class PlanExecutor(Protocol):
    """Minimum common contract implemented by domain Plan executors.

    Implementations may expose additional optional keyword-only execution
    controls, but they must support execution with the canonical PlanRecord
    as the only required argument.
    """

    @property
    def executor_id(self) -> str:
        """Return the stable canonical identifier of this executor."""
        ...

    def execute(
        self,
        plan: PlanRecord,
    ) -> ExecutionRecord:
        """Execute one already-resolved canonical PlanRecord."""
        ...


__all__ = [
    "PlanExecutor",
]
