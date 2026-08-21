"""Internal direct System execution contract.

This module defines the narrow execution seam used by the future direct local
System runtime.

It deliberately does not introduce another execution model.  The direct
executor consumes and produces the canonical backend lifecycle objects already
owned by :mod:`nodrix.system.backend`:

    BackendContext
        -> PreparedExecution
        -> BackendExecutionHandle
        -> BackendExecutionStatus

Important architectural constraints:

* BackendContext is the only prepared runtime semantic input here.
* System YAML is never parsed by a direct executor.
* SystemExecutionPlan is not rebuilt or reinterpreted here.
* No PipelineManifest lowering is permitted.
* No HybridPipelineRuntime dependency is permitted.
* Execution state remains BackendExecutionState.
* The contract is internal until the direct runtime reaches parity.

The protocol is intentionally small.  Resource, application, node, transport
and graph materialization belong behind this boundary rather than in callers
such as the CLI or System orchestrator.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .backend import (
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionStatus,
    PreparedExecution,
)


@runtime_checkable
class DirectSystemExecutor(Protocol):
    """Internal engine capable of executing one local BackendContext directly.

    This is not a second public backend API.  ``ExecutionBackend`` remains the
    backend-neutral contract used by orchestration.  A local backend may
    delegate its concrete execution work to an implementation of this protocol.
    """

    def prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        """Materialize direct-runtime state for one validated context."""
        ...

    def start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        """Start one prepared direct execution."""
        ...

    def inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        """Return the current canonical backend execution status."""
        ...

    def stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None = None,
    ) -> BackendExecutionStatus:
        """Request bounded shutdown and return canonical execution status."""
        ...


__all__ = [
    "DirectSystemExecutor",
]
