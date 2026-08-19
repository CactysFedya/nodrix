from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import json

import pytest

from nodrix.run_events import (
    RUN_EVENT_RECORD_API_VERSION,
    RUN_EVENT_RECORD_KIND,
    RunEventJournal,
    RunEventJournalCorruptionError,
)
from nodrix.run_session import (
    RunStore,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.execution_events import (
    ExecutionEvent,
    ExecutionEventKind,
)
from nodrix.system.model import (
    SystemModel,
)


CREATED = datetime(
    2026,
    8,
    19,
    5,
    30,
    0,
    tzinfo=timezone.utc,
)

RECORDED = datetime(
    2026,
    8,
    19,
    5,
    30,
    1,
    tzinfo=timezone.utc,
)


def _clock() -> datetime:
    return CREATED


def _session(tmp_path):
    plan = plan_canonical_system(
        SystemModel(
            name="event-demo"
        )
    )

    store = RunStore(
        tmp_path / "runs",
        clock=_clock,
    )

    return store.create(
        plan,
        run_id="run_event_demo",
    )


def _system_event(
    kind: ExecutionEventKind,
) -> dict:
    return ExecutionEvent(
        event=kind,
        system="event-demo",
        timestamp=RECORDED,
        execution_id=(
            "system-execution-001"
            if kind
            is ExecutionEventKind.STARTED
            else None
        ),
    ).to_dict()


def test_journal_is_created_only_on_first_event(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunEventJournal(
        session
    )

    assert not journal.path.exists()
    assert journal.next_sequence == 1

    journal.append(
        _system_event(
            ExecutionEventKind.PREPARED
        ),
        recorded_at=RECORDED,
    )

    assert journal.path.is_file()


def test_journal_wraps_domain_event_without_replacing_its_schema(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )
    journal = RunEventJournal(
        session
    )

    domain_event = _system_event(
        ExecutionEventKind.PREPARED
    )

    record = journal.append(
        domain_event,
        recorded_at=RECORDED,
    )

    assert (
        record["apiVersion"]
        == RUN_EVENT_RECORD_API_VERSION
    )
    assert (
        record["kind"]
        == RUN_EVENT_RECORD_KIND
    )
    assert (
        record["runId"]
        == session.run_id
    )
    assert record["sequence"] == 1

    assert (
        record["recordedAt"]
        == "2026-08-19T05:30:01.000000Z"
    )

    # The existing System event remains intact and self-describing.
    assert record["event"] == domain_event
    assert (
        record["event"]["apiVersion"]
        == "nodrix.execution.event/v1"
    )
    assert (
        record["event"]["kind"]
        == "ExecutionEvent"
    )


def test_journal_sequence_survives_reopen(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    first_writer = RunEventJournal(
        session
    )

    first_writer.append(
        _system_event(
            ExecutionEventKind.PREPARED
        ),
        recorded_at=RECORDED,
    )

    second_writer = RunEventJournal(
        session
    )

    assert (
        second_writer.next_sequence
        == 2
    )

    second_writer.append(
        _system_event(
            ExecutionEventKind.STARTED
        ),
        recorded_at=RECORDED,
    )

    records = (
        second_writer.read_all()
    )

    assert [
        item["sequence"]
        for item in records
    ] == [1, 2]


def test_journal_is_jsonl_append_only(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )
    journal = RunEventJournal(
        session
    )

    journal.append(
        _system_event(
            ExecutionEventKind.PREPARED
        ),
        recorded_at=RECORDED,
    )
    journal.append(
        _system_event(
            ExecutionEventKind.STARTED
        ),
        recorded_at=RECORDED,
    )

    raw = journal.path.read_text(
        encoding="utf-8"
    )

    lines = raw.splitlines()

    assert len(lines) == 2

    first = json.loads(
        lines[0]
    )
    second = json.loads(
        lines[1]
    )

    assert first["sequence"] == 1
    assert second["sequence"] == 2


def test_journal_accepts_future_domain_event(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )
    journal = RunEventJournal(
        session
    )

    event = {
        "apiVersion": (
            "example.custom-event/v1"
        ),
        "kind": "CustomEvent",
        "event": "measurement-ready",
        "value": 42,
    }

    record = journal.append(
        event,
        recorded_at=RECORDED,
    )

    assert (
        record["event"]
        == event
    )


def test_journal_rejects_unversioned_event(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )
    journal = RunEventJournal(
        session
    )

    with pytest.raises(
        ValueError,
        match="apiVersion",
    ):
        journal.append(
            {
                "kind": "UnknownEvent",
            },
            recorded_at=RECORDED,
        )

    assert not journal.path.exists()


def test_journal_detects_incomplete_final_record(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    path = (
        session.directory
        / "events.jsonl"
    )

    path.write_bytes(
        b'{"incomplete":true}'
    )

    with pytest.raises(
        RunEventJournalCorruptionError,
        match="incomplete",
    ):
        RunEventJournal(
            session
        )


def test_journal_detects_sequence_corruption(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    path = (
        session.directory
        / "events.jsonl"
    )

    record = {
        "apiVersion": (
            RUN_EVENT_RECORD_API_VERSION
        ),
        "kind": (
            RUN_EVENT_RECORD_KIND
        ),
        "runId": session.run_id,
        "sequence": 2,
        "recordedAt": (
            "2026-08-19T05:30:01.000000Z"
        ),
        "event": {
            "apiVersion": (
                "example.event/v1"
            ),
            "kind": "ExampleEvent",
        },
    }

    path.write_text(
        json.dumps(record)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunEventJournalCorruptionError,
        match="sequence",
    ):
        RunEventJournal(
            session
        )


def test_system_startup_event_keeps_public_execution_event_contract() -> None:
    from nodrix.system.execution_events import (
        ExecutionEventKind,
        execution_event_from_startup_event,
    )
    from nodrix.system.orchestration import (
        SystemStartupEvent,
        SystemStartupEventKind,
    )

    startup = SystemStartupEvent(
        event=(
            SystemStartupEventKind.CHILD_STARTED
        ),
        execution_id="system-parent-001",
        system="robot",
        child="lidar",
        child_execution_id=(
            "system-child-001"
        ),
    )

    event = execution_event_from_startup_event(
        startup,
        timestamp=RECORDED,
    )

    document = event.to_dict()

    assert (
        event.event
        is ExecutionEventKind.CHILD_STARTED
    )
    assert (
        document["apiVersion"]
        == "nodrix.execution.event/v1"
    )
    assert (
        document["kind"]
        == "ExecutionEvent"
    )
    assert (
        document["executionId"]
        == "system-parent-001"
    )

    assert (
        document["details"]["child"]
        == "lidar"
    )
    assert (
        document["details"][
            "childExecutionId"
        ]
        == "system-child-001"
    )
