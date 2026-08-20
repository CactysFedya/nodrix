from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.model import (
    ExecutionRecord,
    MetricDescriptor,
    MetricRecord,
)
from nodrix.run_bundle import (
    load_canonical_run_bundle,
)
from nodrix.run_comparison import (
    compare_canonical_run_bundles,
)
from nodrix.run_metric_comparison import (
    compare_run_metrics,
)
from nodrix.run_metric_policy import (
    RunMetricPolicy,
)
from nodrix.run_metrics import (
    RunMetricJournal,
)
from nodrix.run_policy import (
    RunPolicyStore,
)
from nodrix.run_record import (
    RunRecordStore,
)
from nodrix.run_session import (
    RunStore,
)
from nodrix.run_snapshots import (
    DEFINITION_SNAPSHOT,
    PLAN_SNAPSHOT,
    RunSnapshotStore,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.model import (
    SystemModel,
)
from nodrix.system.run_snapshots import (
    system_definition_snapshot,
    system_plan_snapshot,
)


STARTED = datetime(
    2026,
    8,
    20,
    9,
    0,
    tzinfo=timezone.utc,
)


def _create_run(
    root,
    *,
    run_id: str,
    execution_id: str,
    policy: ExecutionPolicy,
):
    system = SystemModel(
        name="metric-comparison"
    )

    plan = plan_canonical_system(
        system
    )

    session = RunStore(
        root,
        clock=lambda: STARTED,
    ).create(
        plan,
        run_id=run_id,
    )

    snapshots = RunSnapshotStore(
        session
    )

    snapshots.create(
        DEFINITION_SNAPSHOT,
        system_definition_snapshot(
            system,
            plan,
        ),
    )

    snapshots.create(
        PLAN_SNAPSHOT,
        system_plan_snapshot(
            plan
        ),
    )

    RunPolicyStore(
        session,
        policy=policy,
    ).create()

    return (
        session,
        plan,
    )


def _finish(
    session,
    plan,
    *,
    execution_id: str,
) -> None:
    execution = ExecutionRecord(
        execution_id=execution_id,
        plan=plan,
        executor=(
            "nodrix.system.orchestrator"
        ),
        state="completed",
        started_at=STARTED,
        finished_at=(
            STARTED
            + timedelta(
                seconds=10
            )
        ),
    )

    RunRecordStore(
        session
    ).create(
        execution
    )


def _metric(
    descriptor: MetricDescriptor,
    value,
    *,
    offset: int,
) -> MetricRecord:
    return MetricRecord(
        descriptor=descriptor,
        value=value,
        observed_at=(
            STARTED
            + timedelta(
                seconds=offset
            )
        ),
        source="test.component",
    )


def _append(
    journal: RunMetricJournal,
    descriptor: MetricDescriptor,
    values,
) -> None:
    for index, value in enumerate(
        values,
        start=1,
    ):
        journal.append(
            _metric(
                descriptor,
                value,
                offset=index,
            ),
            recorded_at=(
                STARTED
                + timedelta(
                    seconds=index,
                    microseconds=1,
                )
            ),
        )


def _bundle(
    session,
):
    return load_canonical_run_bundle(
        session.directory
    )


def test_numeric_metric_series_are_summarized_and_compared(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    metric_policy = RunMetricPolicy()

    first_session, first_plan = (
        _create_run(
            root,
            run_id="run_metric_compare_a",
            execution_id="execution-a",
            policy=ExecutionPolicy(
                metrics=metric_policy,
            ),
        )
    )

    second_session, second_plan = (
        _create_run(
            root,
            run_id="run_metric_compare_b",
            execution_id="execution-b",
            policy=ExecutionPolicy(
                metrics=metric_policy,
            ),
        )
    )

    descriptor = MetricDescriptor(
        name="mapping.update_ms",
        value_type="float",
        unit="ms",
    )

    _append(
        RunMetricJournal(
            first_session,
            policy=metric_policy,
        ),
        descriptor,
        (10.0, 20.0),
    )

    _append(
        RunMetricJournal(
            second_session,
            policy=metric_policy,
        ),
        descriptor,
        (15.0, 25.0),
    )

    _finish(
        first_session,
        first_plan,
        execution_id="execution-a",
    )

    _finish(
        second_session,
        second_plan,
        execution_id="execution-b",
    )

    comparison = compare_run_metrics(
        _bundle(first_session),
        _bundle(second_session),
    )

    assert len(
        comparison.descriptors
    ) == 1

    metric = (
        comparison.descriptors[0]
    )

    assert (
        metric.descriptor_id
        == descriptor.descriptor_id
    )

    assert metric.comparable is True

    assert metric.first is not None
    assert metric.second is not None

    assert metric.first.count == 2
    assert metric.first.minimum == 10.0
    assert metric.first.maximum == 20.0
    assert metric.first.mean == 15.0
    assert metric.first.last == 20.0

    assert metric.second.mean == 20.0

    assert metric.count_delta == 0
    assert metric.mean_delta == 5.0

    assert metric.mean_percent == pytest.approx(
        33.33333333333333
    )


def test_integer_metrics_preserve_integer_min_max_and_last(
    tmp_path,
) -> None:
    root = tmp_path / "runs"
    metric_policy = RunMetricPolicy()

    first_session, first_plan = _create_run(
        root,
        run_id="run_integer_a",
        execution_id="execution-a",
        policy=ExecutionPolicy(
            metrics=metric_policy,
        ),
    )

    second_session, second_plan = _create_run(
        root,
        run_id="run_integer_b",
        execution_id="execution-b",
        policy=ExecutionPolicy(
            metrics=metric_policy,
        ),
    )

    descriptor = MetricDescriptor(
        name="mapping.voxels",
        value_type="integer",
        unit="count",
    )

    _append(
        RunMetricJournal(
            first_session,
            policy=metric_policy,
        ),
        descriptor,
        (10, 20, 30),
    )

    _append(
        RunMetricJournal(
            second_session,
            policy=metric_policy,
        ),
        descriptor,
        (20, 30, 40),
    )

    _finish(
        first_session,
        first_plan,
        execution_id="execution-a",
    )

    _finish(
        second_session,
        second_plan,
        execution_id="execution-b",
    )

    metric = compare_run_metrics(
        _bundle(first_session),
        _bundle(second_session),
    ).descriptors[0]

    assert metric.first is not None

    assert metric.first.minimum == 10
    assert isinstance(
        metric.first.minimum,
        int,
    )

    assert metric.first.maximum == 30
    assert metric.first.last == 30
    assert metric.first.mean == 20.0


def test_descriptor_identity_not_description_controls_matching(
    tmp_path,
) -> None:
    root = tmp_path / "runs"
    metric_policy = RunMetricPolicy()

    first_session, first_plan = _create_run(
        root,
        run_id="run_description_a",
        execution_id="execution-a",
        policy=ExecutionPolicy(
            metrics=metric_policy,
        ),
    )

    second_session, second_plan = _create_run(
        root,
        run_id="run_description_b",
        execution_id="execution-b",
        policy=ExecutionPolicy(
            metrics=metric_policy,
        ),
    )

    first_descriptor = MetricDescriptor(
        name="detector.inference_ms",
        value_type="float",
        unit="ms",
        description="old docs",
    )

    second_descriptor = MetricDescriptor(
        name="detector.inference_ms",
        value_type="float",
        unit="ms",
        description="new docs",
    )

    assert (
        first_descriptor.descriptor_id
        == second_descriptor.descriptor_id
    )

    _append(
        RunMetricJournal(
            first_session,
            policy=metric_policy,
        ),
        first_descriptor,
        (5.0,),
    )

    _append(
        RunMetricJournal(
            second_session,
            policy=metric_policy,
        ),
        second_descriptor,
        (6.0,),
    )

    _finish(
        first_session,
        first_plan,
        execution_id="execution-a",
    )

    _finish(
        second_session,
        second_plan,
        execution_id="execution-b",
    )

    comparison = compare_run_metrics(
        _bundle(first_session),
        _bundle(second_session),
    )

    assert len(
        comparison.descriptors
    ) == 1

    assert (
        comparison.descriptors[0].comparable
        is True
    )


def test_unit_change_creates_distinct_metric_descriptors(
    tmp_path,
) -> None:
    root = tmp_path / "runs"
    metric_policy = RunMetricPolicy()

    first_session, first_plan = _create_run(
        root,
        run_id="run_unit_a",
        execution_id="execution-a",
        policy=ExecutionPolicy(
            metrics=metric_policy,
        ),
    )

    second_session, second_plan = _create_run(
        root,
        run_id="run_unit_b",
        execution_id="execution-b",
        policy=ExecutionPolicy(
            metrics=metric_policy,
        ),
    )

    first_descriptor = MetricDescriptor(
        name="mapping.latency",
        value_type="float",
        unit="ms",
    )

    second_descriptor = MetricDescriptor(
        name="mapping.latency",
        value_type="float",
        unit="s",
    )

    assert (
        first_descriptor.descriptor_id
        != second_descriptor.descriptor_id
    )

    _append(
        RunMetricJournal(
            first_session,
            policy=metric_policy,
        ),
        first_descriptor,
        (10.0,),
    )

    _append(
        RunMetricJournal(
            second_session,
            policy=metric_policy,
        ),
        second_descriptor,
        (0.01,),
    )

    _finish(
        first_session,
        first_plan,
        execution_id="execution-a",
    )

    _finish(
        second_session,
        second_plan,
        execution_id="execution-b",
    )

    comparison = compare_run_metrics(
        _bundle(first_session),
        _bundle(second_session),
    )

    assert len(
        comparison.descriptors
    ) == 2

    assert all(
        not item.comparable
        for item
        in comparison.descriptors
    )

    assert all(
        item.mean_delta is None
        for item
        in comparison.descriptors
    )


def test_metric_storage_loss_is_explicit_in_comparison(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    limited = RunMetricPolicy(
        max_records=1,
        max_bytes=1024 * 1024,
        max_record_bytes=64 * 1024,
    )

    normal = RunMetricPolicy()

    first_session, first_plan = _create_run(
        root,
        run_id="run_loss_a",
        execution_id="execution-a",
        policy=ExecutionPolicy(
            metrics=limited,
        ),
    )

    second_session, second_plan = _create_run(
        root,
        run_id="run_loss_b",
        execution_id="execution-b",
        policy=ExecutionPolicy(
            metrics=normal,
        ),
    )

    descriptor = MetricDescriptor(
        name="mapping.update_ms",
        value_type="float",
        unit="ms",
    )

    first_journal = RunMetricJournal(
        first_session,
        policy=limited,
    )

    _append(
        first_journal,
        descriptor,
        (10.0, 20.0),
    )

    _append(
        RunMetricJournal(
            second_session,
            policy=normal,
        ),
        descriptor,
        (10.0, 20.0),
    )

    _finish(
        first_session,
        first_plan,
        execution_id="execution-a",
    )

    _finish(
        second_session,
        second_plan,
        execution_id="execution-b",
    )

    comparison = compare_run_metrics(
        _bundle(first_session),
        _bundle(second_session),
    )

    assert (
        comparison.first.stored_records
        == 1
    )

    assert (
        comparison.first.dropped_records
        == 1
    )

    assert (
        comparison.first.dropped_bytes
        > 0
    )

    assert (
        comparison.first.complete
        is False
    )

    assert (
        comparison.first.loss_occurred
        is True
    )

    assert (
        comparison.first.last_drop_reason
        == "record-limit"
    )

    assert (
        comparison.second.complete
        is True
    )

    assert (
        comparison.complete
        is False
    )


def test_metrics_disabled_is_distinct_from_metric_loss(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    first_session, first_plan = _create_run(
        root,
        run_id="run_disabled_a",
        execution_id="execution-a",
        policy=ExecutionPolicy(),
    )

    second_session, second_plan = _create_run(
        root,
        run_id="run_disabled_b",
        execution_id="execution-b",
        policy=ExecutionPolicy(),
    )

    _finish(
        first_session,
        first_plan,
        execution_id="execution-a",
    )

    _finish(
        second_session,
        second_plan,
        execution_id="execution-b",
    )

    comparison = compare_run_metrics(
        _bundle(first_session),
        _bundle(second_session),
    )

    assert (
        comparison.first.metrics_enabled
        is False
    )

    assert (
        comparison.first.stored_records
        == 0
    )

    assert (
        comparison.first.dropped_records
        == 0
    )

    assert (
        comparison.first.complete
        is True
    )

    assert (
        comparison.first.loss_occurred
        is False
    )

    assert comparison.descriptors == ()


def test_bundle_comparison_contains_metric_completeness(
    tmp_path,
) -> None:
    root = tmp_path / "runs"
    metric_policy = RunMetricPolicy()

    first_session, first_plan = _create_run(
        root,
        run_id="run_integrated_a",
        execution_id="execution-a",
        policy=ExecutionPolicy(
            metrics=metric_policy,
        ),
    )

    second_session, second_plan = _create_run(
        root,
        run_id="run_integrated_b",
        execution_id="execution-b",
        policy=ExecutionPolicy(
            metrics=metric_policy,
        ),
    )

    descriptor = MetricDescriptor(
        name="system.temperature",
        value_type="float",
        unit="celsius",
    )

    _append(
        RunMetricJournal(
            first_session,
            policy=metric_policy,
        ),
        descriptor,
        (50.0,),
    )

    _append(
        RunMetricJournal(
            second_session,
            policy=metric_policy,
        ),
        descriptor,
        (55.0,),
    )

    _finish(
        first_session,
        first_plan,
        execution_id="execution-a",
    )

    _finish(
        second_session,
        second_plan,
        execution_id="execution-b",
    )

    comparison = (
        compare_canonical_run_bundles(
            _bundle(first_session),
            _bundle(second_session),
        )
    )

    document = comparison.to_dict()

    assert (
        document[
            "metrics"
        ][
            "complete"
        ]
        is True
    )

    assert len(
        document[
            "metrics"
        ][
            "descriptors"
        ]
    ) == 1

    metric = document[
        "metrics"
    ][
        "descriptors"
    ][0]

    assert metric[
        "descriptorId"
    ] == descriptor.descriptor_id

    assert metric[
        "meanDelta"
    ] == 5.0
