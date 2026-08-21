from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)
import json

import pytest

from nodrix.benchmark_runs import (
    BenchmarkWorkloadMismatchError,
    aggregate_canonical_benchmark_runs,
    benchmark_observation_from_bundle,
)
from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.model import (
    ExecutionRecord,
    MetricDescriptor,
    MetricRecord,
)
from nodrix.observability_profiles import (
    resolve_observability_profile,
)
from nodrix.run_bundle import (
    load_canonical_run_bundle,
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
    RUN_LAYOUT_SCHEMA_V1,
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
    13,
    0,
    tzinfo=timezone.utc,
)


def _create_run(
    root,
    *,
    system: SystemModel,
    plan,
    run_id: str,
    execution_id: str,
    duration: float = 10.0,
    successful: bool = True,
    policy: ExecutionPolicy | None = None,
    execution_details: dict[str, object] | None = None,
):
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
        policy=(
            policy
            if policy is not None
            else ExecutionPolicy()
        ),
    ).create()

    RunRecordStore(
        session
    ).create(
        ExecutionRecord(
            execution_id=execution_id,
            plan=plan,
            executor=(
                "nodrix.system.orchestrator"
            ),
            state=(
                "completed"
                if successful
                else "failed"
            ),
            started_at=STARTED,
            finished_at=(
                STARTED
                + timedelta(
                    seconds=duration
                )
            ),
            details=(execution_details or {}),
        )
    )

    return session


def _bundle(
    session,
):
    return load_canonical_run_bundle(
        session.directory
    )


def _append_metric(
    session,
    policy,
    descriptor,
    values,
) -> None:
    journal = RunMetricJournal(
        session,
        policy=policy,
    )

    for index, value in enumerate(
        values,
        start=1,
    ):
        journal.append(
            MetricRecord(
                descriptor=descriptor,
                value=value,
                observed_at=(
                    STARTED
                    + timedelta(
                        seconds=index
                    )
                ),
                source="benchmark-test",
            ),
            recorded_at=(
                STARTED
                + timedelta(
                    seconds=index,
                    microseconds=1,
                )
            ),
        )


def test_bundle_is_converted_to_benchmark_observation(
    tmp_path,
) -> None:
    system = SystemModel(
        name="benchmark-bridge"
    )

    plan = plan_canonical_system(
        system
    )

    session = _create_run(
        tmp_path / "runs",
        system=system,
        plan=plan,
        run_id="run_bridge",
        execution_id="execution-bridge",
        duration=12.5,
    )

    observation = (
        benchmark_observation_from_bundle(
            _bundle(
                session
            )
        )
    )

    assert (
        observation.run_id
        == "run_bridge"
    )

    assert (
        observation.successful
        is True
    )

    assert (
        observation.duration_seconds
        == 12.5
    )

    assert (
        observation.metrics_enabled
        is False
    )

    assert (
        observation.metrics_complete
        is True
    )


def test_repeated_exact_runs_are_aggregated(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    system = SystemModel(
        name="benchmark-repeat"
    )

    plan = plan_canonical_system(
        system
    )

    first = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_repeat-a",
        execution_id="execution-a",
        duration=10.0,
    )

    second = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_repeat-b",
        execution_id="execution-b",
        duration=12.0,
    )

    result = (
        aggregate_canonical_benchmark_runs(
            (
                _bundle(first),
                _bundle(second),
            )
        )
    )

    assert (
        result.workload.plan_id
        == plan.plan_id
    )

    assert (
        result.aggregate.run_count
        == 2
    )

    assert (
        result.aggregate.duration.mean
        == 11.0
    )

    assert (
        result.policy_comparable
        is True
    )

    assert (
        result.same_effective_policy
        is True
    )


