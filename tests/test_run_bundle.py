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
from nodrix.run_bundle import (
    CanonicalRunBundleIncompleteError,
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
    system_definition_snapshot,
    system_plan_snapshot,
)


STARTED = datetime(
    2026,
    8,
    19,
    12,
    0,
    tzinfo=timezone.utc,
)


def _complete_run(
    tmp_path,
    *,
    run_id="run_bundle",
):
    system = SystemModel(
        name="bundle-system"
    )

    plan = plan_canonical_system(
        system
    )

    store = RunStore(
        tmp_path
        / "runs",
        clock=lambda: STARTED,
    )

    session = store.create(
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
        policy=ExecutionPolicy(),
    ).create()

    execution = ExecutionRecord(
        execution_id="execution-bundle",
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

    return session


def test_load_canonical_run_bundle_reads_validated_evidence(
    tmp_path,
) -> None:
    session = _complete_run(
        tmp_path
    )

    bundle = (
        load_canonical_run_bundle(
            session.directory
        )
    )

    assert (
        bundle.run_id
        == session.run_id
    )

    assert (
        bundle.plan_id
        == session.plan_id
    )

    assert (
        bundle.run["runId"]
        == session.run_id
    )

    assert (
        bundle.definition[
            "content"
        ][
            "revision"
        ]
        == session.subject_revision
    )

    assert (
        bundle.plan[
            "content"
        ][
            "planId"
        ]
        == session.plan_id
    )

    assert bundle.policy is not None

    assert (
        bundle.policy[
            "runId"
        ]
        == session.run_id
    )


def test_canonical_run_bundle_is_deeply_read_only(
    tmp_path,
) -> None:
    session = _complete_run(
        tmp_path
    )

    bundle = (
        load_canonical_run_bundle(
            session.directory
        )
    )

    with pytest.raises(
        TypeError,
    ):
        bundle.plan[
            "content"
        ][
            "planId"
        ] = "changed"  # type: ignore[index]


def test_layout_v2_requires_policy_provenance(
    tmp_path,
) -> None:
    session = _complete_run(
        tmp_path
    )

    (
        session.directory
        / "policy.json"
    ).unlink()

    with pytest.raises(
        CanonicalRunBundleIncompleteError,
        match="layout v2.*policy.json",
    ):
        load_canonical_run_bundle(
            session.directory
        )


def test_historical_layout_v1_can_explicitly_have_no_policy(
    tmp_path,
) -> None:
    session = _complete_run(
        tmp_path
    )

    document = json.loads(
        session.session_path.read_text(
            encoding="utf-8"
        )
    )

    document["layout"] = (
        "nodrix.run-layout/v1"
    )

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

    (
        session.directory
        / "policy.json"
    ).unlink()

    bundle = (
        load_canonical_run_bundle(
            session.directory
        )
    )

    assert (
        bundle.session.layout
        == "nodrix.run-layout/v1"
    )

    assert (
        bundle.policy
        is None
    )

    assert (
        bundle.policy_available
        is False
    )


def test_bundle_requires_final_run_record(
    tmp_path,
) -> None:
    session = _complete_run(
        tmp_path
    )

    (
        session.directory
        / "run.json"
    ).unlink()

    with pytest.raises(
        CanonicalRunBundleIncompleteError,
        match="run.json",
    ):
        load_canonical_run_bundle(
            session.directory
        )


def test_bundle_requires_definition_snapshot(
    tmp_path,
) -> None:
    session = _complete_run(
        tmp_path
    )

    (
        session.directory
        / "definition.json"
    ).unlink()

    with pytest.raises(
        CanonicalRunBundleIncompleteError,
        match="definition.json",
    ):
        load_canonical_run_bundle(
            session.directory
        )


def test_bundle_requires_plan_snapshot(
    tmp_path,
) -> None:
    session = _complete_run(
        tmp_path
    )

    (
        session.directory
        / "plan.json"
    ).unlink()

    with pytest.raises(
        CanonicalRunBundleIncompleteError,
        match="plan.json",
    ):
        load_canonical_run_bundle(
            session.directory
        )


def test_bundle_propagates_snapshot_identity_corruption(
    tmp_path,
) -> None:
    session = _complete_run(
        tmp_path
    )

    path = (
        session.directory
        / "plan.json"
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
        json.dumps(
            document
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunSnapshotCorruptionError,
        match="different Run",
    ):
        load_canonical_run_bundle(
            session.directory
        )
