from __future__ import annotations

import json
from pathlib import Path

from nodrix.run_recovery import (
    ACTIVE_OR_UNKNOWN,
    CORRUPTED,
    FAILED_BEFORE_START,
    HEALTHY_TERMINAL,
    INCOMPLETE,
    INTERRUPTED,
    inspect_run_directory,
)


RUN_ID = "run_recovery_demo"
PLAN_ID = "plan-" + ("a" * 64)
REVISION = (
    "nodrix://system/project/demo"
    "?revision=sha256:"
    + ("b" * 64)
)

STAMP = (
    "2026-08-19T07:30:00.000000Z"
)


def _write_json(
    path: Path,
    value,
) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _base_run(
    tmp_path,
) -> Path:
    directory = (
        tmp_path
        / RUN_ID
    )

    directory.mkdir(
        parents=True
    )

    _write_json(
        directory
        / "session.json",
        {
            "schema": (
                "nodrix.run-session/v1"
            ),
            "layout": (
                "nodrix.run-layout/v1"
            ),
            "run_id": RUN_ID,
            "created_at": STAMP,
            "plan": {
                "id": PLAN_ID,
                "kind": (
                    "system-execution"
                ),
            },
            "operation": {
                "kind": "run",
                "subject": (
                    "nodrix://system/project/demo"
                ),
                "subject_revision": (
                    REVISION
                ),
            },
            "documentation": (
                "README.md"
            ),
        },
    )

    _write_json(
        directory
        / "definition.json",
        {
            "apiVersion": (
                "nodrix.run-snapshot/v1"
            ),
            "kind": "RunSnapshot",
            "snapshotKind": (
                "definition"
            ),
            "runId": RUN_ID,
            "planId": PLAN_ID,
            "content": {
                "revision": (
                    REVISION
                ),
            },
        },
    )

    _write_json(
        directory
        / "plan.json",
        {
            "apiVersion": (
                "nodrix.run-snapshot/v1"
            ),
            "kind": "RunSnapshot",
            "snapshotKind": "plan",
            "runId": RUN_ID,
            "planId": PLAN_ID,
            "content": {
                "planId": PLAN_ID,
                "subjectRevision": (
                    REVISION
                ),
            },
        },
    )

    _write_json(
        directory
        / "environment.json",
        {
            "apiVersion": (
                "nodrix.run-environment/v1"
            ),
            "kind": (
                "RunEnvironment"
            ),
            "runId": RUN_ID,
            "planId": PLAN_ID,
            "capturedAt": STAMP,
            "runtime": {},
            "variables": {},
            "extra": {},
            "policy": {
                "variables": [],
            },
        },
    )

    return directory


def _write_events(
    directory: Path,
    *,
    sequences=(0, 1),
) -> None:
    path = (
        directory
        / "events.jsonl"
    )

    records = []

    for index, sequence in enumerate(
        sequences
    ):
        state = (
            "prepared"
            if index == 0
            else "running"
        )

        event_name = (
            "prepared"
            if state == "prepared"
            else "started"
        )

        records.append(
            {
                "apiVersion": (
                    "nodrix.run-event-record/v1"
                ),
                "kind": (
                    "RunEventRecord"
                ),
                "runId": RUN_ID,
                "sequence": sequence,
                "recordedAt": STAMP,
                "event": {
                    "apiVersion": (
                        "nodrix.execution.event/v1"
                    ),
                    "kind": (
                        "ExecutionEvent"
                    ),
                    "event": (
                        event_name
                    ),
                    "timestamp": STAMP,
                    "system": "demo",
                    "executionId": (
                        None
                        if state == "prepared"
                        else "exec-1"
                    ),
                    "message": None,
                    "details": {},
                    "status": None,
                },
            }
        )

    path.write_text(
        "".join(
            json.dumps(
                record
            )
            + "\n"
            for record
            in records
        ),
        encoding="utf-8",
    )


def _write_status(
    directory: Path,
    *,
    state: str,
    execution_id: str | None,
) -> None:
    _write_json(
        directory
        / "status.json",
        {
            "apiVersion": (
                "nodrix.run-status/v1"
            ),
            "kind": "RunStatus",
            "runId": RUN_ID,
            "planId": PLAN_ID,
            "generation": 1,
            "updatedAt": STAMP,
            "state": state,
            "executionId": (
                execution_id
            ),
            "message": None,
            "details": {},
        },
    )


