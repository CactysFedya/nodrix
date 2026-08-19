from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from nodrix.run_session import RunStore
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
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.canonical_runtime import (
    start_canonical_system_execution,
)
from nodrix.system.orchestration import (
    OrchestrationError,
)


NOW = datetime(
    2026,
    8,
    19,
    5,
    20,
    0,
    tzinfo=timezone.utc,
)


def _clock() -> datetime:
    return NOW


def _plan():
    system = SystemModel(
        name="persistent-runtime",
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

    return plan_canonical_system(
        system
    )


class ObservingBackend(ExecutionBackend):
    def __init__(
        self,
        *,
        expected_run_directory: Path,
        fail_prepare: bool = False,
    ) -> None:
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds={"host"},
            ),
        )

        self.expected_run_directory = (
            expected_run_directory
        )
        self.fail_prepare = fail_prepare
        self.prepare_observed_run = False

    def _prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        directory = (
            self.expected_run_directory
        )

        assert directory.is_dir()
        assert (
            directory
            / "session.json"
        ).is_file()
        assert (
            directory
            / "README.md"
        ).is_file()
        assert (
            directory
            / "logs"
        ).is_dir()

        self.prepare_observed_run = True

        if self.fail_prepare:
            raise RuntimeError(
                "synthetic prepare failure"
            )

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
            execution_id="backend-001",
            prepared=prepared,
        )

    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=BackendExecutionState.RUNNING,
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=BackendExecutionState.STOPPED,
        )


def test_run_directory_exists_before_backend_prepare(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / ".nodrix"
        / "runs"
    )
    run_id = "run_runtime_001"

    expected = (
        root
        / run_id
    )

    backend = ObservingBackend(
        expected_run_directory=expected,
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    store = RunStore(
        root,
        clock=_clock,
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=store,
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        backend.prepare_observed_run
        is True
    )

    assert (
        execution.run_session
        is not None
    )
    assert (
        execution.run_id
        == run_id
    )
    assert (
        execution.run_session.directory
        == expected
    )


def test_prepare_failure_preserves_run_directory(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / ".nodrix"
        / "runs"
    )
    run_id = "run_failed_prepare"

    expected = (
        root
        / run_id
    )

    backend = ObservingBackend(
        expected_run_directory=expected,
        fail_prepare=True,
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    store = RunStore(
        root,
        clock=_clock,
    )

    with pytest.raises(
        OrchestrationError,
        match="synthetic prepare failure",
    ) as error:
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=store,
            run_id=run_id,
            clock=_clock,
        )

    assert error.value.code == "ORCH201"

    # The Run is intentionally durable even though execution never reached
    # backend start.
    assert expected.is_dir()
    assert (
        expected
        / "session.json"
    ).is_file()
    assert (
        expected
        / "README.md"
    ).is_file()
    assert (
        expected
        / "logs"
    ).is_dir()

    assert (
        backend.prepare_observed_run
        is True
    )


def test_run_id_requires_persistent_store() -> None:
    expected_directory = Path(
        "/unused"
    )

    backend = ObservingBackend(
        expected_run_directory=(
            expected_directory
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    with pytest.raises(
        ValueError,
        match="run_id requires run_store",
    ):
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_id="run_without_store",
            clock=_clock,
        )

    assert (
        backend.prepare_observed_run
        is False
    )


def test_existing_non_persistent_runtime_remains_supported(
    tmp_path,
) -> None:
    # Compatibility path for current internal callers.  CLI System execution
    # will later always provide a RunStore.
    expected = (
        tmp_path
        / "should-not-exist"
    )

    # This backend asserts persistence during prepare, so use a tiny variant
    # that does not require a Run directory for the legacy compatibility path.
    class CompatibilityBackend(
        ObservingBackend
    ):
        def _prepare(
            self,
            context: BackendContext,
        ) -> PreparedExecution:
            return PreparedExecution(
                backend=self.backend_id,
                context=context,
            )

    compatible = CompatibilityBackend(
        expected_run_directory=expected,
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): compatible,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            clock=_clock,
        )
    )

    assert execution.run_session is None
    assert execution.run_id is None
