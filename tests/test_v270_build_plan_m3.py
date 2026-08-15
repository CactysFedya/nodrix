from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.project_foundation import add_project_resource, create_progressive_project
from nodrix.workflow_execution import run_workflow
from nodrix.workflow_planning import plan_workflow


runner = CliRunner()


def _cached_dependency_project(tmp_path: Path) -> None:
    create_progressive_project(tmp_path)
    (tmp_path / "a.txt").write_text("a1\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b1\n", encoding="utf-8")
    workflow = add_project_resource("workflow", "build", root=tmp_path)
    workflow.path.write_text(
        "schema: nodrix.workflow/v1\n"
        "name: build\n"
        "steps:\n"
        "  - id: dependency\n"
        "    run: |\n"
        "      python3 -c \"from pathlib import Path; Path('a.out').write_text(Path('a.txt').read_text())\"\n"
        "    cache:\n"
        "      inputs: [a.txt]\n"
        "      outputs: [a.out]\n"
        "  - id: consumer\n"
        "    depends_on: [dependency]\n"
        "    run: |\n"
        "      python3 -c \"from pathlib import Path; Path('b.out').write_text(Path('b.txt').read_text())\"\n"
        "    cache:\n"
        "      inputs: [b.txt]\n"
        "      outputs: [b.out]\n",
        encoding="utf-8",
    )


def test_plan_reports_cache_hits(tmp_path: Path) -> None:
    _cached_dependency_project(tmp_path)
    first = run_workflow("build", root=tmp_path)
    assert [item.status for item in first.steps] == ["succeeded", "succeeded"]

    plan = plan_workflow("build", root=tmp_path)
    assert [item.status for item in plan.steps] == ["cached", "cached"]
    assert all(item.cache == "hit" for item in plan.steps)


def test_dependency_rebuild_invalidates_dependent_cache(tmp_path: Path) -> None:
    _cached_dependency_project(tmp_path)
    run_workflow("build", root=tmp_path)
    (tmp_path / "a.txt").write_text("a2 changed\n", encoding="utf-8")

    plan = plan_workflow("build", root=tmp_path)
    assert plan.steps[0].status == "planned"
    assert plan.steps[1].status == "planned"
    assert any("dependency will rebuild" in reason for reason in plan.steps[1].reasons)

    rebuilt = run_workflow("build", root=tmp_path)
    assert [item.status for item in rebuilt.steps] == ["succeeded", "succeeded"]


def test_generated_build_recipe_plan_exposes_recipe_and_dependencies(tmp_path: Path) -> None:
    create_progressive_project(tmp_path)
    (tmp_path / "sources" / "lib").mkdir(parents=True)
    (tmp_path / "sources" / "app").mkdir(parents=True)
    project_path = tmp_path / "nodrix.yaml"
    project = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    project["build"] = {
        "lib": {
            "uses": "cmake.release",
            "source": "sources/lib",
            "cache": "auto",
        },
        "app": {
            "uses": "cmake.release",
            "source": "sources/app",
            "depends_on": ["lib"],
            "cache": "auto",
        },
    }
    project_path.write_text(yaml.safe_dump(project, sort_keys=False), encoding="utf-8")

    plan = plan_workflow("build", root=tmp_path)
    assert plan.generated is True
    assert [item.recipe for item in plan.steps] == ["cmake.release", "cmake.release"]
    assert plan.steps[1].depends_on == ("lib",)


def test_build_plan_cli_is_read_only_and_human_readable(tmp_path: Path, monkeypatch) -> None:
    _cached_dependency_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["build", "--plan"])
    assert result.exit_code == 0, result.output
    assert "BUILD PLAN" in result.output
    assert "dependency" in result.output
    assert "consumer" in result.output
    assert not (tmp_path / "a.out").exists()
    assert not (tmp_path / "b.out").exists()


def test_build_explain_cli_reports_reason_and_tracked_inputs(tmp_path: Path, monkeypatch) -> None:
    _cached_dependency_project(tmp_path)
    run_workflow("build", root=tmp_path)
    (tmp_path / "a.txt").write_text("changed\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["build", "--explain", "dependency"])
    assert result.exit_code == 0, result.output
    assert "BUILD EXPLAIN dependency" in result.output
    assert "cache fingerprint changed" in result.output
    assert "a.txt" in result.output


def test_build_plan_rebuild_and_json(tmp_path: Path, monkeypatch) -> None:
    _cached_dependency_project(tmp_path)
    run_workflow("build", root=tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["build", "--plan", "--rebuild", "--json"])
    assert result.exit_code == 0, result.output
    assert '"status": "planned"' in result.output
    assert "--rebuild requested" in result.output
