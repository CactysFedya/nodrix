from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import json

import pytest

from nodrix.model import (
    ExecutionState,
)
from nodrix.run_status import (
    RUN_STATUS_API_VERSION,
    RUN_STATUS_KIND,
    RunStatusCorruptionError,
    RunStatusStore,
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


CREATED = datetime(
    2026,
    8,
    19,
    6,
    0,
    0,
    tzinfo=timezone.utc,
)

UPDATED = datetime(
    2026,
    8,
    19,
    6,
    0,
    1,
    tzinfo=timezone.utc,
)


def _clock() -> datetime:
    return CREATED


def _session(tmp_path):
    plan = plan_canonical_system(
        SystemModel(
            name="status-demo"
        )
    )

    return RunStore(
        tmp_path / "runs",
        clock=_clock,
    ).create(
        plan,
        run_id="run_status_demo",
    )


def test_status_file_is_created_only_on_first_write(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )
    store = RunStatusStore(
        session
    )

    assert not store.path.exists()
    assert store.next_generation == 1
    assert store.read() is None

    document = store.write(
        state=ExecutionState.CREATED,
        updated_at=UPDATED,
    )

    assert store.path.is_file()

    assert (
        document["apiVersion"]
        == RUN_STATUS_API_VERSION
    )
    assert (
        document["kind"]
        == RUN_STATUS_KIND
    )
    assert (
        document["runId"]
        == session.run_id
    )
    assert (
        document["planId"]
        == session.plan_id
    )

    assert document[
        "generation"
    ] == 1

    assert document[
        "state"
    ] == "created"

    assert document[
        "executionId"
    ] is None

    assert (
        document["terminal"]
        is False
    )

    assert (
        document["successful"]
        is False
    )


def test_status_generation_survives_reopen(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    first = RunStatusStore(
        session
    )

    first.write(
        state="created",
        updated_at=UPDATED,
    )

    second = RunStatusStore(
        session
    )

    assert (
        second.next_generation
        == 2
    )

    document = second.write(
        state="running",
        execution_id=(
            "system-execution-001"
        ),
        updated_at=UPDATED,
    )

    assert (
        document["generation"]
        == 2
    )

    assert (
        second.next_generation
        == 3
    )


def test_status_atomic_replace_keeps_previous_snapshot_on_failure(
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunStatusStore(
        session
    )

    first = store.write(
        state="created",
        updated_at=UPDATED,
    )

    import nodrix.run_status as run_status

    def fail_replace(
        source,
        destination,
    ) -> None:
        raise OSError(
            "synthetic replace failure"
        )

    monkeypatch.setattr(
        run_status.os,
        "replace",
        fail_replace,
    )

    with pytest.raises(
        OSError,
        match="synthetic replace failure",
    ):
        store.write(
            state="running",
            execution_id=(
                "system-execution-001"
            ),
            updated_at=UPDATED,
        )

    persisted = json.loads(
        store.path.read_text(
            encoding="utf-8"
        )
    )

    assert persisted == first

    # Failed replacement must not advance the visible generation.
    assert (
        store.next_generation
        == 2
    )

    assert not list(
        session.directory.glob(
            ".status.*.tmp"
        )
    )


def test_failed_status_may_exist_before_execution_id(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunStatusStore(
        session
    )

    document = store.write(
        state="failed",
        message="prepare failed",
        details={
            "stage": "prepare",
        },
        updated_at=UPDATED,
    )

    assert (
        document["executionId"]
        is None
    )
    assert (
        document["state"]
        == "failed"
    )
    assert document[
        "terminal"
    ]
    assert not document[
        "successful"
    ]


def test_status_rejects_non_finite_details_before_write(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunStatusStore(
        session
    )

    with pytest.raises(
        ValueError,
        match="non-finite",
    ):
        store.write(
            state="running",
            execution_id="exec-1",
            details={
                "temperature": (
                    float("nan")
                ),
            },
            updated_at=UPDATED,
        )

    assert not (
        store.path.exists()
    )


def test_status_detects_corrupted_existing_document(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    path = (
        session.directory
        / "status.json"
    )

    path.write_text(
        json.dumps(
            {
                "apiVersion": (
                    RUN_STATUS_API_VERSION
                ),
                "kind": (
                    RUN_STATUS_KIND
                ),
                "runId": (
                    session.run_id
                ),
                "planId": (
                    session.plan_id
                ),
                "generation": 4,
                "updatedAt": (
                    "2026-08-19T06:00:01Z"
                ),
                "executionId": (
                    "exec-1"
                ),
                "state": "running",
                # Deliberately inconsistent with state.
                "terminal": True,
                "successful": False,
                "message": None,
                "details": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunStatusCorruptionError,
        match="terminal flag",
    ):
        RunStatusStore(
            session
        )


def test_unchanged_status_does_not_advance_generation(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunStatusStore(
        session
    )

    first = store.write_if_changed(
        state="running",
        execution_id="exec-1",
        details={
            "health": "healthy",
        },
        updated_at=UPDATED,
    )

    later = UPDATED.replace(
        second=2
    )

    second = store.write_if_changed(
        state="running",
        execution_id="exec-1",
        details={
            "health": "healthy",
        },
        updated_at=later,
    )

    assert (
        first["generation"]
        == 1
    )
    assert (
        second["generation"]
        == 1
    )

    # updatedAt marks the actual persisted status change, not a read/poll.
    assert (
        second["updatedAt"]
        == first["updatedAt"]
    )

    assert (
        store.next_generation
        == 2
    )

    changed = store.write_if_changed(
        state="running",
        execution_id="exec-1",
        details={
            "health": "unhealthy",
        },
        updated_at=later,
    )

    assert (
        changed["generation"]
        == 2
    )


@pytest.mark.parametrize(
    "constant",
    (
        "NaN",
        "Infinity",
        "-Infinity",
    ),
)
def test_status_reader_rejects_nonstandard_json_numbers(
    tmp_path,
    constant: str,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunStatusStore(
        session
    )

    store.write(
        state="running",
        execution_id="exec-1",
        updated_at=UPDATED,
    )

    text = store.path.read_text(
        encoding="utf-8"
    )

    old = '"details": {}'

    assert old in text

    store.path.write_text(
        text.replace(
            old,
            (
                '"details": '
                '{"invalid": '
                + constant
                + "}"
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        RunStatusCorruptionError,
        match="invalid JSON",
    ):
        RunStatusStore(
            session
        )


def test_status_reader_requires_timezone_aware_updated_at(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunStatusStore(
        session
    )

    store.write(
        state="running",
        execution_id="exec-1",
        updated_at=UPDATED,
    )

    document = json.loads(
        store.path.read_text(
            encoding="utf-8"
        )
    )

    document["updatedAt"] = (
        "2026-08-19T06:00:01"
    )

    store.path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunStatusCorruptionError,
        match="timezone-aware",
    ):
        RunStatusStore(
            session
        )