def _write_final(
    directory: Path,
    *,
    state: str = "completed",
    execution_id: str = "exec-1",
) -> None:
    _write_json(
        directory
        / "run.json",
        {
            "apiVersion": (
                "nodrix.run-record/v1"
            ),
            "kind": "RunRecord",
            "runId": RUN_ID,
            "execution": {
                "executionId": (
                    execution_id
                ),
                "state": state,
                "terminal": True,
                "successful": (
                    state
                    in {
                        "completed",
                        "stopped",
                    }
                ),
                "startedAt": STAMP,
                "finishedAt": STAMP,
                "plan": {
                    "planId": (
                        PLAN_ID
                    ),
                },
                "details": {},
            },
            "summary": {},
            "metadata": {},
        },
    )


def test_complete_terminal_run_is_healthy(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="completed",
        execution_id="exec-1",
    )

    _write_final(
        directory
    )

    report = (
        inspect_run_directory(
            directory
        )
    )

    assert (
        report.classification
        == HEALTHY_TERMINAL
    )

    assert (
        report.recovered_state
        == "completed"
    )

    assert report.terminal
    assert not report.corrupted
    assert report.event_count == 2


def test_nonterminal_run_is_not_guessed_stale(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="running",
        execution_id="exec-1",
    )

    report = (
        inspect_run_directory(
            directory
        )
    )

    assert (
        report.classification
        == ACTIVE_OR_UNKNOWN
    )


def test_recovery_owner_can_mark_nonterminal_run_interrupted(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="running",
        execution_id="exec-1",
    )

    report = (
        inspect_run_directory(
            directory,
            assume_inactive=True,
        )
    )

    assert (
        report.classification
        == INTERRUPTED
    )

    assert (
        report.recovered_state
        == "running"
    )


def test_failed_before_execution_does_not_require_run_json(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="failed",
        execution_id=None,
    )

    report = (
        inspect_run_directory(
            directory
        )
    )

    assert (
        report.classification
        == FAILED_BEFORE_START
    )

    assert not (
        report.final_record_present
    )


def test_terminal_execution_without_run_json_is_incomplete(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="failed",
        execution_id="exec-1",
    )

    report = (
        inspect_run_directory(
            directory
        )
    )

    assert (
        report.classification
        == INCOMPLETE
    )

    assert any(
        issue.code == "REC106"
        for issue in report.issues
    )


def test_event_sequence_gap_is_corruption(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory,
        sequences=(0, 2),
    )

    _write_status(
        directory,
        state="running",
        execution_id="exec-1",
    )

    report = (
        inspect_run_directory(
            directory
        )
    )

    assert (
        report.classification
        == CORRUPTED
    )

    assert any(
        issue.code == "REC305"
        for issue in report.issues
    )


