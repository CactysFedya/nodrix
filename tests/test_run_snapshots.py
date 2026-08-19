from __future__ import annotations

import json

import pytest

from nodrix.run_session import (
    RunStore,
)
from nodrix.run_snapshots import (
    DEFINITION_SNAPSHOT,
    PLAN_SNAPSHOT,
    RunSnapshotCorruptionError,
    RunSnapshotStore,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.model import (
    SystemModel,
)
from nodrix.system.run_snapshots import (
    SYSTEM_DEFINITION_SNAPSHOT_SCHEMA,
    SYSTEM_PLAN_SNAPSHOT_SCHEMA,
    system_definition_snapshot,
    system_plan_snapshot,
)


def _system(
    *,
    description: str = "snapshot demo",
) -> SystemModel:
    return SystemModel(
        name="snapshot-demo",
        description=description,
    )


def _run(
    tmp_path,
):
    system = _system()

    plan = (
        plan_canonical_system(
            system
        )
    )

    session = RunStore(
        tmp_path / "runs"
    ).create(
        plan,
        run_id="run_snapshot_demo",
    )

    return (
        system,
        plan,
        session,
    )


def test_definition_snapshot_matches_plan_revision(
    tmp_path,
) -> None:
    system, plan, _ = _run(
        tmp_path
    )

    snapshot = (
        system_definition_snapshot(
            system,
            plan,
        )
    )

    assert (
        snapshot["schema"]
        == SYSTEM_DEFINITION_SNAPSHOT_SCHEMA
    )

    assert (
        snapshot["recordType"]
        == "DefinitionRecord"
    )

    assert (
        snapshot["revision"]
        == plan.subject_revision.canonical
    )

    assert (
        snapshot["entity"]
        == plan.subject.canonical
    )

    assert (
        snapshot["definition"]["name"]
        == "snapshot-demo"
    )


def test_definition_snapshot_rejects_different_system_revision(
    tmp_path,
) -> None:
    _, plan, _ = _run(
        tmp_path
    )

    changed = _system(
        description="different revision"
    )

    with pytest.raises(
        ValueError,
        match="revision",
    ):
        system_definition_snapshot(
            changed,
            plan,
        )


def test_plan_snapshot_contains_exact_resolved_payload(
    tmp_path,
) -> None:
    _, plan, _ = _run(
        tmp_path
    )

    snapshot = (
        system_plan_snapshot(
            plan
        )
    )

    assert (
        snapshot["schema"]
        == SYSTEM_PLAN_SNAPSHOT_SCHEMA
    )

    assert (
        snapshot["recordType"]
        == "PlanRecord"
    )

    assert (
        snapshot["planId"]
        == plan.plan_id
    )

    assert (
        snapshot["subjectRevision"]
        == plan.subject_revision.canonical
    )

    assert snapshot[
        "payload"
    ] == plan.payload.model_dump(
        mode="json",
        by_alias=True,
    )

    assert (
        snapshot["payloadSha256"]
        == plan.metadata[
            "plan_sha256"
        ]
    )


def test_plan_snapshot_preserves_operation_parameters(
    tmp_path,
) -> None:
    _, plan, _ = _run(
        tmp_path
    )

    snapshot = (
        system_plan_snapshot(
            plan
        )
    )

    assert (
        snapshot["operation"]["kind"]
        == plan.operation.kind_name
    )

    assert (
        snapshot["operation"]["parameters"]
        == dict(
            plan.operation.parameters
        )
    )


def test_snapshot_store_publishes_definition_and_plan_once(
    tmp_path,
) -> None:
    system, plan, session = _run(
        tmp_path
    )

    store = RunSnapshotStore(
        session
    )

    assert (
        store.read(
            DEFINITION_SNAPSHOT
        )
        is None
    )

    assert (
        store.read(
            PLAN_SNAPSHOT
        )
        is None
    )

    definition = store.create(
        DEFINITION_SNAPSHOT,
        system_definition_snapshot(
            system,
            plan,
        ),
    )

    plan_document = store.create(
        PLAN_SNAPSHOT,
        system_plan_snapshot(
            plan
        ),
    )

    assert (
        definition["runId"]
        == session.run_id
    )

    assert (
        definition["planId"]
        == plan.plan_id
    )

    assert (
        plan_document["runId"]
        == session.run_id
    )

    assert (
        store.path(
            DEFINITION_SNAPSHOT
        ).is_file()
    )

    assert (
        store.path(
            PLAN_SNAPSHOT
        ).is_file()
    )


def test_snapshots_are_never_overwritten(
    tmp_path,
) -> None:
    system, plan, session = _run(
        tmp_path
    )

    store = RunSnapshotStore(
        session
    )

    content = (
        system_definition_snapshot(
            system,
            plan,
        )
    )

    store.create(
        DEFINITION_SNAPSHOT,
        content,
    )

    first = store.path(
        DEFINITION_SNAPSHOT
    ).read_bytes()

    with pytest.raises(
        FileExistsError,
    ):
        store.create(
            DEFINITION_SNAPSHOT,
            content,
        )

    assert (
        store.path(
            DEFINITION_SNAPSHOT
        ).read_bytes()
        == first
    )


def test_failed_publication_leaves_no_partial_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    system, plan, session = _run(
        tmp_path
    )

    store = RunSnapshotStore(
        session
    )

    import nodrix.run_snapshots as snapshots

    def fail_link(
        source,
        destination,
    ) -> None:
        raise OSError(
            "synthetic snapshot failure"
        )

    monkeypatch.setattr(
        snapshots.os,
        "link",
        fail_link,
    )

    with pytest.raises(
        OSError,
        match="synthetic snapshot failure",
    ):
        store.create(
            PLAN_SNAPSHOT,
            system_plan_snapshot(
                plan
            ),
        )

    assert not (
        store.path(
            PLAN_SNAPSHOT
        ).exists()
    )

    assert not list(
        session.directory.glob(
            ".plan.*.tmp"
        )
    )


def test_reader_detects_snapshot_for_different_run(
    tmp_path,
) -> None:
    system, plan, session = _run(
        tmp_path
    )

    store = RunSnapshotStore(
        session
    )

    store.create(
        DEFINITION_SNAPSHOT,
        system_definition_snapshot(
            system,
            plan,
        ),
    )

    path = store.path(
        DEFINITION_SNAPSHOT
    )

    document = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    document["runId"] = (
        "run_someone_else"
    )

    path.write_text(
        json.dumps(document)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunSnapshotCorruptionError,
        match="different Run",
    ):
        store.read(
            DEFINITION_SNAPSHOT
        )