def test_exact_workload_mismatch_is_rejected(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    first_system = SystemModel(
        name="benchmark-workload",
        description="first",
    )

    second_system = SystemModel(
        name="benchmark-workload",
        description="second",
    )

    first_plan = plan_canonical_system(
        first_system
    )

    second_plan = plan_canonical_system(
        second_system
    )

    first = _create_run(
        root,
        system=first_system,
        plan=first_plan,
        run_id="run_workload-a",
        execution_id="execution-a",
    )

    second = _create_run(
        root,
        system=second_system,
        plan=second_plan,
        run_id="run_workload-b",
        execution_id="execution-b",
    )

    with pytest.raises(
        BenchmarkWorkloadMismatchError,
        match="one exact workload",
    ):
        aggregate_canonical_benchmark_runs(
            (
                _bundle(first),
                _bundle(second),
            )
        )


def test_policy_difference_is_explicit_but_not_workload_mismatch(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    system = SystemModel(
        name="benchmark-policy"
    )

    plan = plan_canonical_system(
        system
    )

    first = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy-a",
        execution_id="execution-a",
        policy=ExecutionPolicy(),
    )

    second = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy-b",
        execution_id="execution-b",
        policy=(
            resolve_observability_profile(
                "debug"
            )
        ),
    )

    result = (
        aggregate_canonical_benchmark_runs(
            (
                _bundle(first),
                _bundle(second),
            )
        )
    )

    assert (
        result.aggregate.run_count
        == 2
    )

    assert (
        result.policy_comparable
        is True
    )

    assert (
        result.same_effective_policy
        is False
    )


def test_historical_missing_policy_is_not_claimed_equal(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    system = SystemModel(
        name="benchmark-policy-history"
    )

    plan = plan_canonical_system(
        system
    )

    first = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy-old",
        execution_id="execution-a",
    )

    second = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy-new",
        execution_id="execution-b",
    )

    session_document = json.loads(
        first.session_path.read_text(
            encoding="utf-8"
        )
    )

    session_document[
        "layout"
    ] = RUN_LAYOUT_SCHEMA_V1

    first.session_path.write_text(
        json.dumps(
            session_document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (
        first.directory
        / "policy.json"
    ).unlink()

    result = (
        aggregate_canonical_benchmark_runs(
            (
                _bundle(first),
                _bundle(second),
            )
        )
    )

    assert (
        result.policy_comparable
        is False
    )

    assert (
        result.same_effective_policy
        is None
    )


def test_typed_metrics_flow_into_run_weighted_aggregate(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    system = SystemModel(
        name="benchmark-metrics"
    )

    plan = plan_canonical_system(
        system
    )

    metric_policy = RunMetricPolicy()

    policy = ExecutionPolicy(
        metrics=metric_policy
    )

    first = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_metrics-a",
        execution_id="execution-a",
        policy=policy,
    )

    second = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_metrics-b",
        execution_id="execution-b",
        policy=policy,
    )

    descriptor = MetricDescriptor(
        name="mapping.update_ms",
        value_type="float",
        unit="ms",
    )

    _append_metric(
        first,
        metric_policy,
        descriptor,
        [10.0] * 100,
    )

    _append_metric(
        second,
        metric_policy,
        descriptor,
        [20.0],
    )

    result = (
        aggregate_canonical_benchmark_runs(
            (
                _bundle(first),
                _bundle(second),
            )
        )
    )

    assert len(
        result.aggregate.metrics
    ) == 1

    metric = (
        result.aggregate.metrics[
            0
        ]
    )

    assert (
        metric.total_observations
        == 101
    )

    assert (
        metric.run_means.mean
        == 15.0
    )


def test_metric_storage_loss_propagates_from_persisted_run(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    system = SystemModel(
        name="benchmark-loss"
    )

    plan = plan_canonical_system(
        system
    )

    limited = RunMetricPolicy(
        max_records=1,
        max_bytes=1024 * 1024,
        max_record_bytes=64 * 1024,
    )

    policy = ExecutionPolicy(
        metrics=limited
    )

    first = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_loss-a",
        execution_id="execution-a",
        policy=policy,
    )

    second = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_loss-b",
        execution_id="execution-b",
        policy=policy,
    )

    descriptor = MetricDescriptor(
        name="mapping.update_ms",
        value_type="float",
        unit="ms",
    )

    _append_metric(
        first,
        limited,
        descriptor,
        (10.0, 20.0),
    )

    _append_metric(
        second,
        limited,
        descriptor,
        (10.0,),
    )

    result = (
        aggregate_canonical_benchmark_runs(
            (
                _bundle(first),
                _bundle(second),
            )
        )
    )

    assert (
        result.aggregate.execution_complete
        is True
    )

    assert (
        result.aggregate.metrics_storage_complete
        is False
    )

    assert (
        result.aggregate.complete
        is False
    )

    assert (
        result.aggregate.metrics[
            0
        ].complete
        is False
    )