def test_definition_revision_must_match_plan(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    plan_path = (
        directory
        / "plan.json"
    )

    plan = json.loads(
        plan_path.read_text(
            encoding="utf-8"
        )
    )

    plan["content"][
        "subjectRevision"
    ] = "different-revision"

    _write_json(
        plan_path,
        plan,
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="running",
        execution_id="exec-1",
    )

    report = (
        inspect_run_directory(
            directory
        )
    )

    assert (
        report.classification
        == CORRUPTED
    )

    assert any(
        issue.code == "REC403"
        for issue in report.issues
    )


def test_nonfinite_json_is_corruption(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory
    )

    (
        directory
        / "status.json"
    ).write_text(
        (
            "{"
            f'"runId":"{RUN_ID}",'
            f'"planId":"{PLAN_ID}",'
            '"state":"running",'
            '"updatedAt":NaN'
            "}\n"
        ),
        encoding="utf-8",
    )

    report = (
        inspect_run_directory(
            directory
        )
    )

    assert (
        report.classification
        == CORRUPTED
    )

    assert any(
        issue.code == "REC202"
        for issue in report.issues
    )


def test_stale_temporary_file_is_reported_without_corrupting_run(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="completed",
        execution_id="exec-1",
    )

    _write_final(
        directory
    )

    (
        directory
        / ".plan.dead.tmp"
    ).write_text(
        "leftover",
        encoding="utf-8",
    )

    report = (
        inspect_run_directory(
            directory
        )
    )

    assert (
        report.classification
        == HEALTHY_TERMINAL
    )

    assert (
        report.temporary_files
        == (
            ".plan.dead.tmp",
        )
    )

    assert any(
        issue.code == "REC701"
        for issue in report.issues
    )


def test_final_run_reversed_execution_interval_is_corruption(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="completed",
        execution_id="exec-1",
    )

    _write_final(
        directory
    )

    path = (
        directory
        / "run.json"
    )

    document = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    document["execution"][
        "startedAt"
    ] = (
        "2026-08-19T07:31:00Z"
    )

    document["execution"][
        "finishedAt"
    ] = (
        "2026-08-19T07:30:00Z"
    )

    _write_json(
        path,
        document,
    )

    report = (
        inspect_run_directory(
            directory
        )
    )

    assert (
        report.classification
        == CORRUPTED
    )

    assert any(
        issue.code == "REC610"
        for issue in report.issues
    )



def _upgrade_to_v2(
    directory: Path,
    *,
    with_policy: bool = True,
) -> None:
    session_path = (
        directory
        / "session.json"
    )

    session = json.loads(
        session_path.read_text(
            encoding="utf-8"
        )
    )

    session[
        "layout"
    ] = "nodrix.run-layout/v2"

    _write_json(
        session_path,
        session,
    )

    if not with_policy:
        return

    _write_json(
        directory
        / "policy.json",
        {
            "apiVersion": (
                "nodrix.execution-policy/v1"
            ),
            "kind": (
                "ExecutionPolicy"
            ),
            "runId": RUN_ID,
            "planId": PLAN_ID,
            "environment": {
                "variables": [],
                "redaction": {
                    "sensitiveKeyTokens": [],
                    "marker": "[REDACTED]",
                    "secretValues": {
                        "configured": False,
                        "count": 0,
                        "persisted": False,
                    },
                },
            },
            "logs": {
                "enabled": False,
                "minLevel": "warning",
                "categories": [],
                "maxBytes": 4194304,
                "maxCategoryBytes": 1048576,
                "maxRecordBytes": 65536,
                "overflow": "drop",
                "redaction": {
                    "sensitiveKeyTokens": [],
                    "marker": "[REDACTED]",
                    "secretValues": {
                        "configured": False,
                        "count": 0,
                        "persisted": False,
                    },
                },
            },
        },
    )


def test_legacy_v1_run_remains_recoverable_without_policy(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="completed",
        execution_id="exec-1",
    )

    _write_final(
        directory
    )

    assert not (
        directory
        / "policy.json"
    ).exists()

    report = inspect_run_directory(
        directory
    )

    assert (
        report.classification
        == HEALTHY_TERMINAL
    )

    assert not any(
        issue.code == "REC107"
        for issue in report.issues
    )


def test_v2_run_with_valid_policy_is_healthy(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _upgrade_to_v2(
        directory
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="completed",
        execution_id="exec-1",
    )

    _write_final(
        directory
    )

    report = inspect_run_directory(
        directory
    )

    assert (
        report.classification
        == HEALTHY_TERMINAL
    )

    assert not report.corrupted


def test_v2_run_without_policy_is_incomplete(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _upgrade_to_v2(
        directory,
        with_policy=False,
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="completed",
        execution_id="exec-1",
    )

    _write_final(
        directory
    )

    report = inspect_run_directory(
        directory
    )

    assert (
        report.classification
        == INCOMPLETE
    )

    assert any(
        issue.code == "REC107"
        and issue.path == "policy.json"
        for issue in report.issues
    )


def test_v2_run_with_mismatched_policy_identity_is_corrupted(
    tmp_path,
) -> None:
    directory = _base_run(
        tmp_path
    )

    _upgrade_to_v2(
        directory
    )

    policy_path = (
        directory
        / "policy.json"
    )

    policy = json.loads(
        policy_path.read_text(
            encoding="utf-8"
        )
    )

    policy[
        "runId"
    ] = "run_other"

    _write_json(
        policy_path,
        policy,
    )

    _write_events(
        directory
    )

    _write_status(
        directory,
        state="running",
        execution_id="exec-1",
    )

    report = inspect_run_directory(
        directory
    )

    assert (
        report.classification
        == CORRUPTED
    )

    assert any(
        issue.code == "REC410"
        and issue.path == "policy.json"
        for issue in report.issues
    )
