from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.model import ExecutionState
from nodrix.project_canonical import (
    project_definition_digest,
    project_entity_ref,
)
from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
)
from nodrix.workflow_operation import (
    WORKFLOW_RUN_OPERATION,
    execute_workflow_operation,
)


runner = CliRunner()


def _build_project(
    root: Path,
    *,
    command: str,
) -> None:
    create_progressive_project(root)

    workflow = add_project_resource(
        "workflow",
        "build",
        root=root,
    )

    workflow.path.write_text(
        "schema: nodrix.workflow/v1\n"
        "name: build\n"
        "steps:\n"
        "  - id: compile\n"
        "    run: |\n"
        f"      {command}\n",
        encoding="utf-8",
    )


def test_project_definition_identity_is_location_independent(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first.mkdir()
    second.mkdir()

    document = {
        "schema": "nodrix.project/v1",
        "name": "mapping",
        "defaults": {},
        "workflows": {},
    }

    for root in (first, second):
        (root / "nodrix.yaml").write_text(
            yaml.safe_dump(
                document,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    assert (
        project_entity_ref(first)
        == project_entity_ref(second)
    )
    assert (
        project_definition_digest(first)
        == project_definition_digest(second)
    )


def test_build_operation_uses_complete_canonical_path(
    tmp_path: Path,
) -> None:
    _build_project(
        tmp_path,
        command=(
            "python3 -c "
            "\"from pathlib import Path; "
            "Path('built.txt').write_text('ok')\""
        ),
    )

    outcome = execute_workflow_operation(
        "build",
        root=tmp_path,
    )

    assert outcome.plan.operation.kind_name == "build"
    assert outcome.plan.operation.subject.kind == "project"
    assert outcome.plan.kind_name == "workflow"

    assert outcome.execution.state is ExecutionState.COMPLETED
    assert outcome.execution.successful

    assert (tmp_path / "built.txt").read_text() == "ok"

    assert outcome.history.path.is_file()

    document = json.loads(
        outcome.history.path.read_text(
            encoding="utf-8"
        )
    )

    assert document["schema"] == "nodrix.run/v1"
    assert document["operation"]["kind"] == "build"
    assert document["plan"]["kind"] == "workflow"
    assert document["status"] == "completed"


def test_dry_run_is_successful_without_running_command(
    tmp_path: Path,
) -> None:
    _build_project(
        tmp_path,
        command=(
            "python3 -c "
            "\"from pathlib import Path; "
            "Path('must-not-exist.txt').write_text('bad')\""
        ),
    )

    outcome = execute_workflow_operation(
        "build",
        root=tmp_path,
        dry_run=True,
    )

    assert outcome.execution.state is ExecutionState.COMPLETED
    assert outcome.execution.successful
    assert outcome.execution.details["workflow_status"] == "planned"

    assert not (
        tmp_path / "must-not-exist.txt"
    ).exists()

    document = json.loads(
        outcome.history.path.read_text(
            encoding="utf-8"
        )
    )

    assert document["status"] == "completed"
    assert document["successful"] is True
    assert document["operation"]["parameters"]["dry_run"] is True


def test_generic_workflow_uses_workflow_run_operation(
    tmp_path: Path,
) -> None:
    create_progressive_project(tmp_path)

    workflow = add_project_resource(
        "workflow",
        "deploy",
        root=tmp_path,
    )

    workflow.path.write_text(
        "schema: nodrix.workflow/v1\n"
        "name: deploy\n"
        "steps:\n"
        "  - id: deploy\n"
        "    run: echo deploy\n",
        encoding="utf-8",
    )

    outcome = execute_workflow_operation(
        "deploy",
        root=tmp_path,
    )

    assert (
        outcome.plan.operation.kind
        == WORKFLOW_RUN_OPERATION
    )
    assert (
        outcome.plan.operation.parameters["workflow"]
        == "deploy"
    )


def test_build_cli_preserves_result_shape_and_writes_canonical_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_project(
        tmp_path,
        command="echo built",
    )

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [
            "build",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output

    payload = json.loads(result.stdout)

    assert payload["name"] == "build"
    assert payload["status"] == "succeeded"
    assert payload["steps"][0]["step_id"] == "compile"

    canonical_runs = list(
        (tmp_path / ".nodrix" / "runs").glob(
            "*/run.json"
        )
    )

    assert len(canonical_runs) == 1

    document = json.loads(
        canonical_runs[0].read_text(
            encoding="utf-8"
        )
    )

    assert document["operation"]["kind"] == "build"
    assert document["plan"]["kind"] == "workflow"
