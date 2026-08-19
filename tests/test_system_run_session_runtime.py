from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import pytest

from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.run_events import RunEventJournal
from nodrix.redaction import (
    DEFAULT_REDACTION_MARKER,
)
from nodrix.run_environment import (
    RunEnvironmentPolicy,
    RunEnvironmentStore,
)
from nodrix.run_logs import (
    RunLogPolicy,
)
from nodrix.run_policy import (
    RunPolicyStore,
)
from nodrix.run_record import RunRecordStore
from nodrix.run_recovery import (
    ACTIVE_OR_UNKNOWN,
    FAILED_BEFORE_START,
    HEALTHY_TERMINAL,
    INCOMPLETE,
    INTERRUPTED,
    inspect_run_directory,
)
from nodrix.run_session import RunStore
from nodrix.run_snapshots import (
    DEFINITION_SNAPSHOT,
    PLAN_SNAPSHOT,
)
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


def _system() -> SystemModel:
    return SystemModel(name='persistent-runtime', targets=(Target(name='host', kind='host', properties={'backend': 'local'}),), graphs=(Graph(name='main', nodes=(NodeInstance(name='worker', uses='demo.worker', target='host'),)),))



def _plan():

    return plan_canonical_system(
        _system()
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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
            system_definition=_system(),
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


def test_persistent_runtime_requires_exact_system_definition(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_missing_definition"
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

    with pytest.raises(
        ValueError,
        match="system_definition",
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

    # Invalid API/provenance input is rejected before a Run is created.
    assert not (
        root / run_id
    ).exists()


def test_definition_and_plan_snapshots_exist_before_backend_prepare(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_snapshots_before_prepare"
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

    original_prepare = (
        orchestrator.prepare_plan
    )

    prepare_observed = False

    def guarded_prepare(
        domain_plan,
        *args,
        **kwargs,
    ):
        nonlocal prepare_observed

        directory = (
            root / run_id
        )

        assert (
            directory
            / "session.json"
        ).is_file()

        assert (
            directory
            / "definition.json"
        ).is_file()

        assert (
            directory
            / "plan.json"
        ).is_file()

        prepare_observed = True

        return original_prepare(
            domain_plan,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        orchestrator,
        "prepare_plan",
        guarded_prepare,
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            system_definition=_system(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert prepare_observed

    assert (
        execution.snapshot_store
        is not None
    )

    definition = (
        execution.snapshot_store.read(
            DEFINITION_SNAPSHOT
        )
    )

    exact_plan = (
        execution.snapshot_store.read(
            PLAN_SNAPSHOT
        )
    )

    assert definition is not None
    assert exact_plan is not None

    assert (
        definition["content"]["revision"]
        == execution.plan.subject_revision.canonical
    )

    assert (
        exact_plan["content"]["planId"]
        == execution.plan.plan_id
    )

    assert (
        exact_plan["content"]["payload"]
        == execution.plan.payload.model_dump(
            mode="json",
            by_alias=True,
        )
    )


def test_mismatched_system_definition_is_rejected_before_run_creation(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_wrong_definition"
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

    mismatched = SystemModel(
        name=_system().name,
        description=(
            "different immutable revision"
        ),
    )

    with pytest.raises(
        ValueError,
        match="revision",
    ):
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            system_definition=mismatched,
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )

    assert not (
        root / run_id
    ).exists()


def test_snapshot_publication_failure_prevents_backend_prepare(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_snapshot_failure"
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

    prepare_called = False

    original_prepare = (
        orchestrator.prepare_plan
    )

    def guarded_prepare(
        *args,
        **kwargs,
    ):
        nonlocal prepare_called
        prepare_called = True

        return original_prepare(
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        orchestrator,
        "prepare_plan",
        guarded_prepare,
    )

    import nodrix.run_snapshots as snapshots

    original_link = (
        snapshots.os.link
    )

    calls = 0

    def fail_plan_publication(
        source,
        destination,
    ):
        nonlocal calls
        calls += 1

        # definition.json succeeds; plan.json publication fails.
        if calls == 2:
            raise OSError(
                "synthetic plan snapshot failure"
            )

        return original_link(
            source,
            destination,
        )

    monkeypatch.setattr(
        snapshots.os,
        "link",
        fail_plan_publication,
    )

    with pytest.raises(
        OSError,
        match="synthetic plan snapshot failure",
    ):
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            system_definition=_system(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )

    assert not prepare_called

    directory = (
        root / run_id
    )

    # Run identity survives; recovery can diagnose incomplete provenance.
    assert (
        directory
        / "session.json"
    ).is_file()

    assert (
        directory
        / "definition.json"
    ).is_file()

    assert not (
        directory
        / "plan.json"
    ).exists()

    status = json.loads(
        (
            directory
            / "status.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        status["state"]
        == "failed"
    )

    assert (
        status["details"]["stage"]
        == "snapshot"
    )


def test_environment_snapshot_exists_before_backend_prepare(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_environment_before_prepare"
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

    original_prepare = (
        orchestrator.prepare_plan
    )

    prepare_observed = False

    def guarded_prepare(
        domain_plan,
        *args,
        **kwargs,
    ):
        nonlocal prepare_observed

        directory = (
            root / run_id
        )

        assert (
            directory
            / "definition.json"
        ).is_file()

        assert (
            directory
            / "plan.json"
        ).is_file()

        assert (
            directory
            / "environment.json"
        ).is_file()

        prepare_observed = True

        return original_prepare(
            domain_plan,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        orchestrator,
        "prepare_plan",
        guarded_prepare,
    )

    execution = (
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            system_definition=_system(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert prepare_observed

    assert (
        execution.environment_store
        is not None
    )

    document = (
        execution.environment_store
        .read()
    )

    assert document is not None

    assert (
        document["runId"]
        == run_id
    )

    assert (
        document["planId"]
        == execution.plan.plan_id
    )

    # Default policy captures no process environment variables.
    assert (
        document["variables"]
        == {}
    )


def test_runtime_environment_allowlist_and_redaction(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_environment_allowlist"
    )

    monkeypatch.setenv(
        "NODRIX_TEST_MODE",
        "benchmark",
    )

    monkeypatch.setenv(
        "NODRIX_TEST_TOKEN",
        "must-not-leak",
    )

    monkeypatch.setenv(
        "NODRIX_UNLISTED_SECRET",
        "also-must-not-leak",
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
            system_definition=_system(),
            environment_policy=(
                RunEnvironmentPolicy(
                    variables=(
                        "NODRIX_TEST_MODE",
                        "NODRIX_TEST_TOKEN",
                    ),
                )
            ),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.environment_store
        is not None
    )

    document = (
        execution.environment_store
        .read()
    )

    assert document is not None

    assert (
        document["variables"][
            "NODRIX_TEST_MODE"
        ]
        == "benchmark"
    )

    assert (
        document["variables"][
            "NODRIX_TEST_TOKEN"
        ]
        == DEFAULT_REDACTION_MARKER
    )

    encoded = json.dumps(
        document
    )

    assert (
        "must-not-leak"
        not in encoded
    )

    assert (
        "also-must-not-leak"
        not in encoded
    )


def test_environment_publication_failure_prevents_backend_prepare(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_environment_failure"
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

    prepare_called = False

    original_prepare = (
        orchestrator.prepare_plan
    )

    def guarded_prepare(
        *args,
        **kwargs,
    ):
        nonlocal prepare_called

        prepare_called = True

        return original_prepare(
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        orchestrator,
        "prepare_plan",
        guarded_prepare,
    )

    def fail_capture(
        self,
        *,
        environ=None,
        captured_at=None,
        extra=None,
    ):
        raise OSError(
            "synthetic environment provenance failure"
        )

    monkeypatch.setattr(
        RunEnvironmentStore,
        "capture",
        fail_capture,
    )

    with pytest.raises(
        OSError,
        match=(
            "synthetic environment "
            "provenance failure"
        ),
    ):
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            system_definition=_system(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )

    assert not prepare_called

    directory = (
        root / run_id
    )

    # Definition and Plan provenance already succeeded.
    assert (
        directory
        / "definition.json"
    ).is_file()

    assert (
        directory
        / "plan.json"
    ).is_file()

    assert not (
        directory
        / "environment.json"
    ).exists()

    status = json.loads(
        (
            directory
            / "status.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        status["state"]
        == "failed"
    )

    assert (
        status["details"]["stage"]
        == "environment"
    )


def test_non_persistent_runtime_does_not_require_environment_provenance(
    tmp_path,
) -> None:
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

    expected = (
        tmp_path
        / "no-persistent-run"
    )

    backend = CompatibilityBackend(
        expected_run_directory=expected,
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
            clock=_clock,
        )
    )

    assert (
        execution.run_session
        is None
    )

    assert (
        execution.environment_store
        is None
    )

    assert not expected.exists()


def test_persistent_runtime_has_disabled_log_store_by_default(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_default_logs"
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
            system_definition=_system(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.log_store
        is not None
    )

    assert not (
        execution.log_store
        .policy
        .enabled
    )

    assert not execution.log_store.write(
        "runtime",
        "critical",
        "default mode remains quiet",
        recorded_at=NOW,
    )

    assert not (
        execution.log_store
        .path(
            "runtime"
        )
        .exists()
    )


def test_runtime_exposes_configured_sdk_logging(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_sdk_logs"
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
            system_definition=_system(),
            log_policy=RunLogPolicy(
                enabled=True,
                min_level="info",
                categories=(
                    "sdk",
                ),
            ),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.log_store
        is not None
    )

    assert execution.log_store.write(
        "sdk.perception",
        "info",
        "custom SDK diagnostic",
        fields={
            "frame": 42,
        },
        recorded_at=NOW,
    )

    assert (
        execution.log_store
        .path(
            "sdk.perception"
        )
        .is_file()
    )

    assert not execution.log_store.write(
        "executor.local",
        "error",
        "category is filtered",
        recorded_at=NOW,
    )


def test_log_storage_failure_does_not_control_execution(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_broken_log_storage"
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
            system_definition=_system(),
            log_policy=RunLogPolicy(
                enabled=True,
                min_level="debug",
            ),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.log_store
        is not None
    )

    def fail_append(
        path,
        encoded,
    ) -> None:
        raise OSError(
            "synthetic optional log failure"
        )

    monkeypatch.setattr(
        execution.log_store,
        "_append",
        fail_append,
    )

    # Optional diagnostics fail...
    assert not execution.log_store.write(
        "runtime",
        "error",
        "diagnostic only",
        recorded_at=NOW,
    )

    assert (
        execution.log_store
        .stats()[
            "persistenceErrors"
        ]
    )

    # ...but execution control remains intact.
    record = (
        stop_canonical_system_execution(
            orchestrator,
            execution,
            clock=_clock,
        )
    )

    assert record.terminal
    assert record.successful


def test_non_persistent_runtime_has_no_log_store(
    tmp_path,
) -> None:
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

    backend = CompatibilityBackend(
        expected_run_directory=(
            tmp_path
            / "unused"
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
            clock=_clock,
        )
    )

    assert (
        execution.log_store
        is None
    )


def test_real_completed_run_passes_recovery_integrity(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_recovery_completed"
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
            system_definition=_system(),
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

    report = inspect_run_directory(
        root / run_id
    )

    assert (
        report.classification
        == HEALTHY_TERMINAL
    ), report.issues

    assert report.terminal
    assert report.final_record_present
    assert not report.corrupted

    assert (
        report.execution_id
        == record.execution_id
    )


def test_real_running_run_is_active_or_interrupted_only_with_owner_knowledge(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_recovery_running"
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
            system_definition=_system(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    default_report = (
        inspect_run_directory(
            root / run_id
        )
    )

    assert (
        default_report.classification
        == ACTIVE_OR_UNKNOWN
    ), default_report.issues

    assert (
        default_report.recovered_state
        == "running"
    )

    inactive_report = (
        inspect_run_directory(
            root / run_id,
            assume_inactive=True,
        )
    )

    assert (
        inactive_report.classification
        == INTERRUPTED
    )

    assert (
        inactive_report.execution_id
        is not None
    )

    # The test still owns this in-memory execution; terminate it normally.
    stop_canonical_system_execution(
        orchestrator,
        execution,
        clock=_clock,
    )


def test_real_prepare_failure_is_recoverable_without_final_run_record(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_recovery_prepare_failure"
    )

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
        match="synthetic prepare failure",
    ):
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            system_definition=_system(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )

    report = inspect_run_directory(
        root / run_id
    )

    assert (
        report.classification
        == FAILED_BEFORE_START
    ), report.issues

    assert (
        report.recovered_state
        == "failed"
    )

    assert not (
        report.final_record_present
    )


def test_real_events_recover_running_state_when_status_cache_is_missing(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_recovery_without_status"
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
            system_definition=_system(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    status_path = (
        root
        / run_id
        / "status.json"
    )

    status_path.unlink()

    report = inspect_run_directory(
        root / run_id
    )

    # status.json is only a reconstructible cache.  Its absence makes the
    # persisted Run incomplete, but durable events still recover the last
    # execution state and identity.
    assert (
        report.classification
        == INCOMPLETE
    ), report.issues

    assert (
        report.recovered_state
        == "running"
    )

    assert (
        report.execution_id
        is not None
    )

    assert any(
        issue.code == "REC105"
        for issue in report.issues
    )

    stop_canonical_system_execution(
        orchestrator,
        execution,
        clock=_clock,
    )



def test_runtime_accepts_explicit_default_execution_policy(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_explicit_default_execution_policy"
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
            system_definition=_system(),
            execution_policy=ExecutionPolicy(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.environment_store
        is not None
    )
    assert (
        execution.log_store
        is not None
    )

    environment = (
        execution.environment_store
        .read()
    )

    assert environment is not None
    assert environment["variables"] == {}

    assert (
        execution.log_store
        .policy
        .enabled
        is False
    )


def test_runtime_execution_policy_controls_environment_and_logs(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_unified_execution_policy"
    )

    monkeypatch.setenv(
        "NODRIX_POLICY_MODE",
        "debug",
    )

    environment_policy = (
        RunEnvironmentPolicy(
            variables=(
                "NODRIX_POLICY_MODE",
            ),
        )
    )

    log_policy = RunLogPolicy(
        enabled=True,
        min_level="info",
        categories=(
            "sdk",
        ),
    )

    policy = ExecutionPolicy(
        environment=environment_policy,
        logs=log_policy,
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
            system_definition=_system(),
            execution_policy=policy,
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.environment_store
        is not None
    )
    assert (
        execution.log_store
        is not None
    )

    environment = (
        execution.environment_store
        .read()
    )

    assert environment is not None
    assert (
        environment["variables"][
            "NODRIX_POLICY_MODE"
        ]
        == "debug"
    )

    assert (
        execution.log_store
        .policy
        is log_policy
    )

    assert execution.log_store.write(
        "sdk.policy",
        "info",
        "unified policy is active",
        recorded_at=NOW,
    )

    assert not execution.log_store.write(
        "executor.local",
        "error",
        "category remains filtered",
        recorded_at=NOW,
    )


def test_legacy_environment_and_log_policy_arguments_remain_compatible(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_legacy_execution_policy_compat"
    )

    monkeypatch.setenv(
        "NODRIX_LEGACY_MODE",
        "compat",
    )

    log_policy = RunLogPolicy(
        enabled=True,
        min_level="warning",
        categories=(
            "legacy",
        ),
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
            system_definition=_system(),
            environment_policy=(
                RunEnvironmentPolicy(
                    variables=(
                        "NODRIX_LEGACY_MODE",
                    ),
                )
            ),
            log_policy=log_policy,
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.environment_store
        is not None
    )
    assert (
        execution.log_store
        is not None
    )

    environment = (
        execution.environment_store
        .read()
    )

    assert environment is not None
    assert (
        environment["variables"][
            "NODRIX_LEGACY_MODE"
        ]
        == "compat"
    )

    assert (
        execution.log_store
        .policy
        is log_policy
    )

    assert execution.log_store.write(
        "legacy.adapter",
        "warning",
        "legacy policy compatibility",
        recorded_at=NOW,
    )


def test_runtime_rejects_mixed_unified_and_legacy_policy_arguments(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    orchestrator = SystemOrchestrator(
        {
            (
                "host",
                "local",
            ): ObservingBackend(
                expected_run_directory=(
                    root / "unused"
                ),
            ),
        }
    )

    conflicts = (
        {
            "environment_policy":
                RunEnvironmentPolicy(),
        },
        {
            "log_policy":
                RunLogPolicy(
                    enabled=True
                ),
        },
    )

    for index, conflict in enumerate(
        conflicts,
        start=1,
    ):
        run_id = (
            f"run_policy_conflict_{index}"
        )

        with pytest.raises(
            ValueError,
            match=(
                "execution_policy cannot be combined "
                "with environment_policy or log_policy"
            ),
        ):
            start_canonical_system_execution(
                orchestrator,
                _plan(),
                system_definition=_system(),
                execution_policy=ExecutionPolicy(),
                run_store=RunStore(
                    root,
                    clock=_clock,
                ),
                run_id=run_id,
                clock=_clock,
                **conflict,
            )

        # Conflict validation happens before Run identity
        # or backend preparation is created.
        assert not (
            root / run_id
        ).exists()



def test_runtime_persists_unified_execution_policy(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_persisted_execution_policy"
    )

    monkeypatch.setenv(
        "NODRIX_POLICY_TEST",
        "enabled",
    )

    policy = ExecutionPolicy(
        environment=(
            RunEnvironmentPolicy(
                variables=(
                    "NODRIX_POLICY_TEST",
                ),
            )
        ),
        logs=RunLogPolicy(
            enabled=True,
            min_level="info",
            categories=(
                "sdk",
                "mapping",
            ),
            max_bytes=4096,
            max_category_bytes=2048,
            max_record_bytes=1024,
            overflow="drop",
        ),
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    execution = (
        start_canonical_system_execution(
            SystemOrchestrator(
                {
                    (
                        "host",
                        "local",
                    ): backend,
                }
            ),
            _plan(),
            system_definition=_system(),
            execution_policy=policy,
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.policy_store
        is not None
    )

    document = (
        execution.policy_store
        .read()
    )

    assert document is not None

    assert (
        document["runId"]
        == run_id
    )

    assert (
        document["planId"]
        == execution.plan.plan_id
    )

    assert (
        document["environment"][
            "variables"
        ]
        == [
            "NODRIX_POLICY_TEST",
        ]
    )

    assert (
        document["logs"][
            "enabled"
        ]
        is True
    )

    assert (
        document["logs"][
            "categories"
        ]
        == [
            "mapping",
            "sdk",
        ]
    )

    assert (
        root
        / run_id
        / "policy.json"
    ).is_file()


def test_runtime_persists_effective_legacy_policy(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_persisted_legacy_policy"
    )

    legacy_environment = (
        RunEnvironmentPolicy(
            variables=(
                "RMW_IMPLEMENTATION",
                "ROS_DOMAIN_ID",
            ),
        )
    )

    legacy_logs = RunLogPolicy(
        enabled=True,
        min_level="warning",
        categories=(
            "legacy",
        ),
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    execution = (
        start_canonical_system_execution(
            SystemOrchestrator(
                {
                    (
                        "host",
                        "local",
                    ): backend,
                }
            ),
            _plan(),
            system_definition=_system(),
            environment_policy=(
                legacy_environment
            ),
            log_policy=legacy_logs,
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.policy_store
        is not None
    )

    document = (
        execution.policy_store
        .read()
    )

    assert document is not None

    assert (
        document["environment"][
            "variables"
        ]
        == [
            "RMW_IMPLEMENTATION",
            "ROS_DOMAIN_ID",
        ]
    )

    assert (
        document["logs"][
            "enabled"
        ]
        is True
    )

    assert (
        document["logs"][
            "categories"
        ]
        == [
            "legacy",
        ]
    )


def test_policy_publication_failure_prevents_backend_prepare(
    tmp_path,
    monkeypatch,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_policy_storage_failure"
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    orchestrator = SystemOrchestrator(
        {
            (
                "host",
                "local",
            ): backend,
        }
    )

    def fail_policy_create(
        self,
    ):
        raise OSError(
            "synthetic policy storage failure"
        )

    monkeypatch.setattr(
        RunPolicyStore,
        "create",
        fail_policy_create,
    )

    with pytest.raises(
        OSError,
        match=(
            "synthetic policy storage failure"
        ),
    ):
        start_canonical_system_execution(
            orchestrator,
            _plan(),
            system_definition=_system(),
            execution_policy=(
                ExecutionPolicy()
            ),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )

    # Run identity and exact snapshots already exist as evidence.
    run_directory = (
        root / run_id
    )

    assert run_directory.is_dir()

    assert (
        run_directory
        / "session.json"
    ).is_file()

    assert (
        run_directory
        / "definition.json"
    ).is_file()

    assert (
        run_directory
        / "plan.json"
    ).is_file()

    # Policy publication failed before environment provenance
    # and before backend preparation.
    assert not (
        run_directory
        / "policy.json"
    ).exists()

    assert not (
        run_directory
        / "environment.json"
    ).exists()

    assert (
        backend.prepare_observed_run
        is False
    )

    status = json.loads(
        (
            run_directory
            / "status.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        status["state"]
        == "failed"
    )

    assert (
        status["details"][
            "stage"
        ]
        == "policy"
    )

    events = [
        json.loads(line)
        for line in (
            run_directory
            / "events.jsonl"
        ).read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    assert any(
        item[
            "event"
        ][
            "details"
        ].get(
            "stage"
        )
        == "policy"
        for item in events
    )


def test_canonical_metrics_disabled_does_not_create_metric_storage(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_metrics_disabled"
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    execution = (
        start_canonical_system_execution(
            SystemOrchestrator(
                {
                    (
                        "host",
                        "local",
                    ): backend,
                }
            ),
            _plan(),
            system_definition=_system(),
            execution_policy=ExecutionPolicy(),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert (
        execution.run_session
        is not None
    )

    assert not (
        root
        / run_id
        / "metrics"
    ).exists()

    policy_document = json.loads(
        (
            root
            / run_id
            / "policy.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        policy_document["metrics"]
        is None
    )


def test_canonical_metrics_publish_into_run_metric_journal(
    tmp_path,
    monkeypatch,
) -> None:
    from nodrix.metric_publisher import (
        MetricPublisher,
    )
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )
    from nodrix.run_metrics import (
        RunMetricJournal,
    )

    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_metrics_enabled"
    )

    metric_policy = RunMetricPolicy(
        max_records=32,
        max_bytes=1024 * 1024,
        max_record_bytes=64 * 1024,
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    original_prepare = (
        SystemOrchestrator.prepare_plan
    )

    results = []

    def prepare_with_metric(
        self,
        plan,
        *args,
        **kwargs,
    ):
        metric_sink = kwargs.get(
            "metric_sink"
        )

        assert metric_sink is not None

        # Provenance must exist before Metrics become available to execution.
        assert (
            root
            / run_id
            / "policy.json"
        ).is_file()

        if not results:
            publisher = MetricPublisher(
                source="runtime-test",
                sink=metric_sink,
            )

            results.append(
                publisher.observe(
                    "runtime.items",
                    1,
                    value_type="integer",
                    unit="count",
                )
            )

        return original_prepare(
            self,
            plan,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        SystemOrchestrator,
        "prepare_plan",
        prepare_with_metric,
    )

    execution = (
        start_canonical_system_execution(
            SystemOrchestrator(
                {
                    (
                        "host",
                        "local",
                    ): backend,
                }
            ),
            _plan(),
            system_definition=_system(),
            execution_policy=ExecutionPolicy(
                metrics=metric_policy
            ),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    assert len(results) == 1
    assert results[0].accepted

    assert (
        execution.run_session
        is not None
    )

    metric_path = (
        root
        / run_id
        / "metrics"
        / "records.jsonl"
    )

    assert metric_path.is_file()

    records = (
        RunMetricJournal(
            execution.run_session,
            policy=metric_policy,
        )
        .read_all()
    )

    assert len(records) == 1

    assert (
        records[0].run_id
        == run_id
    )

    assert (
        records[0].metric.name
        == "runtime.items"
    )

    assert (
        records[0].metric.value
        == 1
    )

    assert (
        records[0].metric.source
        == "runtime-test"
    )

    policy_document = json.loads(
        (
            root
            / run_id
            / "policy.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        policy_document["metrics"]
        == {
            "maxRecords": 32,
            "maxBytes": 1024 * 1024,
            "maxRecordBytes": 64 * 1024,
            "overflow": "drop",
        }
    )


def test_canonical_metric_quota_loss_does_not_fail_prepare(
    tmp_path,
    monkeypatch,
) -> None:
    from nodrix.metric_publisher import (
        MetricPublisher,
    )
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )

    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_metrics_quota"
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    original_prepare = (
        SystemOrchestrator.prepare_plan
    )

    results = []

    def prepare_with_metric_loss(
        self,
        plan,
        *args,
        **kwargs,
    ):
        metric_sink = kwargs.get(
            "metric_sink"
        )

        assert metric_sink is not None

        if not results:
            publisher = MetricPublisher(
                source="runtime-test",
                sink=metric_sink,
            )

            results.append(
                publisher.observe(
                    "runtime.items",
                    1,
                    value_type="integer",
                    unit="count",
                )
            )

            results.append(
                publisher.observe(
                    "runtime.items",
                    2,
                    value_type="integer",
                    unit="count",
                )
            )

        return original_prepare(
            self,
            plan,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        SystemOrchestrator,
        "prepare_plan",
        prepare_with_metric_loss,
    )

    execution = (
        start_canonical_system_execution(
            SystemOrchestrator(
                {
                    (
                        "host",
                        "local",
                    ): backend,
                }
            ),
            _plan(),
            system_definition=_system(),
            execution_policy=ExecutionPolicy(
                metrics=RunMetricPolicy(
                    max_records=1,
                    max_bytes=1024 * 1024,
                    max_record_bytes=64 * 1024,
                )
            ),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
            run_id=run_id,
            clock=_clock,
        )
    )

    # Metric loss is not a control-plane prepare failure.
    assert (
        backend.prepare_observed_run
        is True
    )

    assert (
        execution.run_session
        is not None
    )

    assert len(results) == 2

    assert results[0].accepted

    assert not (
        results[1].accepted
    )

    assert (
        results[1].reason
        == "record-limit"
    )

    status = json.loads(
        (
            root
            / run_id
            / "metrics"
            / "status.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        status["lossOccurred"]
        is True
    )

    assert (
        status["droppedRecords"]
        == 1
    )

    assert (
        status["lastDropReason"]
        == "record-limit"
    )


def test_canonical_metric_storage_failure_does_not_fail_execution(
    tmp_path,
    monkeypatch,
) -> None:
    from nodrix.metric_publisher import (
        MetricPublisher,
    )
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )
    from nodrix.run_metrics import (
        RunMetricJournal,
    )

    root = (
        tmp_path
        / "runs"
    )

    run_id = (
        "run_metrics_storage_failure"
    )

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    def fail_append(
        self,
        metric,
        *,
        recorded_at=None,
    ):
        raise OSError(
            "synthetic canonical Metric "
            "storage failure"
        )

    monkeypatch.setattr(
        RunMetricJournal,
        "append",
        fail_append,
    )

    original_prepare = (
        SystemOrchestrator.prepare_plan
    )

    results = []

    def prepare_with_failed_metric(
        self,
        plan,
        *args,
        **kwargs,
    ):
        metric_sink = kwargs.get(
            "metric_sink"
        )

        assert metric_sink is not None

        if not results:
            publisher = MetricPublisher(
                source="runtime-test",
                sink=metric_sink,
            )

            results.append(
                publisher.observe(
                    "runtime.items",
                    1,
                    value_type="integer",
                    unit="count",
                )
            )

        return original_prepare(
            self,
            plan,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        SystemOrchestrator,
        "prepare_plan",
        prepare_with_failed_metric,
    )

    execution = (
        start_canonical_system_execution(
            SystemOrchestrator(
                {
                    (
                        "host",
                        "local",
                    ): backend,
                }
            ),
            _plan(),
            system_definition=_system(),
            execution_policy=ExecutionPolicy(
                metrics=RunMetricPolicy()
            ),
            run_store=RunStore(
                root,
                clock=_clock,
            ),
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

    assert len(results) == 1

    assert not (
        results[0].accepted
    )

    assert (
        results[0].reason
        == "storage-error"
    )


def test_canonical_metrics_require_persistent_run_store(
    tmp_path,
) -> None:
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )

    backend = ObservingBackend(
        expected_run_directory=(
            tmp_path
            / "unused-run"
        ),
    )

    with pytest.raises(
        ValueError,
        match="persistent RunStore",
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
            _plan(),
            system_definition=_system(),
            execution_policy=ExecutionPolicy(
                metrics=RunMetricPolicy()
            ),
        )

    assert (
        backend.prepare_observed_run
        is False
    )


def test_runtime_persists_minimal_observability_profile_as_effective_policy(
    tmp_path,
) -> None:
    root = tmp_path / "runs"
    run_id = "run_observability_minimal"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    execution = start_canonical_system_execution(
        SystemOrchestrator(
            {
                (
                    "host",
                    "local",
                ): backend,
            }
        ),
        _plan(),
        system_definition=_system(),
        observability_profile="minimal",
        run_store=RunStore(
            root,
            clock=_clock,
        ),
        run_id=run_id,
        clock=_clock,
    )

    assert execution.run_session is not None
    assert backend.prepare_observed_run is True

    document = json.loads(
        (
            root
            / run_id
            / "policy.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert document["logs"]["enabled"] is False
    assert document["metrics"] is None

    assert not (
        root
        / run_id
        / "metrics"
    ).exists()


def test_runtime_persists_standard_observability_profile_as_effective_policy(
    tmp_path,
) -> None:
    root = tmp_path / "runs"
    run_id = "run_observability_standard"

    backend = ObservingBackend(
        expected_run_directory=(
            root / run_id
        ),
    )

    execution = start_canonical_system_execution(
        SystemOrchestrator(
            {
                (
                    "host",
                    "local",
                ): backend,
            }
        ),
        _plan(),
        system_definition=_system(),
        observability_profile="standard",
        run_store=RunStore(
            root,
            clock=_clock,
        ),
        run_id=run_id,
        clock=_clock,
    )

    assert execution.run_session is not None
    assert backend.prepare_observed_run is True

    document = json.loads(
        (
            root
            / run_id
            / "policy.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert document["logs"]["enabled"] is True
    assert document["logs"]["minLevel"] == "warning"

    assert (
        document["metrics"]["maxRecords"]
        == 100_000
    )

    assert (
        document["metrics"]["maxBytes"]
        == 4 * 1024 * 1024
    )


@pytest.mark.parametrize(
    "conflicting",
    (
        "execution_policy",
        "environment_policy",
        "log_policy",
    ),
)
def test_runtime_rejects_ambiguous_observability_profile_policy_combinations(
    conflicting,
    tmp_path,
) -> None:
    backend = ObservingBackend(
        expected_run_directory=(
            tmp_path / "unused-run"
        ),
    )

    kwargs = {
        "observability_profile": "minimal",
    }

    if conflicting == "execution_policy":
        kwargs["execution_policy"] = (
            ExecutionPolicy()
        )
    elif conflicting == "environment_policy":
        kwargs["environment_policy"] = (
            RunEnvironmentPolicy()
        )
    elif conflicting == "log_policy":
        kwargs["log_policy"] = (
            RunLogPolicy()
        )
    else:
        raise AssertionError(
            conflicting
        )

    with pytest.raises(
        ValueError,
        match=(
            "observability_profile cannot "
            "be combined"
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
            _plan(),
            **kwargs,
        )

    assert (
        backend.prepare_observed_run
        is False
    )


def test_runtime_rejects_unknown_observability_profile_before_prepare(
    tmp_path,
) -> None:
    backend = ObservingBackend(
        expected_run_directory=(
            tmp_path / "unused-run"
        ),
    )

    with pytest.raises(
        ValueError,
        match="unsupported observability profile",
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
            _plan(),
            observability_profile=(
                "not-a-profile"
            ),
        )

    assert (
        backend.prepare_observed_run
        is False
    )


def test_runtime_custom_observability_uses_execution_policy_instead(
    tmp_path,
) -> None:
    backend = ObservingBackend(
        expected_run_directory=(
            tmp_path / "unused-run"
        ),
    )

    with pytest.raises(
        ValueError,
        match="requires custom_policy",
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
            _plan(),
            observability_profile="custom",
        )

    assert (
        backend.prepare_observed_run
        is False
    )


def test_observability_profile_changes_policy_not_plan_identity(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    plan = _plan()
    system = _system()

    first_backend = ObservingBackend(
        expected_run_directory=(
            root / "run_observability_plan_a"
        ),
    )

    second_backend = ObservingBackend(
        expected_run_directory=(
            root / "run_observability_plan_b"
        ),
    )

    start_canonical_system_execution(
        SystemOrchestrator(
            {
                (
                    "host",
                    "local",
                ): first_backend,
            }
        ),
        plan,
        system_definition=system,
        observability_profile="minimal",
        run_store=RunStore(
            root,
            clock=_clock,
        ),
        run_id="run_observability_plan_a",
        clock=_clock,
    )

    start_canonical_system_execution(
        SystemOrchestrator(
            {
                (
                    "host",
                    "local",
                ): second_backend,
            }
        ),
        plan,
        system_definition=system,
        observability_profile="debug",
        run_store=RunStore(
            root,
            clock=_clock,
        ),
        run_id="run_observability_plan_b",
        clock=_clock,
    )

    first_plan = json.loads(
        (
            root
            / "run_observability_plan_a"
            / "plan.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    second_plan = json.loads(
        (
            root
            / "run_observability_plan_b"
            / "plan.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        first_plan["planId"]
        == second_plan["planId"]
    )

    assert (
        first_plan["runId"]
        != second_plan["runId"]
    )

    first_plan_without_run = dict(
        first_plan
    )
    second_plan_without_run = dict(
        second_plan
    )

    first_plan_without_run.pop(
        "runId"
    )
    second_plan_without_run.pop(
        "runId"
    )

    assert (
        first_plan_without_run
        == second_plan_without_run
    )

    first_policy = json.loads(
        (
            root
            / "run_observability_plan_a"
            / "policy.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    second_policy = json.loads(
        (
            root
            / "run_observability_plan_b"
            / "policy.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert first_policy != second_policy

    assert (
        first_policy["metrics"]
        is None
    )

    assert (
        second_policy["metrics"]
        is not None
    )
