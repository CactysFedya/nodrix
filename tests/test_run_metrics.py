from __future__ import annotations

from dataclasses import (
    FrozenInstanceError,
)
from datetime import (
    datetime,
    timezone,
)
import json

import pytest

from nodrix.model import (
    MetricDescriptor,
    MetricRecord,
)
from nodrix.run_metrics import (
    RUN_METRIC_RECORD_API_VERSION,
    RUN_METRIC_RECORD_KIND,
    RunMetricJournal,
    RunMetricJournalCorruptionError,
    RunMetricRecord,
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
    5,
    50,
    tzinfo=timezone.utc,
)

OBSERVED = datetime(
    2026,
    8,
    19,
    5,
    50,
    1,
    tzinfo=timezone.utc,
)

RECORDED = datetime(
    2026,
    8,
    19,
    5,
    50,
    2,
    tzinfo=timezone.utc,
)


def _clock() -> datetime:
    return CREATED


def _session(
    tmp_path,
    *,
    run_id: str = "run_metric_demo",
):
    plan = plan_canonical_system(
        SystemModel(
            name="metric-demo"
        )
    )

    store = RunStore(
        tmp_path / "runs",
        clock=_clock,
    )

    return store.create(
        plan,
        run_id=run_id,
    )


def _metric(
    value: float = 12.5,
) -> MetricRecord:
    return MetricRecord(
        descriptor=MetricDescriptor(
            name="mapping.update_ms",
            value_type="float",
            unit="ms",
            description=(
                "Voxel-map update latency"
            ),
        ),
        value=value,
        observed_at=OBSERVED,
        source="mapping.voxel_map",
        attributes={
            "sensor": "mid360",
        },
    )


def test_run_metric_record_is_immutable() -> None:
    record = RunMetricRecord(
        run_id="run_metric_demo",
        sequence=1,
        recorded_at=RECORDED,
        metric=_metric(),
    )

    with pytest.raises(
        FrozenInstanceError,
    ):
        record.sequence = 2  # type: ignore[misc]


