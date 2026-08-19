from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import pytest

from nodrix.run_events import RunEventJournal
from nodrix.run_record import RunRecordStore
from nodrix.run_session import RunStore
from nodrix.run_status import RunStatusStore
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
    inspect_canonical_system_execution,
    start_canonical_system_execution,
    stop_canonical_system_execution,
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


def _event_names(
    execution,
) -> list[str]:
    assert execution.event_journal is not None

    return [
        record["event"]["event"]
        for record
        in execution.event_journal.read_all()
    ]


def test_persistent_runtime_records_prepared_and_started_events(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / ".nodrix"
        / "runs"
    )
    run_id = "run_event_lifecycle"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert _event_names(
        execution
    ) == [
        "prepared",
        "started",
    ]

    records = (
        execution.event_journal
        .read_all()
    )

    assert [
        record["sequence"]
        for record in records
    ] == [1, 2]

    assert all(
        record["runId"]
        == run_id
        for record in records
    )


def test_inspect_does_not_append_polling_snapshots(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = "run_no_poll_events"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    before = _event_names(
        execution
    )

    inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=_clock,
    )

    inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=_clock,
    )

    assert _event_names(
        execution
    ) == before


def test_stop_records_stopping_and_finished_once(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = "run_stop_events"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    record = (
        stop_canonical_system_execution(
            orchestrator,
            execution,
            clock=_clock,
        )
    )

    assert record.terminal

    assert _event_names(
        execution
    ) == [
        "prepared",
        "started",
        "stopping",
        "finished",
    ]

    # Re-inspection of an already terminal execution must not duplicate the
    # final event.
    inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=_clock,
    )

    assert _event_names(
        execution
    ) == [
        "prepared",
        "started",
        "stopping",
        "finished",
    ]


def test_event_persistence_failure_before_start_prevents_execution(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = "run_event_storage_failure"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    start_called = False
    original_start = orchestrator.start

    def guarded_start(*args, **kwargs):
        nonlocal start_called
        start_called = True
        return original_start(
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        orchestrator,
        "start",
        guarded_start,
    )

    def fail_append(
        self,
        event,
        *,
        recorded_at=None,
    ):
        raise OSError(
            "synthetic disk full"
        )

    monkeypatch.setattr(
        RunEventJournal,
        "append",
        fail_append,
    )

    with pytest.raises(
        OSError,
        match="synthetic disk full",
    ):
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )

    # prepare() may already have completed, but actual execution must not
    # begin without the mandatory durable PREPARED event.
    assert start_called is False

    # Persistent Run identity still survives for diagnostics/recovery.
    directory = (
        root
        / run_id
    )

    assert directory.is_dir()
    assert (
        directory
        / "session.json"
    ).is_file()


def test_event_persistence_failure_after_start_does_not_block_stop(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = "run_stop_with_broken_events"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.event_journal
        is not None
    )

    def fail_append(
        event,
        *,
        recorded_at=None,
    ):
        raise OSError(
            "synthetic disk full"
        )

    monkeypatch.setattr(
        execution.event_journal,
        "append",
        fail_append,
    )

    record = (
        stop_canonical_system_execution(
            orchestrator,
            execution,
            clock=_clock,
        )
    )

    assert record.terminal
    assert record.successful

    errors = record.details[
        "run_event_persistence_errors"
    ]

    assert len(errors) >= 1
    assert any(
        "synthetic disk full" in error
        for error in errors
    )


def _run_status(
    execution,
):
    assert (
        execution.status_store
        is not None
    )

    document = (
        execution.status_store.read()
    )

    assert document is not None

    return document


def test_persistent_runtime_has_running_live_status(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = "run_live_status"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    status = _run_status(
        execution
    )

    assert (
        status["state"]
        == "running"
    )
    assert (
        status["executionId"]
        == execution.execution_id
    )

    # created -> prepared -> running
    assert (
        status["generation"]
        == 3
    )


def test_repeated_unchanged_inspection_does_not_rewrite_status(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = "run_status_polling"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    # First inspection enriches the running status with actual scope details.
    inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=_clock,
    )

    first = _run_status(
        execution
    )

    inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=_clock,
    )

    second = _run_status(
        execution
    )

    assert (
        second["generation"]
        == first["generation"]
    )

    assert second == first


