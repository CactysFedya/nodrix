from __future__ import annotations

from pathlib import Path

import yaml

from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
    list_project_resources,
)
from nodrix.workflow_execution import (
    check_project_environment,
    run_workflow,
)


def test_progressive_project_creates_no_architecture_directories(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"
    created = create_progressive_project(root)

    assert created == [root / "nodrix.yaml", root / ".gitignore"]
    assert (root / "nodrix.yaml").is_file()
    assert not (root / "pipelines").exists()
    assert not (root / "workflows").exists()
    assert not (root / "environments").exists()


def test_resource_is_created_registered_and_can_be_default(
    tmp_path: Path,
) -> None:
    root = tmp_path / "robot"
    create_progressive_project(root)

    result = add_project_resource(
        "pipeline",
        "mapping",
        root=root,
        make_default=True,
    )

    assert result.path == root / "pipelines/mapping.yaml"
    assert result.path.is_file()
    project = yaml.safe_load((root / "nodrix.yaml").read_text(encoding="utf-8"))
    assert project["pipelines"]["mapping"] == "pipelines/mapping.yaml"
    assert project["defaults"]["pipeline"] == "mapping"
    assert list_project_resources("pipeline", root=root) == {
        "pipeline": {"mapping": "pipelines/mapping.yaml"}
    }


def test_raspberry_pi_environment_template(tmp_path: Path) -> None:
    root = tmp_path / "robot"
    create_progressive_project(root)
    result = add_project_resource(
        "environment",
        "raspberry-pi5",
        root=root,
        template="raspberry-pi5",
    )

    document = yaml.safe_load(result.path.read_text(encoding="utf-8"))
    assert document["platform"]["architecture"] == ["aarch64", "arm64"]
    assert document["environment"]["CMAKE_BUILD_PARALLEL_LEVEL"] == "4"


def test_workflow_runs_and_keeps_step_logs(tmp_path: Path) -> None:
    root = tmp_path / "robot"
    create_progressive_project(root)
    result = add_project_resource("workflow", "build", root=root)
    result.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.workflow/v1",
                "name": "build",
                "steps": [
                    {
                        "id": "write-artifact",
                        "run": (
                            "python3 -c \"from pathlib import Path; "
                            "Path('built.txt').write_text('ok')\""
                        ),
                    },
                    {
                        "id": "optional-tool",
                        "run": "exit 9",
                        "when": {"command_exists": "definitely-not-installed"},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    run = run_workflow("build", root=root)

    assert run.succeeded
    assert (root / "built.txt").read_text(encoding="utf-8") == "ok"
    assert [step.status for step in run.steps] == ["succeeded", "skipped"]

    operation_directory = Path(run.run_directory)

    assert operation_directory.is_dir()
    assert not (operation_directory / "summary.json").exists()

    logs = sorted(
        (operation_directory / "logs").glob("*.log")
    )
    assert len(logs) == 2


def test_failed_workflow_stops_at_first_failed_step(tmp_path: Path) -> None:
    root = tmp_path / "robot"
    create_progressive_project(root)
    result = add_project_resource("workflow", "test", root=root)
    result.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.workflow/v1",
                "name": "test",
                "steps": [
                    {"id": "fail", "run": "exit 7"},
                    {"id": "never", "run": "touch should-not-exist"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    run = run_workflow("test", root=root)

    assert not run.succeeded
    assert run.status == "failed"
    assert [step.step_id for step in run.steps] == ["fail"]
    assert not (root / "should-not-exist").exists()


def test_environment_check_without_environment_is_empty(tmp_path: Path) -> None:
    root = tmp_path / "robot"
    create_progressive_project(root)

    assert check_project_environment(root) == []