def test_metric_journal_is_optional_and_created_lazily(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    assert (
        journal.path
        == session.directory
        / "metrics"
        / "records.jsonl"
    )

    assert not session.metrics_path.exists()
    assert not journal.path.exists()

    assert journal.next_sequence == 1
    assert journal.read_all() == ()

    assert not session.metrics_path.exists()


def test_journal_wraps_typed_metric_in_versioned_run_record(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    metric = _metric()

    record = journal.append(
        metric,
        recorded_at=RECORDED,
    )

    assert isinstance(
        record,
        RunMetricRecord,
    )

    assert (
        record.run_id
        == session.run_id
    )
    assert record.sequence == 1
    assert record.metric is metric

    document = (
        record.to_document()
    )

    assert (
        document["apiVersion"]
        == RUN_METRIC_RECORD_API_VERSION
    )
    assert (
        document["kind"]
        == RUN_METRIC_RECORD_KIND
    )
    assert (
        document["runId"]
        == session.run_id
    )
    assert (
        document["recordedAt"]
        == "2026-08-19T05:50:02.000000Z"
    )

    nested = document[
        "metric"
    ]

    assert (
        nested["observedAt"]
        == "2026-08-19T05:50:01.000000Z"
    )

    assert (
        nested["descriptor"][
            "descriptorId"
        ]
        == metric.descriptor_id
    )

    assert (
        nested["descriptor"][
            "name"
        ]
        == "mapping.update_ms"
    )


def test_sequence_survives_journal_reopen(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    first = RunMetricJournal(
        session
    )

    first.append(
        _metric(1.0),
        recorded_at=RECORDED,
    )

    second = RunMetricJournal(
        session
    )

    assert second.next_sequence == 2

    second.append(
        _metric(2.0),
        recorded_at=RECORDED,
    )

    records = second.read_all()

    assert [
        record.sequence
        for record in records
    ] == [1, 2]

    assert [
        record.metric.value
        for record in records
    ] == [1.0, 2.0]


def test_journal_is_jsonl_append_only(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    journal.append(
        _metric(1.0),
        recorded_at=RECORDED,
    )

    first_bytes = (
        journal.path.read_bytes()
    )

    journal.append(
        _metric(2.0),
        recorded_at=RECORDED,
    )

    second_bytes = (
        journal.path.read_bytes()
    )

    assert second_bytes.startswith(
        first_bytes
    )

    assert second_bytes.count(
        b"\n"
    ) == 2


def test_read_all_returns_typed_metric_records(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    journal.append(
        _metric(),
        recorded_at=RECORDED,
    )

    records = journal.read_all()

    assert len(records) == 1

    record = records[0]

    assert isinstance(
        record,
        RunMetricRecord,
    )
    assert isinstance(
        record.metric,
        MetricRecord,
    )

    assert (
        record.metric.name
        == "mapping.update_ms"
    )
    assert (
        record.metric.unit
        == "ms"
    )
    assert (
        record.metric.source
        == "mapping.voxel_map"
    )


def test_recorded_and_observed_times_are_normalized_to_utc(
    tmp_path,
) -> None:
    offset = timezone.utc

    metric = MetricRecord(
        descriptor=MetricDescriptor(
            name="sdk.rate",
            value_type="float",
            unit="Hz",
        ),
        value=20.0,
        observed_at=datetime(
            2026,
            8,
            19,
            5,
            55,
            tzinfo=offset,
        ),
    )

    session = _session(
        tmp_path
    )

    record = RunMetricJournal(
        session
    ).append(
        metric,
        recorded_at=datetime(
            2026,
            8,
            19,
            5,
            56,
            tzinfo=offset,
        ),
    )

    assert (
        record.recorded_at.tzinfo
        is timezone.utc
    )

    restored = RunMetricRecord.from_document(
        record.to_document()
    )

    assert (
        restored.metric.observed_at.tzinfo
        is timezone.utc
    )


def test_descriptor_identity_is_verified_when_reading(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    journal.append(
        _metric(),
        recorded_at=RECORDED,
    )

    document = json.loads(
        journal.path.read_text(
            encoding="utf-8"
        )
    )

    document[
        "metric"
    ][
        "descriptor"
    ][
        "descriptorId"
    ] = "metric-tampered"

    journal.path.write_text(
        json.dumps(
            document,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunMetricJournalCorruptionError,
    ):
        RunMetricJournal(
            session
        )


def test_foreign_run_id_is_corruption(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    journal.append(
        _metric(),
        recorded_at=RECORDED,
    )

    document = json.loads(
        journal.path.read_text(
            encoding="utf-8"
        )
    )

    document[
        "runId"
    ] = "run_other"

    journal.path.write_text(
        json.dumps(
            document,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunMetricJournalCorruptionError,
        match="different Run",
    ):
        RunMetricJournal(
            session
        )


def test_non_contiguous_sequence_is_corruption(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    record = journal.append(
        _metric(),
        recorded_at=RECORDED,
    ).to_document()

    record[
        "sequence"
    ] = 2

    journal.path.write_text(
        json.dumps(
            record,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunMetricJournalCorruptionError,
        match="not contiguous",
    ):
        RunMetricJournal(
            session
        )


def test_incomplete_final_record_is_corruption(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    journal.directory.mkdir(
        parents=True
    )

    journal.path.write_bytes(
        b'{"apiVersion":"broken"}'
    )

    with pytest.raises(
        RunMetricJournalCorruptionError,
        match="incomplete",
    ):
        RunMetricJournal(
            session
        )


def test_invalid_json_is_corruption(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    journal.directory.mkdir(
        parents=True
    )

    journal.path.write_bytes(
        b"{not-json}\n"
    )

    with pytest.raises(
        RunMetricJournalCorruptionError,
        match="invalid JSON",
    ):
        RunMetricJournal(
            session
        )


def test_legacy_root_metrics_jsonl_is_not_canonical_journal(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    legacy = (
        session.directory
        / "metrics.jsonl"
    )

    legacy.write_text(
        '{"legacy":"runtime-snapshot"}\n',
        encoding="utf-8",
    )

    journal = RunMetricJournal(
        session
    )

    assert journal.next_sequence == 1
    assert journal.read_all() == ()
    assert not journal.path.exists()

    journal.append(
        _metric(),
        recorded_at=RECORDED,
    )

    assert legacy.read_text(
        encoding="utf-8"
    ) == (
        '{"legacy":"runtime-snapshot"}\n'
    )

    assert journal.path.is_file()


def test_journal_rejects_non_metric_record(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    with pytest.raises(
        TypeError,
        match="MetricRecord",
    ):
        journal.append(  # type: ignore[arg-type]
            {
                "value": 1
            },
            recorded_at=RECORDED,
        )


def test_record_limit_drops_metric_and_persists_loss_status(
    tmp_path,
) -> None:
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )

    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session,
        policy=RunMetricPolicy(
            max_records=1,
            max_bytes=1024 * 1024,
            max_record_bytes=64 * 1024,
        ),
    )

    first = journal.append(
        _metric(1.0),
        recorded_at=RECORDED,
    )

    second = journal.append(
        _metric(2.0),
        recorded_at=RECORDED,
    )

    assert first is not None
    assert second is None

    assert journal.stored_records == 1
    assert journal.dropped_records == 1
    assert journal.loss_occurred
    assert (
        journal.last_drop_reason
        == "record-limit"
    )

    assert journal.next_sequence == 2
    assert journal.status_path.is_file()

    status = json.loads(
        journal.status_path.read_text(
            encoding="utf-8"
        )
    )

    assert status["lossOccurred"] is True
    assert status["droppedRecords"] == 1
    assert status["droppedBytes"] > 0
    assert (
        status["lastDropReason"]
        == "record-limit"
    )


def test_oversized_metric_is_dropped_without_creating_record_journal(
    tmp_path,
) -> None:
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )

    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session,
        policy=RunMetricPolicy(
            max_records=100,
            max_bytes=1024 * 1024,
            max_record_bytes=64,
        ),
    )

    result = journal.append(
        _metric(),
        recorded_at=RECORDED,
    )

    assert result is None
    assert journal.next_sequence == 1
    assert journal.stored_records == 0
    assert journal.dropped_records == 1
    assert (
        journal.last_drop_reason
        == "record-too-large"
    )

    assert not journal.path.exists()
    assert journal.status_path.is_file()


def test_byte_limit_drops_metric_without_breaking_sequence(
    tmp_path,
) -> None:
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )

    session = _session(
        tmp_path,
        run_id="run_metric_byte_limit",
    )

    # First persist one exact record for this Run.  Run identity is part of
    # the encoded envelope, so byte-budget tests must use the same Run rather
    # than estimating size from another run_id.
    initial = RunMetricJournal(
        session
    )

    first = initial.append(
        _metric(1.0),
        recorded_at=RECORDED,
    )

    assert first is not None

    record_bytes = (
        initial.path.stat().st_size
    )

    # Reopen the same durable journal with a budget exactly equal to the
    # already persisted history.  No additional record can fit.
    journal = RunMetricJournal(
        session,
        policy=RunMetricPolicy(
            max_records=100,
            max_bytes=record_bytes,
            max_record_bytes=64 * 1024,
        ),
    )

    assert journal.stored_records == 1
    assert journal.stored_bytes == record_bytes
    assert journal.next_sequence == 2

    second = journal.append(
        _metric(2.0),
        recorded_at=RECORDED,
    )

    assert second is None

    # Dropped observations never consume canonical journal sequence numbers.
    assert journal.next_sequence == 2
    assert journal.stored_records == 1
    assert (
        journal.stored_bytes
        == record_bytes
    )
    assert journal.dropped_records == 1
    assert journal.loss_occurred
    assert (
        journal.last_drop_reason
        == "byte-limit"
    )

    records = journal.read_all()

    assert len(records) == 1
    assert records[0].sequence == 1
    assert records[0].metric.value == 1.0


def test_loss_counters_survive_reopen(
    tmp_path,
) -> None:
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )

    session = _session(
        tmp_path
    )

    policy = RunMetricPolicy(
        max_records=1,
        max_bytes=1024 * 1024,
        max_record_bytes=64 * 1024,
    )

    first = RunMetricJournal(
        session,
        policy=policy,
    )

    assert first.append(
        _metric(1.0),
        recorded_at=RECORDED,
    ) is not None

    assert first.append(
        _metric(2.0),
        recorded_at=RECORDED,
    ) is None

    reopened = RunMetricJournal(
        session,
        policy=policy,
    )

    assert reopened.stored_records == 1
    assert reopened.dropped_records == 1
    assert reopened.dropped_bytes > 0
    assert reopened.loss_occurred
    assert (
        reopened.last_drop_reason
        == "record-limit"
    )


def test_loss_status_for_foreign_run_is_corruption(
    tmp_path,
) -> None:
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )

    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session,
        policy=RunMetricPolicy(
            max_records=1,
        ),
    )

    assert journal.append(
        _metric(1.0),
        recorded_at=RECORDED,
    ) is not None

    assert journal.append(
        _metric(2.0),
        recorded_at=RECORDED,
    ) is None

    document = json.loads(
        journal.status_path.read_text(
            encoding="utf-8"
        )
    )

    document["runId"] = "run_other"

    journal.status_path.write_text(
        json.dumps(
            document,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        RunMetricJournalCorruptionError,
        match="different Run",
    ):
        RunMetricJournal(
            session
        )


def test_run_metric_sink_accepts_persisted_metric(
    tmp_path,
) -> None:
    from datetime import datetime, timezone

    from nodrix.metric_publisher import (
        MetricPublisher,
    )
    from nodrix.run_metrics import (
        RunMetricSink,
    )

    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    sink = RunMetricSink(
        journal
    )

    publisher = MetricPublisher(
        source="worker",
        sink=sink,
    )

    result = publisher.observe(
        "worker.items",
        1,
        value_type="integer",
        unit="count",
        observed_at=datetime(
            2026,
            8,
            19,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert result.accepted
    assert result.reason is None

    records = journal.read_all()

    assert len(records) == 1
    assert (
        records[0].metric.name
        == "worker.items"
    )


def test_run_metric_sink_reports_policy_drop(
    tmp_path,
) -> None:
    from nodrix.metric_publisher import (
        MetricPublisher,
    )
    from nodrix.run_metric_policy import (
        RunMetricPolicy,
    )
    from nodrix.run_metrics import (
        RunMetricSink,
    )

    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session,
        policy=RunMetricPolicy(
            max_records=1,
            max_bytes=1024 * 1024,
            max_record_bytes=64 * 1024,
        ),
    )

    publisher = MetricPublisher(
        source="worker",
        sink=RunMetricSink(
            journal
        ),
    )

    first = publisher.observe(
        "worker.items",
        1,
        value_type="integer",
        unit="count",
    )

    second = publisher.observe(
        "worker.items",
        2,
        value_type="integer",
        unit="count",
    )

    assert first.accepted

    assert not second.accepted
    assert (
        second.reason
        == "record-limit"
    )

    assert (
        journal.dropped_records
        == 1
    )


def test_run_metric_sink_storage_failure_is_nonfatal(
    tmp_path,
    monkeypatch,
) -> None:
    from nodrix.metric_publisher import (
        MetricPublisher,
    )
    from nodrix.run_metrics import (
        RunMetricSink,
    )

    session = _session(
        tmp_path
    )

    journal = RunMetricJournal(
        session
    )

    def fail_append(
        metric,
        *,
        recorded_at=None,
    ):
        raise OSError(
            "synthetic Metric storage failure"
        )

    monkeypatch.setattr(
        journal,
        "append",
        fail_append,
    )

    publisher = MetricPublisher(
        source="worker",
        sink=RunMetricSink(
            journal
        ),
    )

    result = publisher.observe(
        "worker.items",
        1,
        value_type="integer",
        unit="count",
    )

    assert not result.accepted
    assert (
        result.reason
        == "storage-error"
    )
