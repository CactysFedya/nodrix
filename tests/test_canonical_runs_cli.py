from __future__ import annotations

import json

from typer.testing import CliRunner

from nodrix.cli import app


runner = CliRunner()


def write_json(path, document) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(document),
        encoding="utf-8",
    )


def canonical_run():
    return {
        "schema": "nodrix.run/v1",
        "kind": "Run",
        "id": "run-001",
        "ref": "nodrix://record/run/run-001",
        "status": "completed",
        "successful": True,
        "duration_seconds": 30.0,
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
            "ref": "nodrix://record/plan/plan-001",
            "kind": "system-execution",
            "metadata": {},
        },
        "execution": {
            "id": "execution-001",
            "ref": (
                "nodrix://record/execution/"
                "execution-001"
            ),
            "executor": "nodrix.system.orchestrator",
            "state": "completed",
            "started_at": "2026-08-15T20:00:00Z",
            "finished_at": "2026-08-15T20:00:30Z",
            "details": {},
        },
        "summary": {},
        "metadata": {},
        "relations": [],
    }


def prepare_mixed_runs(tmp_path) -> None:
    root = (
        tmp_path
        / ".nodrix"
        / "runs"
    )

    write_json(
        root
        / "run-001"
        / "run.json",
        canonical_run(),
    )

    write_json(
        root
        / "legacy-001"
        / "summary.json",
        {
            "pipeline": "old-yolo",
            "status": "completed",
            "duration_seconds": 10.0,
        },
    )


def test_runs_list_shows_canonical_subject_and_operation(
    tmp_path,
) -> None:
    prepare_mixed_runs(
        tmp_path
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "list",
            "--project",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0

    output = result.stdout

    assert "Operation" in output
    assert "Subject / Pipeline" in output

    assert "run-001" in output
    assert "run" in output
    assert "system/project/mapping" in output

    assert "legacy-001" in output
    assert "old-yolo" in output
    assert "completed" in output


def test_runs_list_does_not_show_uri_prefix_in_subject(
    tmp_path,
) -> None:
    prepare_mixed_runs(
        tmp_path
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "list",
            "--project",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "nodrix://" not in result.stdout


def test_runs_list_json_preserves_machine_readable_identity(
    tmp_path,
) -> None:
    prepare_mixed_runs(
        tmp_path
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "list",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0

    data = json.loads(
        result.stdout
    )

    by_id = {
        item["id"]: item
        for item in data
    }

    canonical = by_id[
        "run-001"
    ]

    assert canonical["canonical"] is True
    assert canonical["operation"] == "run"

    assert canonical["subject"] == (
        "nodrix://system/project/mapping"
    )

    legacy = by_id[
        "legacy-001"
    ]

    assert legacy["canonical"] is False
    assert legacy["pipeline"] == "old-yolo"
    assert legacy["subject"] is None


def test_runs_list_empty_storage_is_valid(
    tmp_path,
) -> None:
    result = runner.invoke(
        app,
        [
            "runs",
            "list",
            "--project",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "Operation" in result.stdout
    assert "Subject / Pipeline" in result.stdout


def test_runs_list_is_borderless(
    tmp_path,
) -> None:
    prepare_mixed_runs(tmp_path)

    result = runner.invoke(
        app,
        [
            "runs",
            "list",
            "--project",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0

    border_chars = (
        "┏┓┗┛┃"
        "╭╮╰╯"
        "┌┐└┘│"
        "━─"
        "┡┩"
    )

    assert not any(
        char in result.stdout
        for char in border_chars
    )


def test_runs_show_canonical_is_compact_and_borderless(
    tmp_path,
) -> None:
    document = canonical_run()

    document["relations"] = [
        {
            "source": "nodrix://record/plan/plan-001",
            "kind": "executed_as",
            "target": (
                "nodrix://record/execution/"
                "execution-001"
            ),
            "metadata": {},
        },
        {
            "source": (
                "nodrix://record/execution/"
                "execution-001"
            ),
            "kind": "recorded_as",
            "target": "nodrix://record/run/run-001",
            "metadata": {},
        },
        {
            "source": "nodrix://record/run/run-001",
            "kind": "consumes",
            "target": (
                "nodrix://dataset/project/livox-session"
                "@sha256:"
                + "b" * 64
            ),
            "metadata": {},
        },
        {
            "source": "nodrix://record/run/run-001",
            "kind": "produces",
            "target": (
                "nodrix://artifact/project/global-map"
                "@sha256:"
                + "c" * 64
            ),
            "metadata": {},
        },
    ]

    write_json(
        (
            tmp_path
            / ".nodrix"
            / "runs"
            / "run-001"
            / "run.json"
        ),
        document,
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "show",
            "run-001",
            "--project",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0

    output = result.stdout

    assert "RUN" in output
    assert "run-001" in output
    assert "COMPLETED" in output

    assert "system/project/mapping" in output
    assert "Operation" in output
    assert "run" in output

    assert "plan-001" in output
    assert "execution-001" in output
    assert "nodrix.system.orchestrator" in output

    assert "PROVENANCE" in output
    assert "consumes" in output
    assert "dataset/project/livox-session" in output
    assert "produces" in output
    assert "artifact/project/global-map" in output

    assert "nodrix://" not in output

    border_chars = (
        "┏┓┗┛┃"
        "╭╮╰╯"
        "┌┐└┘│"
        "━─"
        "┡┩"
    )

    assert not any(
        char in output
        for char in border_chars
    )


def test_runs_show_canonical_json_preserves_document(
    tmp_path,
) -> None:
    document = canonical_run()

    write_json(
        (
            tmp_path
            / ".nodrix"
            / "runs"
            / "run-001"
            / "run.json"
        ),
        document,
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "show",
            "run-001",
            "--project",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0

    loaded = json.loads(
        result.stdout
    )

    assert loaded == document
    assert loaded["schema"] == "nodrix.run/v1"


def test_runs_show_legacy_keeps_json_output(
    tmp_path,
) -> None:
    document = {
        "pipeline": "old-yolo",
        "status": "completed",
        "duration_seconds": 10.0,
    }

    write_json(
        (
            tmp_path
            / ".nodrix"
            / "runs"
            / "legacy-001"
            / "summary.json"
        ),
        document,
    )

    result = runner.invoke(
        app,
        [
            "runs",
            "show",
            "legacy-001",
            "--project",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0

    loaded = json.loads(
        result.stdout
    )

    assert loaded == document
