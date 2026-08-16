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


def test_workflow_operation_keeps_logs_without_legacy_summary(
    tmp_path: Path,
) -> None:
    _build_project(
        tmp_path,
        command="echo built",
    )

    outcome = execute_workflow_operation(
        "build",
        root=tmp_path,
    )

    operation_directory = Path(
        str(outcome.execution.details["run_directory"])
    )

    assert operation_directory.is_dir()
    assert not (
        operation_directory / "summary.json"
    ).exists()

    logs = list(
        (operation_directory / "logs").glob("*.log")
    )
    assert logs

    assert outcome.history.path.is_file()


def test_prepare_cli_uses_canonical_execution_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_progressive_project(tmp_path)

    workflow = add_project_resource(
        "workflow",
        "prepare",
        root=tmp_path,
    )

    workflow.path.write_text(
        "schema: nodrix.workflow/v1\n"
        "name: prepare\n"
        "steps:\n"
        "  - id: prepare\n"
        "    run: echo prepared\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["prepare"],
    )

    assert result.exit_code == 0, result.output
    assert "READY" in result.output
    assert "History:" in result.output

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

    assert document["plan"]["kind"] == "workflow"
    assert document["operation"]["kind"] == "prepare"
    assert (
        document["operation"]["parameters"]["workflow"]
        == "prepare"
    )

    legacy_summaries = list(
        (tmp_path / ".nodrix" / "operations").glob(
            "*/summary.json"
        )
    )
    assert legacy_summaries == []


def test_builtin_workflow_names_resolve_to_canonical_operations() -> None:
    from nodrix.workflow_operation import (
        resolve_workflow_operation_kind,
    )

    expected = {
        "prepare": "prepare",
        "build": "build",
        "test": "test",
        "validate": "validate",
        "profile": "profile",
        "benchmark": "benchmark",
        "diagnose": "diagnose",
        "calibrate": "calibrate",
        "export": "export",
        "package": "package",
        "cleanup": "cleanup",
    }

    assert {
        workflow: resolve_workflow_operation_kind(workflow).value
        for workflow in expected
    } == expected


def test_unknown_workflow_resolves_to_generic_workflow_operation() -> None:
    from nodrix.workflow_operation import (
        WORKFLOW_RUN_OPERATION,
        resolve_workflow_operation_kind,
    )

    assert (
        resolve_workflow_operation_kind("deploy")
        == WORKFLOW_RUN_OPERATION
    )


def test_workflow_operation_kind_can_be_explicitly_overridden() -> None:
    from nodrix.workflow_operation import (
        resolve_workflow_operation_kind,
    )

    resolved = resolve_workflow_operation_kind(
        "flash",
        requested="mycompany.flash-firmware",
    )

    assert resolved.value == "mycompany.flash-firmware"


def test_explicit_operation_kind_overrides_builtin_binding() -> None:
    from nodrix.workflow_operation import (
        resolve_workflow_operation_kind,
    )

    resolved = resolve_workflow_operation_kind(
        "build",
        requested="vendor.cross-build",
    )

    assert resolved.value == "vendor.cross-build"


def test_optimize_workflow_resolves_to_builtin_operation_kind() -> None:
    from nodrix.model import OPTIMIZE
    from nodrix.workflow_operation import (
        resolve_workflow_operation_kind,
    )

    assert (
        resolve_workflow_operation_kind("optimize")
        == OPTIMIZE
    )


def test_custom_workflow_remains_extensible() -> None:
    from nodrix.model import OperationKind
    from nodrix.workflow_operation import (
        resolve_workflow_operation_kind,
    )

    custom = OperationKind(
        "robot.flash"
    )

    assert (
        resolve_workflow_operation_kind(
            "flash",
            requested=custom,
        )
        == custom
    )


def test_declared_workflow_operation_binding_reaches_canonical_operation(
    tmp_path: Path,
) -> None:
    from nodrix.project_foundation import (
        add_project_resource,
        create_progressive_project,
    )
    from nodrix.workflow_operation import (
        execute_workflow_operation,
    )

    create_progressive_project(
        tmp_path
    )

    resource = add_project_resource(
        "workflow",
        "flash",
        root=tmp_path,
    )

    resource.path.write_text(
        "schema: nodrix.workflow/v1\n"
        "name: flash\n"
        "implements: robot.flash\n"
        "steps:\n"
        "  - id: write\n"
        "    run: echo flash\n",
        encoding="utf-8",
    )

    outcome = execute_workflow_operation(
        "flash",
        root=tmp_path,
        dry_run=True,
    )

    assert (
        outcome.plan.operation.kind_name
        == "robot.flash"
    )

    assert (
        outcome.plan.payload.implements
        == "robot.flash"
    )


def test_explicit_operation_kind_overrides_declared_workflow_binding(
    tmp_path: Path,
) -> None:
    from nodrix.project_foundation import (
        add_project_resource,
        create_progressive_project,
    )
    from nodrix.workflow_operation import (
        execute_workflow_operation,
    )

    create_progressive_project(
        tmp_path
    )

    resource = add_project_resource(
        "workflow",
        "build",
        root=tmp_path,
    )

    resource.path.write_text(
        "schema: nodrix.workflow/v1\n"
        "name: build\n"
        "implements: vendor.cross-build\n"
        "steps:\n"
        "  - id: build\n"
        "    run: echo build\n",
        encoding="utf-8",
    )

    outcome = execute_workflow_operation(
        "build",
        root=tmp_path,
        dry_run=True,
        operation_kind="debug.cross-build",
    )

    assert (
        outcome.plan.operation.kind_name
        == "debug.cross-build"
    )


def test_declared_operation_binding_overrides_workflow_name_convention() -> None:
    from nodrix.workflow_operation import (
        resolve_workflow_operation_kind,
    )

    resolved = resolve_workflow_operation_kind(
        "build",
        declared="vendor.cross-build",
    )

    assert resolved.value == "vendor.cross-build"
