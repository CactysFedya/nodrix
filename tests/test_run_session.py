from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import json

import pytest

from nodrix.run_session import (
    RUN_LAYOUT_SCHEMA,
    RUN_SESSION_SCHEMA,
    RunStore,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.model import (
    SystemModel,
)


CREATED_AT = datetime(
    2026,
    8,
    19,
    5,
    9,
    12,
    tzinfo=timezone.utc,
)


def _clock() -> datetime:
    return CREATED_AT


def _plan():
    return plan_canonical_system(
        SystemModel(
            name="demo-system"
        )
    )


def test_run_store_creates_durable_session_before_execution(
    tmp_path,
) -> None:
    store = RunStore(
        tmp_path / ".nodrix" / "runs",
        clock=_clock,
        token_factory=(
            lambda: "a1b2c3d4e5f6"
        ),
    )

    session = store.create(
        _plan()
    )

    assert session.run_id == (
        "run_20260819T050912Z_"
        "a1b2c3d4e5f6"
    )

    assert session.directory.is_dir()
    assert session.logs_path.is_dir()
    assert session.session_path.is_file()
    assert session.readme_path.is_file()

    document = json.loads(
        session.session_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        document["schema"]
        == RUN_SESSION_SCHEMA
    )
    assert (
        document["layout"]
        == RUN_LAYOUT_SCHEMA
    )
    assert (
        document["run_id"]
        == session.run_id
    )
    assert (
        document["created_at"]
        == "2026-08-19T05:09:12.000000Z"
    )

    assert (
        document["plan"]["id"]
        == session.plan_id
    )
    assert (
        document["plan"]["kind"]
        == "system-execution"
    )

    assert (
        document["operation"]["kind"]
        == "run"
    )
    assert (
        document["operation"]["subject_revision"]
        == session.subject_revision
    )

    # Later lifecycle files are deliberately not fabricated yet.
    for name in (
        "definition.json",
        "plan.json",
        "policy.json",
        "status.json",
        "events.jsonl",
        "environment.json",
        "run.json",
    ):
        assert not (
            session.directory
            / name
        ).exists()

    # Canonical Metrics are optional and created lazily on first publish.
    assert not session.metrics_path.exists()


def test_run_readme_is_bilingual_and_self_describing(
    tmp_path,
) -> None:
    store = RunStore(
        tmp_path / "runs",
        clock=_clock,
        token_factory=(
            lambda: "001122334455"
        ),
    )

    session = store.create(
        _plan()
    )

    readme = (
        session.readme_path
        .read_text(
            encoding="utf-8"
        )
    )

    assert "## English" in readme
    assert "## Русский" in readme

    assert RUN_LAYOUT_SCHEMA in readme
    assert RUN_SESSION_SCHEMA in readme
    assert session.run_id in readme

    for name in (
        "README.md",
        "session.json",
        "definition.json",
        "plan.json",
        "policy.json",
        "status.json",
        "events.jsonl",
        "environment.json",
        "logs/",
        "metrics/records.jsonl",
        "metrics/status.json",
        "run.json",
    ):
        assert name in readme

    assert "append-only" in readme
    assert "только на добавление" in readme
    assert "immutable" in readme
    assert "неизменяем" in readme


def test_explicit_run_id_cannot_escape_store(
    tmp_path,
) -> None:
    store = RunStore(
        tmp_path / "runs",
        clock=_clock,
    )

    for invalid in (
        "../escape",
        "run_../escape",
        "/tmp/run_escape",
        "run_",
        "other_run",
    ):
        with pytest.raises(
            ValueError,
        ):
            store.create(
                _plan(),
                run_id=invalid,
            )

    assert not (
        tmp_path
        / "escape"
    ).exists()


def test_run_directory_is_never_silently_reused(
    tmp_path,
) -> None:
    store = RunStore(
        tmp_path / "runs",
        clock=_clock,
    )

    first = store.create(
        _plan(),
        run_id="run_fixed_001",
    )

    assert first.directory.exists()

    with pytest.raises(
        FileExistsError,
    ):
        store.create(
            _plan(),
            run_id="run_fixed_001",
        )


def test_same_timestamp_can_create_distinct_runs(
    tmp_path,
) -> None:
    tokens = iter(
        (
            "111111111111",
            "222222222222",
        )
    )

    store = RunStore(
        tmp_path / "runs",
        clock=_clock,
        token_factory=lambda: next(
            tokens
        ),
    )

    first = store.create(
        _plan()
    )
    second = store.create(
        _plan()
    )

    assert (
        first.run_id
        != second.run_id
    )
    assert (
        first.directory
        != second.directory
    )
