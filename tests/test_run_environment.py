from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import json

import pytest

from nodrix.redaction import (
    DEFAULT_REDACTION_MARKER,
    RedactionPolicy,
)
from nodrix.run_environment import (
    RUN_ENVIRONMENT_API_VERSION,
    RUN_ENVIRONMENT_KIND,
    RunEnvironmentCorruptionError,
    RunEnvironmentPolicy,
    RunEnvironmentStore,
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


CAPTURED = datetime(
    2026,
    8,
    19,
    6,
    30,
    0,
    tzinfo=timezone.utc,
)


def _session(
    tmp_path,
):
    plan = plan_canonical_system(
        SystemModel(
            name="environment-demo"
        )
    )

    return RunStore(
        tmp_path / "runs"
    ).create(
        plan,
        run_id="run_environment_demo",
    )


def test_default_policy_does_not_capture_process_variables(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunEnvironmentStore(
        session
    )

    document = store.capture(
        environ={
            "PATH": "/secret/user/path",
            "API_TOKEN": "very-secret-token",
        },
        captured_at=CAPTURED,
    )

    assert (
        document["apiVersion"]
        == RUN_ENVIRONMENT_API_VERSION
    )

    assert (
        document["kind"]
        == RUN_ENVIRONMENT_KIND
    )

    assert (
        document["variables"]
        == {}
    )

    assert (
        document["policy"]["variables"]
        == []
    )


def test_allowlisted_variables_are_captured_with_redaction(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    policy = RunEnvironmentPolicy(
        variables=(
            "PATH",
            "API_TOKEN",
            "MISSING_VALUE",
        ),
    )

    store = RunEnvironmentStore(
        session,
        policy=policy,
    )

    document = store.capture(
        environ={
            "PATH": "/opt/nodrix/bin",
            "API_TOKEN": "abc123",
            "OTHER_SECRET": "must-not-appear",
        },
        captured_at=CAPTURED,
    )

    assert (
        document["variables"]["PATH"]
        == "/opt/nodrix/bin"
    )

    assert (
        document["variables"]["API_TOKEN"]
        == DEFAULT_REDACTION_MARKER
    )

    assert (
        document["variables"]["MISSING_VALUE"]
        is None
    )

    encoded = json.dumps(
        document
    )

    assert (
        "must-not-appear"
        not in encoded
    )

    assert (
        "abc123"
        not in encoded
    )


def test_extra_environment_metadata_is_redacted(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    policy = RunEnvironmentPolicy(
        redaction=RedactionPolicy(
            secrets=(
                "literal-secret",
            )
        )
    )

    store = RunEnvironmentStore(
        session,
        policy=policy,
    )

    document = store.capture(
        environ={},
        captured_at=CAPTURED,
        extra={
            "backend": "local",
            "credentials": {
                "password": "password-value",
            },
            "message": (
                "failed literal-secret"
            ),
        },
    )

    assert (
        document["extra"]["backend"]
        == "local"
    )

    assert (
        document["extra"]["credentials"]
        == DEFAULT_REDACTION_MARKER
    )

    assert (
        document["extra"]["message"]
        == (
            "failed "
            + DEFAULT_REDACTION_MARKER
        )
    )


def test_environment_snapshot_is_immutable(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunEnvironmentStore(
        session
    )

    store.capture(
        environ={},
        captured_at=CAPTURED,
    )

    first = (
        store.path.read_bytes()
    )

    with pytest.raises(
        FileExistsError,
    ):
        store.capture(
            environ={},
            captured_at=CAPTURED,
        )

    assert (
        store.path.read_bytes()
        == first
    )


def test_failed_publication_leaves_no_partial_environment(
    tmp_path,
    monkeypatch,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunEnvironmentStore(
        session
    )

    import nodrix.run_environment as run_environment

    def fail_link(
        source,
        destination,
    ) -> None:
        raise OSError(
            "synthetic environment failure"
        )

    monkeypatch.setattr(
        run_environment.os,
        "link",
        fail_link,
    )

    with pytest.raises(
        OSError,
        match="synthetic environment failure",
    ):
        store.capture(
            environ={},
            captured_at=CAPTURED,
        )

    assert not (
        store.path.exists()
    )

    assert not list(
        session.directory.glob(
            ".environment.*.tmp"
        )
    )


def test_reader_detects_nonfinite_corruption(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    path = (
        session.directory
        / "environment.json"
    )

    path.write_text(
        (
            "{"
            '"apiVersion":"nodrix.run-environment/v1",'
            '"kind":"RunEnvironment",'
            f'"runId":"{session.run_id}",'
            f'"planId":"{session.plan_id}",'
            '"capturedAt":"2026-08-19T06:30:00Z",'
            '"runtime":{},'
            '"variables":{},'
            '"extra":{"temperature":NaN},'
            '"policy":{"variables":[]}'
            "}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        RunEnvironmentCorruptionError,
        match="invalid JSON",
    ):
        RunEnvironmentStore(
            session
        ).read()
