from __future__ import annotations

import json

import pytest

from nodrix.model import (
    EntityRef,
    Operation,
    PlanRecord,
    RevisionRef,
)
from nodrix.run_session import (
    RUN_LAYOUT_SCHEMA,
    RUN_SESSION_SCHEMA,
    RunSessionCorruptionError,
    RunStore,
    load_run_session,
)


def _plan() -> PlanRecord:
    system = EntityRef(
        kind="system",
        namespace="project",
        name="session-loader",
    )

    return PlanRecord(
        plan_id="plan-session-loader",
        kind="system-execution",
        operation=Operation(
            kind="run",
            subject=system,
        ),
        subject_revision=(
            RevisionRef.from_sha256(
                system,
                "a" * 64,
            )
        ),
        payload={
            "target": "local",
        },
    )


def _created_session(
    tmp_path,
    *,
    run_id="run_session_loader",
):
    store = RunStore(
        tmp_path
        / "runs"
    )

    session = store.create(
        _plan(),
        run_id=run_id,
    )

    return store, session


def _document(
    session,
):
    return json.loads(
        session.session_path.read_text(
            encoding="utf-8"
        )
    )


def _write_document(
    session,
    document,
) -> None:
    session.session_path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_run_session_reopens_exact_persisted_header(
    tmp_path,
) -> None:
    _, created = _created_session(
        tmp_path
    )

    loaded = load_run_session(
        created.directory
    )

    assert loaded == created
    assert loaded.run_id == created.run_id
    assert loaded.plan_id == created.plan_id
    assert loaded.subject == created.subject
    assert (
        loaded.subject_revision
        == created.subject_revision
    )


def test_run_store_open_reuses_canonical_loader(
    tmp_path,
) -> None:
    store, created = _created_session(
        tmp_path
    )

    loaded = store.open(
        created.run_id
    )

    assert loaded == created


def test_load_run_session_rejects_unsupported_schema(
    tmp_path,
) -> None:
    _, session = _created_session(
        tmp_path
    )

    document = _document(
        session
    )

    document["schema"] = (
        "nodrix.run-session/v999"
    )

    _write_document(
        session,
        document,
    )

    with pytest.raises(
        RunSessionCorruptionError,
        match="schema is unsupported",
    ):
        load_run_session(
            session.directory
        )


def test_load_run_session_rejects_unsupported_layout(
    tmp_path,
) -> None:
    _, session = _created_session(
        tmp_path
    )

    document = _document(
        session
    )

    assert (
        document["schema"]
        == RUN_SESSION_SCHEMA
    )

    assert (
        document["layout"]
        == RUN_LAYOUT_SCHEMA
    )

    document["layout"] = (
        "nodrix.run-layout/v999"
    )

    _write_document(
        session,
        document,
    )

    with pytest.raises(
        RunSessionCorruptionError,
        match="layout is unsupported",
    ):
        load_run_session(
            session.directory
        )


def test_load_run_session_rejects_invalid_timestamp(
    tmp_path,
) -> None:
    _, session = _created_session(
        tmp_path
    )

    document = _document(
        session
    )

    document["created_at"] = (
        "2026-08-19T12:00:00"
    )

    _write_document(
        session,
        document,
    )

    with pytest.raises(
        RunSessionCorruptionError,
        match="timezone-aware",
    ):
        load_run_session(
            session.directory
        )


def test_load_run_session_rejects_unexpected_fields(
    tmp_path,
) -> None:
    _, session = _created_session(
        tmp_path
    )

    document = _document(
        session
    )

    document["hidden"] = True

    _write_document(
        session,
        document,
    )

    with pytest.raises(
        RunSessionCorruptionError,
        match="invalid fields",
    ):
        load_run_session(
            session.directory
        )


def test_load_run_session_rejects_directory_identity_mismatch(
    tmp_path,
) -> None:
    _, session = _created_session(
        tmp_path,
        run_id="run_original",
    )

    renamed = (
        session.directory.parent
        / "run_renamed"
    )

    session.directory.rename(
        renamed
    )

    with pytest.raises(
        RunSessionCorruptionError,
        match="directory name does not match",
    ):
        load_run_session(
            renamed
        )


def test_load_run_session_rejects_nonfinite_json(
    tmp_path,
) -> None:
    _, session = _created_session(
        tmp_path
    )

    text = (
        session.session_path
        .read_text(
            encoding="utf-8"
        )
    )

    text = text.replace(
        '"documentation": "README.md"',
        (
            '"documentation": "README.md", '
            '"bad": NaN'
        ),
    )

    session.session_path.write_text(
        text,
        encoding="utf-8",
    )

    with pytest.raises(
        RunSessionCorruptionError,
        match="invalid JSON",
    ):
        load_run_session(
            session.directory
        )


def test_load_run_session_preserves_historical_v1_layout(
    tmp_path,
) -> None:
    _, session = _created_session(
        tmp_path
    )

    document = _document(
        session
    )

    document["layout"] = (
        "nodrix.run-layout/v1"
    )

    _write_document(
        session,
        document,
    )

    loaded = load_run_session(
        session.directory
    )

    assert (
        loaded.layout
        == "nodrix.run-layout/v1"
    )

    assert (
        loaded.document()["layout"]
        == "nodrix.run-layout/v1"
    )
