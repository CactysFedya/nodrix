from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)
import json

import pytest

from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.model import (
    ExecutionRecord,
)
from nodrix.observability_profiles import (
    resolve_observability_profile,
)
from nodrix.run_bundle import (
    load_canonical_run_bundle,
)
from nodrix.run_comparison import (
    CanonicalRunBundleComparison,
    compare_canonical_run_bundles,
)
from nodrix.run_policy import (
    RUN_POLICY_V1_API_VERSION,
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
    19,
    13,
    0,
    tzinfo=timezone.utc,
)


def _definition(
    *,
    description: str | None = None,
) -> SystemModel:
    return SystemModel(
        name="comparison-system",
        description=description,
    )


def _create_run(
    root,
    *,
    system: SystemModel,
    plan,
    run_id: str,
    execution_id: str,
    duration_seconds: float = 10.0,
    state: str = "completed",
    policy: ExecutionPolicy | None = None,
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

    execution = ExecutionRecord(
        execution_id=execution_id,
        plan=plan,
        executor=(
            "nodrix.system.orchestrator"
        ),
        state=state,
        started_at=STARTED,
        finished_at=(
            STARTED
            + timedelta(
                seconds=duration_seconds
            )
        ),
    )

    RunRecordStore(
        session
    ).create(
        execution
    )

    return session


def test_persisted_repeated_runs_are_same_exact_workload(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    system = _definition()
    plan = plan_canonical_system(
        system
    )

    first_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_compare_a",
        execution_id="execution-a",
        duration_seconds=10.0,
    )

    second_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_compare_b",
        execution_id="execution-b",
        duration_seconds=12.0,
    )

    comparison = (
        compare_canonical_run_bundles(
            load_canonical_run_bundle(
                first_session.directory
            ),
            load_canonical_run_bundle(
                second_session.directory
            ),
        )
    )

    assert isinstance(
        comparison,
        CanonicalRunBundleComparison,
    )

    assert (
        comparison.runs.first.run_id
        != comparison.runs.second.run_id
    )

    assert (
        comparison.runs.first.execution_id
        != comparison.runs.second.execution_id
    )

    assert (
        comparison.runs.provenance.same_plan
        is True
    )

    assert (
        comparison.evidence.same_definition
        is True
    )

    assert (
        comparison.evidence.same_plan_snapshot
        is True
    )

    assert (
        comparison.evidence.same_effective_policy
        is True
    )

    assert (
        comparison.same_exact_workload
        is True
    )

    assert (
        comparison.runs.outcome.duration_delta_seconds
        == 2.0
    )

    assert (
        comparison.runs.outcome.duration_percent
        == 20.0
    )


def test_same_workload_can_have_different_execution_policy(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    system = _definition()
    plan = plan_canonical_system(
        system
    )

    first_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy_a",
        execution_id="execution-a",
        policy=ExecutionPolicy(),
    )

    second_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy_b",
        execution_id="execution-b",
        policy=(
            resolve_observability_profile(
                "debug"
            )
        ),
    )

    comparison = (
        compare_canonical_run_bundles(
            load_canonical_run_bundle(
                first_session.directory
            ),
            load_canonical_run_bundle(
                second_session.directory
            ),
        )
    )

    assert (
        comparison.same_exact_workload
        is True
    )

    assert (
        comparison.runs.provenance.same_plan
        is True
    )

    assert (
        comparison.evidence.policy_comparable
        is True
    )

    assert (
        comparison.evidence.same_effective_policy
        is False
    )


def test_missing_historical_policy_is_explicitly_not_comparable(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    system = _definition()
    plan = plan_canonical_system(
        system
    )

    first_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy_legacy",
        execution_id="execution-a",
    )

    second_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy_current",
        execution_id="execution-b",
    )

    session_document = json.loads(
        first_session.session_path.read_text(
            encoding="utf-8"
        )
    )

    session_document[
        "layout"
    ] = RUN_LAYOUT_SCHEMA_V1

    first_session.session_path.write_text(
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
        first_session.directory
        / "policy.json"
    ).unlink()

    comparison = (
        compare_canonical_run_bundles(
            load_canonical_run_bundle(
                first_session.directory
            ),
            load_canonical_run_bundle(
                second_session.directory
            ),
        )
    )

    assert (
        comparison.same_exact_workload
        is True
    )

    assert (
        comparison.evidence.first_policy_available
        is False
    )

    assert (
        comparison.evidence.second_policy_available
        is True
    )

    assert (
        comparison.evidence.policy_comparable
        is False
    )

    assert (
        comparison.evidence.same_effective_policy
        is None
    )


