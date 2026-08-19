from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import json

from nodrix.redaction import (
    DEFAULT_REDACTION_MARKER,
    RedactionPolicy,
)
from nodrix.run_logs import (
    RunLogPolicy,
    RunLogStore,
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


RECORDED = datetime(
    2026,
    8,
    19,
    7,
    0,
    0,
    tzinfo=timezone.utc,
)


def _session(
    tmp_path,
):
    plan = plan_canonical_system(
        SystemModel(
            name="log-demo"
        )
    )

    return RunStore(
        tmp_path / "runs"
    ).create(
        plan,
        run_id="run_log_demo",
    )


def test_logging_is_disabled_by_default(
    tmp_path,
) -> None:
    store = RunLogStore(
        _session(
            tmp_path
        )
    )

    written = store.write(
        "runtime",
        "error",
        "should not reach disk",
        recorded_at=RECORDED,
    )

    assert not written

    assert not (
        store.path(
            "runtime"
        ).exists()
    )

    assert (
        store.stats()[
            "recordsFiltered"
        ]
        == 1
    )


def test_category_maps_to_log_hierarchy(
    tmp_path,
) -> None:
    store = RunLogStore(
        _session(
            tmp_path
        ),
        policy=RunLogPolicy(
            enabled=True,
            min_level="debug",
        ),
    )

    assert store.write(
        "executor.local",
        "info",
        "backend ready",
        recorded_at=RECORDED,
    )

    path = store.path(
        "executor.local"
    )

    assert (
        path.relative_to(
            store.root
        ).as_posix()
        == "executor/local.jsonl"
    )

    assert path.is_file()


def test_log_record_is_structured_and_redacted(
    tmp_path,
) -> None:
    store = RunLogStore(
        _session(
            tmp_path
        ),
        policy=RunLogPolicy(
            enabled=True,
            min_level="debug",
            redaction=RedactionPolicy(
                secrets=(
                    "literal-secret",
                )
            ),
        ),
    )

    assert store.write(
        "sdk.perception",
        "warning",
        (
            "failed for "
            "literal-secret"
        ),
        fields={
            "password": (
                "must-not-leak"
            ),
            "frame": 42,
        },
        recorded_at=RECORDED,
    )

    path = store.path(
        "sdk.perception"
    )

    record = json.loads(
        path.read_text(
            encoding="utf-8"
        ).splitlines()[0]
    )

    assert (
        record["category"]
        == "sdk.perception"
    )

    assert (
        record["level"]
        == "warning"
    )

    assert (
        "literal-secret"
        not in record["message"]
    )

    assert (
        DEFAULT_REDACTION_MARKER
        in record["message"]
    )

    assert (
        record["fields"]["password"]
        == DEFAULT_REDACTION_MARKER
    )

    assert (
        record["fields"]["frame"]
        == 42
    )


def test_level_filter_does_not_write(
    tmp_path,
) -> None:
    store = RunLogStore(
        _session(
            tmp_path
        ),
        policy=RunLogPolicy(
            enabled=True,
            min_level="error",
        ),
    )

    assert not store.write(
        "runtime",
        "info",
        "too verbose",
        recorded_at=RECORDED,
    )

    assert not (
        store.path(
            "runtime"
        ).exists()
    )


def test_category_prefix_filter(
    tmp_path,
) -> None:
    store = RunLogStore(
        _session(
            tmp_path
        ),
        policy=RunLogPolicy(
            enabled=True,
            min_level="debug",
            categories=(
                "executor",
            ),
        ),
    )

    assert store.write(
        "executor.local",
        "info",
        "allowed",
        recorded_at=RECORDED,
    )

    assert not store.write(
        "sdk.camera",
        "error",
        "filtered",
        recorded_at=RECORDED,
    )

    assert (
        store.path(
            "executor.local"
        ).is_file()
    )

    assert not (
        store.path(
            "sdk.camera"
        ).exists()
    )


def test_quota_overflow_drops_without_raising(
    tmp_path,
) -> None:
    store = RunLogStore(
        _session(
            tmp_path
        ),
        policy=RunLogPolicy(
            enabled=True,
            min_level="debug",
            max_bytes=512,
            max_category_bytes=512,
            max_record_bytes=512,
            overflow="drop",
        ),
    )

    result = store.write(
        "runtime",
        "error",
        "x" * 2000,
        recorded_at=RECORDED,
    )

    assert not result

    stats = store.stats()

    assert (
        stats["recordsDropped"]
        == 1
    )

    assert (
        stats["bytesDropped"]
        > 512
    )

    assert not stats[
        "captureStopped"
    ]


def test_stop_capture_overflow_disables_future_writes(
    tmp_path,
) -> None:
    store = RunLogStore(
        _session(
            tmp_path
        ),
        policy=RunLogPolicy(
            enabled=True,
            min_level="debug",
            max_bytes=512,
            max_category_bytes=512,
            max_record_bytes=512,
            overflow="stop_capture",
        ),
    )

    assert not store.write(
        "runtime",
        "error",
        "x" * 2000,
        recorded_at=RECORDED,
    )

    assert (
        store.stats()[
            "captureStopped"
        ]
    )

    assert not store.write(
        "runtime",
        "critical",
        "small later record",
        recorded_at=RECORDED,
    )

    assert (
        store.stats()[
            "recordsDropped"
        ]
        == 2
    )


def test_filesystem_failure_is_best_effort(
    tmp_path,
    monkeypatch,
) -> None:
    store = RunLogStore(
        _session(
            tmp_path
        ),
        policy=RunLogPolicy(
            enabled=True,
            min_level="debug",
        ),
    )

    def fail_append(
        path,
        encoded,
    ) -> None:
        raise OSError(
            "synthetic log disk failure"
        )

    monkeypatch.setattr(
        store,
        "_append",
        fail_append,
    )

    assert not store.write(
        "runtime",
        "error",
        "execution must continue",
        recorded_at=RECORDED,
    )

    stats = store.stats()

    assert (
        stats["recordsDropped"]
        == 1
    )

    assert stats[
        "persistenceErrors"
    ]

    assert (
        "synthetic log disk failure"
        in stats[
            "persistenceErrors"
        ][0]
    )
