from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from nodrix.benchmark_measured_runs import (
    CanonicalMeasuredRunContractError,
    execute_canonical_benchmark_runs,
)
from nodrix.benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.model import (
    ExecutionRecord,
)
from nodrix.run_bundle import (
    load_canonical_run_bundle,
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
    19,
    0,
    tzinfo=timezone.utc,
)


def _plan(
    tmp_path,
    *,
    repeat: int = 2,
    warmup: int = 1,
    variants=(
        BenchmarkVariant(
            "fast"
        ),
    ),
) -> BenchmarkPlan:
    pipeline = (
        tmp_path
        / "pipeline.yaml"
    )

    pipeline.write_text(
        "name: measured-runs\n",
        encoding="utf-8",
    )

    return BenchmarkPlan(
        pipeline=pipeline,
        repeat=repeat,
        warmup=warmup,
        variants=variants,
    )


def _bundle(
    root,
    *,
    run_id: str,
    execution_id: str,
    system_name: str,
):
    system = SystemModel(
        name=system_name
    )

    plan = (
        plan_canonical_system(
            system
        )
    )

    session = RunStore(
        root,
        clock=lambda: STARTED,
    ).create(
        plan,
        run_id=run_id,
    )

    snapshots = (
        RunSnapshotStore(
            session
        )
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
        policy=ExecutionPolicy(),
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
            state="completed",
            started_at=STARTED,
            finished_at=(
                STARTED
                + timedelta(
                    seconds=1
                )
            ),
        )
    )

    return (
        load_canonical_run_bundle(
            session.directory
        )
    )


def test_coordinator_executes_warmup_and_measured_runs_in_order(
    tmp_path,
) -> None:
    plan = _plan(
        tmp_path,
        repeat=2,
        warmup=1,
        variants=(
            BenchmarkVariant(
                "fast"
            ),
            BenchmarkVariant(
                "accurate"
            ),
        ),
    )

    requests = []

    def execute(
        request,
    ):
        requests.append(
            (
                request.variant.name,
                request.phase,
                request.iteration,
            )
        )

        run_id = (
            "run_"
            + request.variant.name
            + "-"
            + request.phase
            + "-"
            + str(
                request.iteration
            )
        )

        return _bundle(
            tmp_path / "runs",
            run_id=run_id,
            execution_id=(
                "execution-"
                + request.variant.name
                + "-"
                + request.phase
                + "-"
                + str(
                    request.iteration
                )
            ),
            system_name=(
                request.variant.name
                + "-workload"
            ),
        )

    result = (
        execute_canonical_benchmark_runs(
            plan,
            run_callable=execute,
        )
    )

    assert requests == [
        (
            "fast",
            "warmup",
            0,
        ),
        (
            "fast",
            "measured",
            0,
        ),
        (
            "fast",
            "measured",
            1,
        ),
        (
            "accurate",
            "warmup",
            0,
        ),
        (
            "accurate",
            "measured",
            0,
        ),
        (
            "accurate",
            "measured",
            1,
        ),
    ]

    assert (
        result.warmup_run_ids
        == (
            "run_fast-warmup-0",
            "run_accurate-warmup-0",
        )
    )

    assert (
        result.measured_run_ids
        == (
            "run_fast-measured-0",
            "run_fast-measured-1",
            "run_accurate-measured-0",
            "run_accurate-measured-1",
        )
    )


def test_measured_runs_projection_excludes_warmups(
    tmp_path,
) -> None:
    plan = _plan(
        tmp_path,
        repeat=2,
        warmup=1,
    )

    def execute(
        request,
    ):
        return _bundle(
            tmp_path / "runs",
            run_id=(
                "run_"
                + request.phase
                + "-"
                + str(
                    request.iteration
                )
            ),
            execution_id=(
                "execution-"
                + request.phase
                + "-"
                + str(
                    request.iteration
                )
            ),
            system_name=(
                "strict-workload"
            ),
        )

    result = (
        execute_canonical_benchmark_runs(
            plan,
            run_callable=execute,
        )
    )

    assert (
        tuple(
            bundle.session.run_id
            for bundle
            in result.measured_runs[
                "fast"
            ]
        )
        == (
            "run_measured-0",
            "run_measured-1",
        )
    )

    assert (
        "run_warmup-0"
        not in result.measured_run_ids
    )


def test_zero_warmup_executes_only_measured_runs(
    tmp_path,
) -> None:
    plan = _plan(
        tmp_path,
        repeat=2,
        warmup=0,
    )

    phases = []

    def execute(
        request,
    ):
        phases.append(
            request.phase
        )

        return _bundle(
            tmp_path / "runs",
            run_id=(
                "run_measured-"
                + str(
                    request.iteration
                )
            ),
            execution_id=(
                "execution-measured-"
                + str(
                    request.iteration
                )
            ),
            system_name=(
                "strict-workload"
            ),
        )

    result = (
        execute_canonical_benchmark_runs(
            plan,
            run_callable=execute,
        )
    )

    assert phases == [
        "measured",
        "measured",
    ]

    assert (
        result.warmup_run_ids
        == ()
    )


def test_noncanonical_return_value_is_rejected(
    tmp_path,
) -> None:
    plan = _plan(
        tmp_path,
        repeat=1,
        warmup=0,
    )

    with pytest.raises(
        CanonicalMeasuredRunContractError,
        match="CanonicalRunBundle",
    ):
        execute_canonical_benchmark_runs(
            plan,
            run_callable=(
                lambda request: {
                    "run_dir": (
                        "/legacy/run"
                    ),
                    "request": request,
                }
            ),
        )


def test_same_run_identity_cannot_be_reused(
    tmp_path,
) -> None:
    plan = _plan(
        tmp_path,
        repeat=2,
        warmup=0,
    )

    bundle = _bundle(
        tmp_path / "runs",
        run_id="run_shared",
        execution_id="execution-shared",
        system_name="strict-workload",
    )

    with pytest.raises(
        CanonicalMeasuredRunContractError,
        match="reused Run identity",
    ):
        execute_canonical_benchmark_runs(
            plan,
            run_callable=(
                lambda request: bundle
            ),
        )
