from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from nodrix.system import (
    BackendExecutionState,
    BackendExecutionStatus,
    ChildSystemExecutionStatus,
    EXECUTION_EVENT_API_VERSION,
    EXECUTION_EVENT_KIND,
    ExecutionEvent,
    ExecutionEventKind,
    ExecutionHealthState,
    ExecutionObservation,
    ExecutionScope,
    Graph,
    NodeInstance,
    ScopeExecutionStatus,
    SystemExecutionStatus,
    SystemInstance,
    SystemModel,
    dumps_execution_event,
    plan_system,
)
from nodrix.system.definition import (
    system_definition_record,
)


def _hierarchical_status(
    tmp_path: Path,
    *,
    state: BackendExecutionState = (
        BackendExecutionState.RUNNING
    ),
) -> SystemExecutionStatus:
    child_definition = SystemModel(
        name="livox-mid360",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="driver",
                        uses="demo.driver",
                    ),
                ),
            ),
        ),
    )
    revision = system_definition_record(
        child_definition
    ).revision

    parent_definition = SystemModel(
        name="rpi5-mapping",
        systems=(
            SystemInstance(
                name="lidar",
                uses=revision.canonical,
            ),
        ),
    )
    plan = plan_system(
        parent_definition,
        system_resolver=(
            lambda requested: (
                child_definition
                if requested == revision
                else None
            )
        ),
    )

    observation = ExecutionObservation(
        ready=(
            False
            if state
            in {
                BackendExecutionState.COMPLETED,
                BackendExecutionState.STOPPED,
                BackendExecutionState.FAILED,
            }
            else True
        ),
        health=ExecutionHealthState.DEGRADED,
        message="camera latency is elevated",
    )
    backend_status = BackendExecutionStatus(
        backend="local",
        execution_id="local-001",
        state=state,
        details={
            "run_path": (
                tmp_path / "runs" / "local-001"
            ),
            "labels": (
                "mapping",
                "lidar",
            ),
        },
        observation=observation,
    )
    child_status = SystemExecutionStatus(
        execution_id="system-child",
        state=state,
        scopes=(
            ScopeExecutionStatus(
                scope=ExecutionScope(
                    "pi5",
                    "local",
                ),
                status=backend_status,
            ),
        ),
        observation=observation,
    )

    return SystemExecutionStatus(
        execution_id="system-root",
        state=state,
        systems=(
            ChildSystemExecutionStatus(
                instance=plan.child("lidar"),
                status=child_status,
            ),
        ),
        observation=observation,
    )


def test_execution_event_serializes_hierarchical_snapshot(
    tmp_path: Path,
) -> None:
    status = _hierarchical_status(
        tmp_path
    )
    event = ExecutionEvent(
        event=ExecutionEventKind.SNAPSHOT,
        system="rpi5-mapping",
        timestamp=datetime(
            2026,
            8,
            18,
            9,
            30,
            tzinfo=timezone.utc,
        ),
        status=status,
        details={
            "sequence": 2,
        },
    )

    payload = event.to_dict()

    assert payload["apiVersion"] == (
        EXECUTION_EVENT_API_VERSION
    )
    assert payload["kind"] == (
        EXECUTION_EVENT_KIND
    )
    assert payload["event"] == "snapshot"
    assert payload["timestamp"] == (
        "2026-08-18T09:30:00Z"
    )
    assert payload["executionId"] == (
        "system-root"
    )

    child = payload["status"]["systems"][0]
    instance = child["instance"]

    assert instance["name"] == "lidar"
    assert instance["definition"] == (
        "livox-mid360"
    )
    assert instance["ordinal"] == 0
    assert isinstance(
        instance["revision"],
        str,
    )
    assert instance["revision"]

    scope = child["status"]["scopes"][0]
    assert scope["scope"] == {
        "id": "pi5:local",
        "target": "pi5",
        "backend": "local",
    }
    assert scope["status"]["observation"] == {
        "ready": True,
        "health": "degraded",
        "message": "camera latency is elevated",
    }
    assert scope["status"]["details"] == {
        "run_path": str(
            tmp_path
            / "runs"
            / "local-001"
        ),
        "labels": [
            "mapping",
            "lidar",
        ],
    }


def test_execution_event_dump_is_one_json_line(
    tmp_path: Path,
) -> None:
    event = ExecutionEvent(
        event=ExecutionEventKind.SNAPSHOT,
        system="rpi5-mapping",
        status=_hierarchical_status(
            tmp_path
        ),
    )

    encoded = dumps_execution_event(
        event
    )

    assert "\n" not in encoded
    assert json.loads(encoded) == (
        event.to_dict()
    )


def test_finished_event_requires_terminal_status(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="terminal status",
    ):
        ExecutionEvent(
            event=ExecutionEventKind.FINISHED,
            system="rpi5-mapping",
            status=_hierarchical_status(
                tmp_path
            ),
        )


def test_finished_event_accepts_terminal_status(
    tmp_path: Path,
) -> None:
    event = ExecutionEvent(
        event=ExecutionEventKind.FINISHED,
        system="rpi5-mapping",
        status=_hierarchical_status(
            tmp_path,
            state=(
                BackendExecutionState.COMPLETED
            ),
        ),
    )

    assert event.to_dict()[
        "status"
    ]["terminal"] is True


def test_execution_event_rejects_naive_timestamp() -> None:
    with pytest.raises(
        ValueError,
        match="timezone",
    ):
        ExecutionEvent(
            event=ExecutionEventKind.PREPARED,
            system="rpi5-mapping",
            timestamp=datetime(
                2026,
                8,
                18,
                9,
                30,
            ),
        )


@pytest.mark.parametrize(
    "kind",
    [
        ExecutionEventKind.CHILD_STARTED,
        ExecutionEventKind.DEPENDENCY_WAITING,
        ExecutionEventKind.DEPENDENCY_SATISFIED,
        ExecutionEventKind.DEPENDENCY_FAILED,
    ],
)
def test_startup_execution_events_require_execution_id(
    kind: ExecutionEventKind,
) -> None:
    with pytest.raises(ValueError, match="execution_id"):
        ExecutionEvent(
            event=kind,
            system="rpi5-mapping",
        )

    event = ExecutionEvent(
        event=kind,
        system="rpi5-mapping",
        execution_id="system-001",
    )
    assert event.to_dict()["event"] == kind.value