def test_policy_v1_and_v2_compare_by_effective_semantics(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    system = _definition()
    plan = plan_canonical_system(
        system
    )

    first_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy_v1",
        execution_id="execution-a",
    )

    second_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_policy_v2",
        execution_id="execution-b",
    )

    path = (
        first_session.directory
        / "policy.json"
    )

    document = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    document[
        "apiVersion"
    ] = RUN_POLICY_V1_API_VERSION

    document.pop(
        "metrics"
    )

    path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    comparison = (
        compare_canonical_run_bundles(
            load_canonical_run_bundle(
                first_session.directory
            ),
            load_canonical_run_bundle(
                second_session.directory
            ),
        )
    )

    assert (
        comparison.evidence.policy_comparable
        is True
    )

    assert (
        comparison.evidence.same_effective_policy
        is True
    )


def test_definition_and_plan_change_break_exact_workload_identity(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    first_system = _definition(
        description="first"
    )

    second_system = _definition(
        description="second"
    )

    first_plan = (
        plan_canonical_system(
            first_system
        )
    )

    second_plan = (
        plan_canonical_system(
            second_system
        )
    )

    first_session = _create_run(
        root,
        system=first_system,
        plan=first_plan,
        run_id="run_definition_a",
        execution_id="execution-a",
    )

    second_session = _create_run(
        root,
        system=second_system,
        plan=second_plan,
        run_id="run_definition_b",
        execution_id="execution-b",
    )

    comparison = (
        compare_canonical_run_bundles(
            load_canonical_run_bundle(
                first_session.directory
            ),
            load_canonical_run_bundle(
                second_session.directory
            ),
        )
    )

    assert (
        comparison.evidence.same_definition
        is False
    )

    assert (
        comparison.evidence.same_plan_snapshot
        is False
    )

    assert (
        comparison.same_exact_workload
        is False
    )


def test_persisted_comparison_document_is_deterministic(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    system = _definition()
    plan = plan_canonical_system(
        system
    )

    first_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_document_a",
        execution_id="execution-a",
    )

    second_session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_document_b",
        execution_id="execution-b",
    )

    first = (
        load_canonical_run_bundle(
            first_session.directory
        )
    )

    second = (
        load_canonical_run_bundle(
            second_session.directory
        )
    )

    left = (
        compare_canonical_run_bundles(
            first,
            second,
        )
    )

    right = (
        compare_canonical_run_bundles(
            first,
            second,
        )
    )

    assert left == right

    document = left.to_dict()

    assert set(document) == {
        "first",
        "second",
        "provenance",
        "outcome",
        "evidence",
        "metrics",
    }

    assert (
        document[
            "metrics"
        ][
            "descriptors"
        ]
        == []
    )

    assert (
        document[
            "metrics"
        ][
            "complete"
        ]
        is True
    )

    assert (
        document[
            "evidence"
        ][
            "sameExactWorkload"
        ]
        is True
    )

    assert (
        document[
            "evidence"
        ][
            "samePolicy"
        ]
        is True
    )


@pytest.mark.parametrize(
    "position",
    (
        "first",
        "second",
    ),
)
def test_bundle_comparison_requires_canonical_bundles(
    tmp_path,
    position,
) -> None:
    root = (
        tmp_path
        / "runs"
    )

    system = _definition()
    plan = plan_canonical_system(
        system
    )

    session = _create_run(
        root,
        system=system,
        plan=plan,
        run_id="run_type_check",
        execution_id="execution-a",
    )

    bundle = (
        load_canonical_run_bundle(
            session.directory
        )
    )

    with pytest.raises(
        TypeError,
        match=(
            "first must be a CanonicalRunBundle"
            if position == "first"
            else "second must be a CanonicalRunBundle"
        ),
    ):
        if position == "first":
            compare_canonical_run_bundles(
                {},  # type: ignore[arg-type]
                bundle,
            )
        else:
            compare_canonical_run_bundles(
                bundle,
                {},  # type: ignore[arg-type]
            )