def test_stop_updates_live_status_to_terminal_state(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = "run_terminal_status"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    record = (
        stop_canonical_system_execution(
            orchestrator,
            execution,
            clock=_clock,
        )
    )

    assert record.terminal

    status = _run_status(
        execution
    )

    assert (
        status["state"]
        == "stopped"
    )
    assert status["terminal"]
    assert status["successful"]

    # created -> prepared -> running -> stopping -> stopped
    assert (
        status["generation"]
        == 5
    )


def test_prepare_failure_leaves_failed_live_status(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = "run_prepare_status_failure"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
        fail_prepare=True,
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    with pytest.raises(
        OrchestrationError,
    ):
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )

    document = json.loads(
        (
            root
            / run_id
            / "status.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        document["state"]
        == "failed"
    )
    assert document["terminal"]
    assert not document["successful"]
    assert (
        document["executionId"]
        is None
    )

    assert (
        document["details"]["stage"]
        == "prepare"
    )


def test_status_storage_failure_does_not_control_execution(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = "run_broken_status_storage"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    def fail_status(
        self,
        *,
        state,
        execution_id=None,
        message=None,
        details=None,
        updated_at=None,
    ):
        raise OSError(
            "synthetic status disk failure"
        )

    monkeypatch.setattr(
        RunStatusStore,
        "write_if_changed",
        fail_status,
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    # status.json is only a recoverable cache. Execution is still alive.
    assert (
        execution.execution_id
    )

    record = (
        stop_canonical_system_execution(
            orchestrator,
            execution,
            clock=_clock,
        )
    )

    assert record.terminal
    assert record.successful

    errors = record.details[
        "run_status_persistence_errors"
    ]

    assert errors
    assert any(
        "synthetic status disk failure"
        in item
        for item in errors
    )


def test_terminal_stop_publishes_immutable_run_record(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = (
        "run_final_runtime"
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.run_record_store
        is not None
    )

    assert not (
        execution.run_record_store
        .path.exists()
    )

    record = (
        stop_canonical_system_execution(
            orchestrator,
            execution,
            clock=_clock,
        )
    )

    assert record.terminal
    assert (
        execution.final_run_recorded
    )

    document = (
        execution.run_record_store
        .read()
    )

    assert document is not None

    assert (
        document["runId"]
        == run_id
    )

    assert (
        document["execution"][
            "executionId"
        ]
        == execution.execution_id
    )

    assert (
        document["execution"]["state"]
        == record.state.value
    )

    assert (
        document["execution"]["plan"][
            "planId"
        ]
        == execution.plan.plan_id
    )


def test_terminal_reinspection_never_rewrites_run_json(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = (
        "run_final_once"
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    stop_canonical_system_execution(
        orchestrator,
        execution,
        clock=_clock,
    )

    assert (
        execution.run_record_store
        is not None
    )

    path = (
        execution.run_record_store.path
    )

    first = path.read_bytes()

    inspect_canonical_system_execution(
        orchestrator,
        execution,
        clock=_clock,
    )

    second = path.read_bytes()

    assert second == first

    assert (
        execution.final_run_recorded
    )


def test_final_record_storage_failure_does_not_change_terminal_execution(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )
    run_id = (
        "run_final_storage_failure"
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            ("host", "local"): backend,
        }
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    def fail_create(
        self,
        execution_record,
        *,
        summary=None,
        metadata=None,
    ):
        raise OSError(
            "synthetic final record failure"
        )

    monkeypatch.setattr(
        RunRecordStore,
        "create",
        fail_create,
    )

    record = (
        stop_canonical_system_execution(
            orchestrator,
            execution,
            clock=_clock,
        )
    )

    # Execution already terminated successfully. Persistence failure cannot
    # retroactively turn it into an execution failure.
    assert record.terminal
    assert record.successful

    assert not (
        execution.final_run_recorded
    )

    assert (
        execution.run_record_store
        is not None
    )

    assert not (
        execution.run_record_store
        .path.exists()
    )

    errors = record.details[
        "run_record_persistence_errors"
    ]

    assert errors

    assert any(
        "synthetic final record failure"
        in item
        for item in errors
    )
