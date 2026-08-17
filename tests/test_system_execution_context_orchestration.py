from __future__ import annotations

import pytest

from nodrix.system import (
    BackendCapabilities,
    BackendContext,
    BackendContractError,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    ExecutionScope,
    Graph,
    NodeInstance,
    PreparedExecution,
    SystemModel,
    SystemOrchestrator,
    plan_system,
)
from nodrix.system.execution_context import (
    SystemExecutionContext,
)


class CaptureBackend(ExecutionBackend):
    def __init__(self) -> None:
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds=frozenset(
                    {"local", "host"}
                ),
            ),
        )
        self.validated_context = None
        self.prepared_context = None

    def _validate(self, context):
        self.validated_context = context
        return ()

    def _prepare(self, context):
        self.prepared_context = context
        return PreparedExecution(
            backend="local",
            context=context,
        )

    def _start(self, prepared):
        return BackendExecutionHandle(
            backend="local",
            execution_id="capture-001",
            prepared=prepared,
        )

    def _inspect(self, handle):
        return BackendExecutionStatus(
            backend="local",
            execution_id=handle.execution_id,
            state=BackendExecutionState.COMPLETED,
        )

    def _stop(
        self,
        handle,
        *,
        timeout_seconds=None,
    ):
        return BackendExecutionStatus(
            backend="local",
            execution_id=handle.execution_id,
            state=BackendExecutionState.STOPPED,
        )


def _system() -> SystemModel:
    return SystemModel(
        name="context-orchestration",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                    ),
                ),
            ),
        ),
    )


def _context(
    value: str,
) -> SystemExecutionContext:
    return SystemExecutionContext(
        variables={
            "EXECUTION_VALUE": value,
        },
        runtime={
            "mode": "realtime",
            "engine": "unified",
        },
    )


def _orchestrator(
    backend: CaptureBackend,
) -> SystemOrchestrator:
    return SystemOrchestrator(
        {
            ExecutionScope(
                "local",
                "local",
            ): backend,
        }
    )


def test_orchestrator_passes_bound_context_to_backend() -> None:
    context = _context("field")

    plan = plan_system(
        _system(),
        execution_context=context,
    )

    backend = CaptureBackend()
    orchestrator = _orchestrator(
        backend
    )

    report = orchestrator.validate_plan(
        plan,
        execution_context=context,
    )

    assert report.valid is True

    prepared = orchestrator.prepare_plan(
        plan,
        execution_context=context,
    )

    assert (
        prepared.execution_context
        is context
    )

    assert (
        backend.prepared_context.execution_context
        is context
    )

    assert (
        prepared.scopes[
            0
        ].prepared.context.execution_context
        is context
    )


def test_bound_plan_requires_materialized_context() -> None:
    context = _context("field")

    plan = plan_system(
        _system(),
        execution_context=context,
    )

    backend = CaptureBackend()
    orchestrator = _orchestrator(
        backend
    )

    report = orchestrator.validate_plan(
        plan
    )

    assert report.valid is False
    assert report.errors[
        0
    ].code == "ORCH103"

    assert (
        "requires a materialized execution context"
        in report.errors[0].message
    )

    assert backend.validated_context is None


def test_orchestrator_rejects_context_digest_mismatch() -> None:
    plan = plan_system(
        _system(),
        execution_context=_context(
            "field"
        ),
    )

    wrong = _context(
        "laboratory"
    )

    backend = CaptureBackend()
    orchestrator = _orchestrator(
        backend
    )

    report = orchestrator.validate_plan(
        plan,
        execution_context=wrong,
    )

    assert report.valid is False
    assert report.errors[
        0
    ].code == "ORCH103"

    assert (
        "does not match"
        in report.errors[0].message
    )

    assert backend.validated_context is None


def test_unbound_plan_rejects_unexpected_context() -> None:
    plan = plan_system(
        _system()
    )

    backend = CaptureBackend()
    orchestrator = _orchestrator(
        backend
    )

    report = orchestrator.validate_plan(
        plan,
        execution_context=_context(
            "field"
        ),
    )

    assert report.valid is False
    assert report.errors[
        0
    ].code == "ORCH103"

    assert (
        "does not bind an execution context"
        in report.errors[0].message
    )


def test_backend_context_enforces_binding_without_orchestrator() -> None:
    plan = plan_system(
        _system(),
        execution_context=_context(
            "field"
        ),
    )

    with pytest.raises(
        BackendContractError,
        match="BACKEND208",
    ):
        BackendContext.from_plan(
            plan,
            "local",
            execution_context=_context(
                "laboratory"
            ),
        )


def test_execution_backend_prepare_plan_accepts_bound_context() -> None:
    context = _context(
        "field"
    )

    plan = plan_system(
        _system(),
        execution_context=context,
    )

    backend = CaptureBackend()

    prepared = backend.prepare_plan(
        plan,
        execution_context=context,
    )

    assert (
        prepared.context.execution_context
        is context
    )
