import json

from nodrix.runs import (
    is_canonical_run_report,
    list_runs,
    load_run,
)


def write_json(path, document) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(document),
        encoding="utf-8",
    )


def canonical_document(
    *,
    run_id: str = "run-canonical",
):
    return {
        "schema": "nodrix.run/v1",
        "kind": "Run",
        "id": run_id,
        "ref": (
            f"nodrix://record/run/{run_id}"
        ),
        "status": "completed",
        "successful": True,
        "duration_seconds": 12.5,
        "subject": {
            "entity": (
                "nodrix://system/project/mapping"
            ),
            "revision": (
                "nodrix://system/project/mapping"
                "@sha256:"
                + "a" * 64
            ),
        },
        "operation": {
            "kind": "run",
            "parameters": {},
        },
        "plan": {
            "id": "plan-001",
            "ref": (
                "nodrix://record/plan/plan-001"
            ),
            "kind": "system-execution",
            "metadata": {},
        },
        "execution": {
            "id": "execution-001",
            "ref": (
                "nodrix://record/execution/"
                "execution-001"
            ),
            "executor": (
                "nodrix.system.orchestrator"
            ),
            "state": "completed",
            "started_at": (
                "2026-08-15T20:00:00Z"
            ),
            "finished_at": (
                "2026-08-15T20:00:12.500000Z"
            ),
            "details": {},
        },
        "summary": {},
        "metadata": {},
        "relations": [],
    }


def test_detects_canonical_run_report() -> None:
    assert is_canonical_run_report(
        canonical_document()
    )


def test_legacy_report_is_not_canonical() -> None:
    assert not is_canonical_run_report(
        {
            "id": "legacy-run",
            "pipeline": "demo",
            "status": "completed",
        }
    )


def test_list_runs_exposes_canonical_identity(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / ".nodrix"
        / "runs"
        / "run-canonical"
    )

    write_json(
        root / "run.json",
        canonical_document(),
    )

    items = list_runs(
        tmp_path
    )

    assert len(items) == 1

    item = items[0]

    assert item["id"] == "run-canonical"
    assert item["canonical"] is True
    assert item["schema"] == "nodrix.run/v1"

    assert item["subject"] == (
        "nodrix://system/project/mapping"
    )

    assert item["operation"] == "run"
    assert item["status"] == "completed"
    assert item["duration_seconds"] == 12.5

    assert item["pipeline"] is None


def test_list_runs_keeps_legacy_shape_compatible(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / ".nodrix"
        / "runs"
        / "legacy-run"
    )

    write_json(
        root / "summary.json",
        {
            "pipeline": "demo-pipeline",
            "status": "completed",
            "duration_seconds": 5.0,
        },
    )

    items = list_runs(
        tmp_path
    )

    assert len(items) == 1

    item = items[0]

    assert item["id"] == "legacy-run"
    assert item["pipeline"] == "demo-pipeline"
    assert item["status"] == "completed"

    assert item["canonical"] is False
    assert item["schema"] is None
    assert item["subject"] is None
    assert item["operation"] is None


def test_legacy_and_canonical_runs_can_coexist(
    tmp_path,
) -> None:
    runs = (
        tmp_path
        / ".nodrix"
        / "runs"
    )

    write_json(
        runs
        / "legacy-run"
        / "summary.json",
        {
            "pipeline": "legacy",
            "status": "completed",
        },
    )

    write_json(
        runs
        / "canonical-run"
        / "run.json",
        canonical_document(
            run_id="canonical-run",
        ),
    )

    items = list_runs(
        tmp_path
    )

    by_id = {
        item["id"]: item
        for item in items
    }

    assert set(by_id) == {
        "legacy-run",
        "canonical-run",
    }

    assert (
        by_id["legacy-run"]["canonical"]
        is False
    )

    assert (
        by_id["canonical-run"]["canonical"]
        is True
    )


def test_load_run_remains_raw_compatibility_api(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / ".nodrix"
        / "runs"
        / "run-canonical"
    )

    document = canonical_document()

    write_json(
        root / "run.json",
        document,
    )

    loaded = load_run(
        "run-canonical",
        project=tmp_path,
    )

    assert loaded == document


def test_summary_json_remains_authoritative_for_legacy_run(
    tmp_path,
) -> None:
    root = (
        tmp_path
        / ".nodrix"
        / "runs"
        / "legacy-run"
    )

    write_json(
        root / "summary.json",
        {
            "pipeline": "legacy-summary",
            "status": "completed",
        },
    )

    write_json(
        root / "run.json",
        {
            "pipeline": "legacy-run-json",
            "status": "failed",
        },
    )

    loaded = load_run(
        "legacy-run",
        project=tmp_path,
    )

    assert loaded["pipeline"] == "legacy-summary"
    assert loaded["status"] == "completed"
