from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)
import json

import pytest
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.model import (
    ExecutionRecord,
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
from nodrix.runs import (
    CanonicalRunComparisonUnavailableError,
    RunComparisonCompatibilityError,
    compare_runs,
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


runner = CliRunner()

STARTED = datetime(
    2026,
    8,
    20,
    10,
    0,
    tzinfo=timezone.utc,
)


def _runs_root(
    project,
):
    return (
        project
        / ".nodrix"
        / "runs"
    )


def _canonical_run(
    project,
    *,
    run_id: str,
    execution_id: str,
    duration_seconds: float = 10.0,
):
    root = _runs_root(
        project
    )

    system = SystemModel(
        name="runs-compare"
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
                    seconds=duration_seconds
                )
            ),
        )
    )

    return session


def _legacy_run(
    project,
    *,
    run_id: str,
    duration_seconds: float,
) -> None:
    directory = (
        _runs_root(
            project
        )
        / run_id
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        directory
        / "summary.json"
    ).write_text(
        json.dumps(
            {
                "run_dir": str(
                    directory
                ),
                "pipeline": "legacy",
                "status": "completed",
                "duration_seconds": (
                    duration_seconds
                ),
                "nodes": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _report_only_canonical(
    project,
    *,
    run_id: str,
) -> None:
    directory = (
        _runs_root(
            project
        )
        / run_id
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        directory
        / "run.json"
    ).write_text(
        json.dumps(
            {
                "schema": (
                    "nodrix.run/v1"
                ),
                "kind": "Run",
                "id": run_id,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_compare_runs_dispatches_persisted_canonical_history(
    tmp_path,
) -> None:
    _canonical_run(
        tmp_path,
        run_id="run_compare_a",
        execution_id="execution-a",
        duration_seconds=10.0,
    )

    _canonical_run(
        tmp_path,
        run_id="run_compare_b",
        execution_id="execution-b",
        duration_seconds=12.0,
    )

    comparison = compare_runs(
        "run_compare_a",
        "run_compare_b",
        tmp_path,
    )

    assert (
        comparison[
            "evidence"
        ][
            "sameExactWorkload"
        ]
        is True
    )

    assert (
        comparison[
            "outcome"
        ][
            "durationDeltaSeconds"
        ]
        == 2.0
    )

    assert (
        comparison[
            "metrics"
        ][
            "descriptors"
        ]
        == []
    )


def test_canonical_session_wins_over_legacy_summary_during_compare(
    tmp_path,
) -> None:
    first = _canonical_run(
        tmp_path,
        run_id="run_summary_shadow_a",
        execution_id="execution-a",
    )

    _canonical_run(
        tmp_path,
        run_id="run_summary_shadow_b",
        execution_id="execution-b",
    )

    (
        first.directory
        / "summary.json"
    ).write_text(
        json.dumps(
            {
                "pipeline": "must-not-shadow",
                "duration_seconds": 9999,
            }
        ),
        encoding="utf-8",
    )

    comparison = compare_runs(
        "run_summary_shadow_a",
        "run_summary_shadow_b",
        tmp_path,
    )

    assert (
        comparison[
            "first"
        ][
            "runId"
        ]
        == "run_summary_shadow_a"
    )

    assert (
        "duration_seconds_delta"
        not in comparison
    )


def test_compare_runs_preserves_legacy_contract(
    tmp_path,
) -> None:
    _legacy_run(
        tmp_path,
        run_id="legacy-a",
        duration_seconds=10.0,
    )

    _legacy_run(
        tmp_path,
        run_id="legacy-b",
        duration_seconds=12.0,
    )

    comparison = compare_runs(
        "legacy-a",
        "legacy-b",
        tmp_path,
    )

    assert set(
        comparison
    ) == {
        "first",
        "second",
        "duration_seconds_delta",
        "nodes",
        "metrics",
    }

    assert (
        comparison[
            "duration_seconds_delta"
        ]
        == 2.0
    )

    assert (
        "duration_seconds"
        in comparison[
            "metrics"
        ]
    )


def test_compare_runs_rejects_canonical_legacy_mixing(
    tmp_path,
) -> None:
    _canonical_run(
        tmp_path,
        run_id="run_mixed",
        execution_id="execution-a",
    )

    _legacy_run(
        tmp_path,
        run_id="legacy-mixed",
        duration_seconds=10.0,
    )

    with pytest.raises(
        RunComparisonCompatibilityError,
        match=(
            "cannot compare canonical "
            "and legacy Runs"
        ),
    ):
        compare_runs(
            "run_mixed",
            "legacy-mixed",
            tmp_path,
        )


def test_report_only_canonical_history_fails_explicitly(
    tmp_path,
) -> None:
    _report_only_canonical(
        tmp_path,
        run_id="run-report-a",
    )

    _report_only_canonical(
        tmp_path,
        run_id="run-report-b",
    )

    with pytest.raises(
        CanonicalRunComparisonUnavailableError,
        match="report-only canonical history",
    ):
        compare_runs(
            "run-report-a",
            "run-report-b",
            tmp_path,
        )


def test_runs_compare_cli_emits_canonical_json(
    tmp_path,
) -> None:
    _canonical_run(
        tmp_path,
        run_id="run_cli_a",
        execution_id="execution-a",
    )

    _canonical_run(
        tmp_path,
        run_id="run_cli_b",
        execution_id="execution-b",
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "compare",
            "run_cli_a",
            "run_cli_b",
            "--project",
            str(
                tmp_path
            ),
        ],
    )

    assert (
        result.exit_code
        == 0
    )

    document = json.loads(
        result.stdout
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
        "descriptors"
        in document[
            "metrics"
        ]
    )


def test_runs_compare_cli_table_handles_canonical_without_metrics(
    tmp_path,
) -> None:
    _canonical_run(
        tmp_path,
        run_id="run_table_a",
        execution_id="execution-a",
    )

    _canonical_run(
        tmp_path,
        run_id="run_table_b",
        execution_id="execution-b",
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "compare",
            "run_table_a",
            "run_table_b",
            "--project",
            str(
                tmp_path
            ),
            "--table",
        ],
    )

    assert (
        result.exit_code
        == 0
    )

    assert (
        "COMPARE"
        in result.stdout
    )

    assert (
        "Exact workload"
        in result.stdout
    )

    assert (
        "No canonical Metric observations."
        in result.stdout
    )


def test_runs_compare_cli_keeps_legacy_table(
    tmp_path,
) -> None:
    _legacy_run(
        tmp_path,
        run_id="legacy-table-a",
        duration_seconds=10.0,
    )

    _legacy_run(
        tmp_path,
        run_id="legacy-table-b",
        duration_seconds=12.0,
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "compare",
            "legacy-table-a",
            "legacy-table-b",
            "--project",
            str(
                tmp_path
            ),
            "--table",
        ],
    )

    assert (
        result.exit_code
        == 0
    )

    assert (
        "duration_seconds"
        in result.stdout
    )


def test_runs_compare_cli_surfaces_mixed_model_error(
    tmp_path,
) -> None:
    _canonical_run(
        tmp_path,
        run_id="run_cli_mixed",
        execution_id="execution-a",
    )

    _legacy_run(
        tmp_path,
        run_id="legacy-cli-mixed",
        duration_seconds=10.0,
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "compare",
            "run_cli_mixed",
            "legacy-cli-mixed",
            "--project",
            str(
                tmp_path
            ),
        ],
    )

    assert (
        result.exit_code
        == 1
    )

    assert (
        "Cannot compare runs"
        in result.stdout
    )

    assert (
        "canonical and legacy"
        in result.stdout
    )
