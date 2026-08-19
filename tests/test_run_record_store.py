from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import json

import pytest

from nodrix.model.executions import (
    ExecutionRecord,
)
from nodrix.run_record import (
    RUN_RECORD_API_VERSION,
    RUN_RECORD_KIND,
    RunRecordCorruptionError,
    RunRecordStore,
)
from nodrix.run_session import (
    RunStore,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.model import (
    SystemModel,
)


STARTED = datetime(
    2026,
    8,
    19,
    6,
    30,
    0,
    tzinfo=timezone.utc,
)

FINISHED = datetime(
    2026,
    8,
    19,
    6,
    31,
    0,
    tzinfo=timezone.utc,
)


def _plan():
    return plan_canonical_system(
        SystemModel(
            name="final-run-demo"
        )
    )


def _session(
    tmp_path,
    *,
    plan=None,
):
    canonical_plan = (
        _plan()
        if plan is None
        else plan
    )

    return RunStore(
        tmp_path / "runs"
    ).create(
        canonical_plan,
        run_id="run_final_demo",
    )


def _terminal_execution(
    plan,
    *,
    state: str = "completed",
) -> ExecutionRecord:
    return ExecutionRecord(
        execution_id=(
            "execution-final-001"
        ),
        plan=plan,
        executor=(
            "test.executor"
        ),
        state=state,
        started_at=STARTED,
        finished_at=FINISHED,
        details={
            "answer": 42,
        },
    )


def test_final_record_does_not_exist_before_terminal_execution(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunRecordStore(
        session
    )

    assert (
        store.read()
        is None
    )

    assert not (
        store.path.exists()
    )


def test_store_publishes_canonical_final_run_record(
    tmp_path,
) -> None:
    plan = _plan()
    session = _session(
        tmp_path,
        plan=plan,
    )

    store = RunRecordStore(
        session
    )

    run = store.create(
        _terminal_execution(
            plan
        ),
        summary={
            "result": "ok",
        },
        metadata={
            "origin": "test",
        },
    )

    assert (
        run.run_id
        == session.run_id
    )

    document = (
        store.read()
    )

    assert document is not None

    assert (
        document["apiVersion"]
        == RUN_RECORD_API_VERSION
    )
    assert (
        document["kind"]
        == RUN_RECORD_KIND
    )
    assert (
        document["runId"]
        == session.run_id
    )

    execution = (
        document["execution"]
    )

    assert (
        execution["executionId"]
        == "execution-final-001"
    )
    assert (
        execution["state"]
        == "completed"
    )
    assert execution[
        "terminal"
    ]
    assert execution[
        "successful"
    ]

    assert (
        execution["plan"]["planId"]
        == plan.plan_id
    )

    assert (
        document["summary"]["result"]
        == "ok"
    )
    assert (
        document["metadata"]["origin"]
        == "test"
    )


def test_non_terminal_execution_cannot_be_finalized(
    tmp_path,
) -> None:
    plan = _plan()
    session = _session(
        tmp_path,
        plan=plan,
    )

    store = RunRecordStore(
        session
    )

    execution = ExecutionRecord(
        execution_id="execution-live",
        plan=plan,
        executor="test.executor",
        state="running",
        started_at=STARTED,
    )

    with pytest.raises(
        ValueError,
        match="terminal",
    ):
        store.create(
            execution
        )

    assert not (
        store.path.exists()
    )


def test_final_record_is_never_overwritten(
    tmp_path,
) -> None:
    plan = _plan()
    session = _session(
        tmp_path,
        plan=plan,
    )

    store = RunRecordStore(
        session
    )

    store.create(
        _terminal_execution(
            plan
        )
    )

    first = (
        store.path.read_bytes()
    )

    with pytest.raises(
        FileExistsError,
    ):
        store.create(
            _terminal_execution(
                plan,
                state="failed",
            )
        )

    assert (
        store.path.read_bytes()
        == first
    )


def test_failed_publication_does_not_leave_partial_run_json(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _plan()
    session = _session(
        tmp_path,
        plan=plan,
    )

    store = RunRecordStore(
        session
    )

    import nodrix.run_record as run_record

    def fail_link(
        source,
        destination,
    ) -> None:
        raise OSError(
            "synthetic publication failure"
        )

    monkeypatch.setattr(
        run_record.os,
        "link",
        fail_link,
    )

    with pytest.raises(
        OSError,
        match="synthetic publication failure",
    ):
        store.create(
            _terminal_execution(
                plan
            )
        )

    assert not (
        store.path.exists()
    )

    assert not list(
        session.directory.glob(
            ".run.*.tmp"
        )
    )


def test_final_record_rejects_different_plan(
    tmp_path,
) -> None:
    session_plan = _plan()

    session = _session(
        tmp_path,
        plan=session_plan,
    )

    other_plan = (
        plan_canonical_system(
            SystemModel(
                name="another-system"
            )
        )
    )

    store = RunRecordStore(
        session
    )

    with pytest.raises(
        ValueError,
        match="different .*PlanRecord",
    ):
        store.create(
            _terminal_execution(
                other_plan
            )
        )

    assert not (
        store.path.exists()
    )


def test_reader_detects_corrupted_final_record(
    tmp_path,
) -> None:
    plan = _plan()
    session = _session(
        tmp_path,
        plan=plan,
    )

    path = (
        session.directory
        / "run.json"
    )

    path.write_text(
        json.dumps(
            {
                "apiVersion": (
                    RUN_RECORD_API_VERSION
                ),
                "kind": (
                    RUN_RECORD_KIND
                ),
                "runId": (
                    session.run_id
                ),
                "execution": {
                    "executionId": (
                        "execution-final-001"
                    ),
                    "executor": (
                        "test.executor"
                    ),
                    "state": "running",
                    "terminal": False,
                    "successful": False,
                    "startedAt": (
                        "2026-08-19T06:30:00Z"
                    ),
                    "finishedAt": (
                        "2026-08-19T06:31:00Z"
                    ),
                    "details": {},
                    "plan": {
                        "planId": (
                            plan.plan_id
                        ),
                    },
                },
                "summary": {},
                "metadata": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunRecordCorruptionError,
        match="terminal",
    ):
        RunRecordStore(
            session
        ).read()
