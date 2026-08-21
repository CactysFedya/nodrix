from __future__ import annotations

import pytest

from nodrix.system import (
    BackendCapabilities,
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    ExecutionScope,
    Graph,
    NodeInstance,
    PreparedExecution,
    SystemModel,
    Target,
    plan_execution_scopes,
    plan_system,
)
from nodrix.system.canonical import (
    system_plan_record,
)
from nodrix.system_execution_frontend import (
    build_system_orchestrator,
    hierarchical_execution_scopes,
    system_execution_plan,
)


class FrontendBackend(
    ExecutionBackend
):
    def __init__(
        self,
        backend_id: str,
    ) -> None:
        super().__init__(
            backend_id,
            capabilities=BackendCapabilities(
                target_kinds={
                    "host",
                },
            ),
        )

    def _prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
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
            execution_id=(
                f"{self.backend_id}-execution"
            ),
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


def _plan():
    return plan_system(
        SystemModel(
            name="execution-frontend",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={
                        "backend": "local",
                    },
                ),
                Target(
                    name="server",
                    kind="host",
                    properties={
                        "backend": "remote",
                    },
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="capture",
                            uses="demo.capture",
                            target="robot",
                        ),
                        NodeInstance(
                            name="analysis",
                            uses="demo.analysis",
                            target="server",
                        ),
                    ),
                ),
            ),
        )
    )


def test_domain_and_canonical_plan_normalize_to_same_exact_plan() -> None:
    plan = _plan()

    canonical = (
        system_plan_record(
            plan
        )
    )

    assert (
        system_execution_plan(
            plan
        )
        is plan
    )

    assert (
        system_execution_plan(
            canonical
        )
        is plan
    )


def test_hierarchical_scopes_preserve_planner_order() -> None:
    plan = _plan()

    expected = (
        plan_execution_scopes(
            plan
        )
    )

    assert expected == (
        ExecutionScope(
            "robot",
            "local",
        ),
        ExecutionScope(
            "server",
            "remote",
        ),
    )

    assert (
        hierarchical_execution_scopes(
            plan
        )
        == expected
    )

    assert (
        hierarchical_execution_scopes(
            system_plan_record(
                plan
            )
        )
        == expected
    )


def test_backend_factory_is_called_once_per_unique_scope() -> None:
    plan = _plan()

    calls: list[
        ExecutionScope
    ] = []

    def factory(
        scope: ExecutionScope,
    ):
        calls.append(
            scope
        )

        return FrontendBackend(
            scope.backend
        )

    orchestrator = (
        build_system_orchestrator(
            plan,
            backend_factory=factory,
        )
    )

    assert tuple(
        calls
    ) == (
        plan_execution_scopes(
            plan
        )
    )

    assert tuple(
        orchestrator.bindings
    ) == tuple(
        calls
    )


def test_missing_binding_remains_canonical_orch101() -> None:
    plan = _plan()

    orchestrator = (
        build_system_orchestrator(
            plan,
            backend_factory=(
                lambda scope: (
                    FrontendBackend(
                        "local"
                    )
                    if scope.backend
                    == "local"
                    else None
                )
            ),
        )
    )

    report = (
        orchestrator.validate_plan(
            plan
        )
    )

    assert not report.valid

    assert any(
        item.code
        == "ORCH101"
        and item.scope
        == ExecutionScope(
            "server",
            "remote",
        )
        for item
        in report.errors
    )


def test_backend_mismatch_remains_canonical_orch102() -> None:
    plan = _plan()

    orchestrator = (
        build_system_orchestrator(
            plan,
            backend_factory=(
                lambda scope: (
                    FrontendBackend(
                        "wrong-backend"
                    )
                    if scope.backend
                    == "remote"
                    else FrontendBackend(
                        scope.backend
                    )
                )
            ),
        )
    )

    report = (
        orchestrator.validate_plan(
            plan
        )
    )

    assert not report.valid

    assert any(
        item.code
        == "ORCH102"
        and item.scope
        == ExecutionScope(
            "server",
            "remote",
        )
        for item
        in report.errors
    )


def test_invalid_backend_factory_result_fails_at_frontend_boundary() -> None:
    with pytest.raises(
        TypeError,
        match=(
            "ExecutionBackend or None"
        ),
    ):
        build_system_orchestrator(
            _plan(),
            backend_factory=(
                lambda scope: object()
            ),
        )
