from __future__ import annotations

import pytest

from nodrix.system import (
    BackendCapabilities,
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    Graph,
    NodeInstance,
    PreparedExecution,
    SystemModel,
    SystemOrchestrator,
    Target,
    plan_system,
)
from nodrix.system.canonical import (
    system_plan_record,
)
from nodrix.system.canonical_runtime import (
    start_canonical_system_execution,
    stop_canonical_system_execution,
)
from nodrix.system.execution_context import (
    SystemExecutionContext,
    SystemExecutionContextBindingError,
)


def _system() -> SystemModel:
    return SystemModel(
        name="canonical-context-runtime",
        targets=(
            Target(
                name="host",
                kind="host",
                properties={
                    "backend": "local",
                },
            ),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                        target="host",
                    ),
                ),
            ),
        ),
    )


class ContextBackend(
    ExecutionBackend
):
    def __init__(self) -> None:
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds={
                    "host",
                },
            ),
        )

        self.prepared_context: (
            BackendContext | None
        ) = None

    def _prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        self.prepared_context = context

        return PreparedExecution(
            backend=self.backend_id,
            context=context,
        )

    def _start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id="context-backend",
            prepared=prepared,
        )

    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=(
                handle.execution_id
            ),
            state=(
                BackendExecutionState.RUNNING
            ),
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        del timeout_seconds

        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=(
                handle.execution_id
            ),
            state=(
                BackendExecutionState.STOPPED
            ),
        )


def _context(
    *,
    model: str,
) -> SystemExecutionContext:
    return SystemExecutionContext(
        variables={
            "ROBOT_MODEL": model,
        },
        runtime={
            "mode": "benchmark",
        },
    )


def _plan(
    context: SystemExecutionContext,
):
    return system_plan_record(
        plan_system(
            _system(),
            execution_context=context,
        )
    )


def test_canonical_runtime_forwards_exact_execution_context() -> None:
    context = _context(
        model="mid360"
    )

    backend = ContextBackend()

    orchestrator = (
        SystemOrchestrator(
            {
                (
                    "host",
                    "local",
                ): backend,
            }
        )
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(
                context
            ),
            system_definition=_system(),
            execution_context=context,
        )
    )

    assert (
        backend.prepared_context
        is not None
    )

    assert (
        backend
        .prepared_context
        .execution_context
        == context
    )

    stop_canonical_system_execution(
        orchestrator,
        execution,
    )


def test_canonical_runtime_rejects_missing_bound_execution_context() -> None:
    context = _context(
        model="mid360"
    )

    backend = ContextBackend()

    with pytest.raises(
        SystemExecutionContextBindingError,
        match=(
            "requires a materialized "
            "execution context"
        ),
    ):
        start_canonical_system_execution(
            SystemOrchestrator(
                {
                    (
                        "host",
                        "local",
                    ): backend,
                }
            ),
            _plan(
                context
            ),
            system_definition=_system(),
        )

    assert (
        backend.prepared_context
        is None
    )


def test_canonical_runtime_rejects_different_execution_context() -> None:
    planned = _context(
        model="mid360"
    )

    supplied = _context(
        model="camera-only"
    )

    backend = ContextBackend()

    with pytest.raises(
        SystemExecutionContextBindingError,
        match="digest does not match",
    ):
        start_canonical_system_execution(
            SystemOrchestrator(
                {
                    (
                        "host",
                        "local",
                    ): backend,
                }
            ),
            _plan(
                planned
            ),
            system_definition=_system(),
            execution_context=supplied,
        )

    assert (
        backend.prepared_context
        is None
    )


def test_canonical_runtime_rejects_context_for_unbound_plan() -> None:
    system = _system()

    plan = system_plan_record(
        plan_system(
            system
        )
    )

    backend = ContextBackend()

    with pytest.raises(
        SystemExecutionContextBindingError,
        match=(
            "does not bind an execution context"
        ),
    ):
        start_canonical_system_execution(
            SystemOrchestrator(
                {
                    (
                        "host",
                        "local",
                    ): backend,
                }
            ),
            plan,
            system_definition=system,
            execution_context=_context(
                model="unexpected"
            ),
        )

    assert (
        backend.prepared_context
        is None
    )