def test_failed_run_is_kept_as_evidence_but_not_in_duration_mean(
    tmp_path,
) -> None:
    root = tmp_path / "runs"

    system = SystemModel(
        name="benchmark-failure"
    )

    plan = plan_canonical_system(
        system
    )

    first = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_success",
        execution_id="execution-success",
        duration=10.0,
    )

    second = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_failed",
        execution_id="execution-failed",
        duration=100.0,
        successful=False,
    )

    result = (
        aggregate_canonical_benchmark_runs(
            (
                _bundle(first),
                _bundle(second),
            )
        )
    )

    assert (
        result.aggregate.failed_run_ids
        == (
            "run_failed",
        )
    )

    assert (
        result.aggregate.duration.mean
        == 10.0
    )

    assert (
        result.aggregate.execution_complete
        is False
    )


def test_strict_benchmark_observation_uses_backend_measured_duration(
    tmp_path,
) -> None:
    system = SystemModel(
        name="benchmark-measured-timing"
    )

    plan = plan_canonical_system(
        system
    )

    session = _create_run(
        tmp_path / "runs",
        system=system,
        plan=plan,
        run_id="run_measured-timing",
        execution_id="execution-measured",
        # Lifecycle duration deliberately differs from measured duration.
        duration=100.0,
        execution_details={
            "execution_timing": {
                "source": "backend",
                "target": "host",
                "backend": "local",
                "execution_id": "local-measured",
                "duration_seconds": 3.25,
            },
        },
    )

    observation = (
        benchmark_observation_from_bundle(
            _bundle(
                session
            ),
            require_measured_timing=True,
        )
    )

    assert (
        observation.duration_seconds
        == 3.25
    )


def test_strict_benchmark_observation_rejects_lifecycle_fallback(
    tmp_path,
) -> None:
    system = SystemModel(
        name="benchmark-no-measured-timing"
    )

    plan = plan_canonical_system(
        system
    )

    session = _create_run(
        tmp_path / "runs",
        system=system,
        plan=plan,
        run_id="run_no-measured-timing",
        execution_id="execution-no-measured",
        duration=10.0,
    )

    with pytest.raises(
        RuntimeError,
        match="does not contain exact backend execution timing",
    ):
        benchmark_observation_from_bundle(
            _bundle(
                session
            ),
            require_measured_timing=True,
        )

    # Historical/general observation remains backward-compatible.
    historical = (
        benchmark_observation_from_bundle(
            _bundle(
                session
            )
        )
    )

    assert (
        historical.duration_seconds
        == 10.0
    )


def test_measured_aggregate_keeps_failed_run_without_backend_timing(
    tmp_path,
) -> None:
    from nodrix.benchmark_runs import (
        aggregate_measured_canonical_benchmark_runs,
    )

    root = (
        tmp_path
        / "runs"
    )

    system = SystemModel(
        name="benchmark-failed-timing"
    )

    plan = plan_canonical_system(
        system
    )

    successful = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_measured-success",
        execution_id="execution-success",
        # Deliberately different lifecycle duration.
        duration=100.0,
        execution_details={
            "execution_timing": {
                "source": "backend",
                "target": "host",
                "backend": "local",
                "execution_id": "backend-success",
                "duration_seconds": 3.5,
            },
        },
    )

    failed = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_measured-failed",
        execution_id="execution-failed",
        duration=50.0,
        successful=False,
        # A backend may fail before exact timing becomes available.
        execution_details={},
    )

    result = (
        aggregate_measured_canonical_benchmark_runs(
            (
                _bundle(
                    successful
                ),
                _bundle(
                    failed
                ),
            )
        )
    )

    assert (
        result.aggregate.failed_run_ids
        == (
            "run_measured-failed",
        )
    )

    # Only the successful Run is a performance duration sample.
    # Its lifecycle duration was 100 s, but exact backend timing was 3.5 s.
    assert (
        result.aggregate.duration.mean
        == 3.5
    )

    assert (
        result.aggregate.execution_complete
        is False
    )


def test_measured_aggregate_rejects_successful_run_without_backend_timing(
    tmp_path,
) -> None:
    from nodrix.benchmark_runs import (
        aggregate_measured_canonical_benchmark_runs,
    )

    system = SystemModel(
        name="benchmark-success-timing-required"
    )

    plan = plan_canonical_system(
        system
    )

    session = _create_run(
        tmp_path / "runs",
        system=system,
        plan=plan,
        run_id="run_success-no-timing",
        execution_id="execution-success-no-timing",
        duration=10.0,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "does not contain exact backend "
            "execution timing"
        ),
    ):
        aggregate_measured_canonical_benchmark_runs(
            (
                _bundle(
                    session
                ),
            )
        )
