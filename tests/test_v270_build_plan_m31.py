from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.project_foundation import create_progressive_project


runner = CliRunner()


def test_build_plan_without_configuration_is_actionable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_progressive_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["build", "--plan"])

    assert result.exit_code == 1
    assert "Build is not configured for this project" in result.output
    assert "nodrix.yaml" in result.output
    assert "workflows.build" in result.output
    assert "workflows entry 'build'" not in result.output


def test_plain_build_without_configuration_uses_same_message(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_progressive_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["build"])

    assert result.exit_code == 1
    assert "Build is not configured for this project" in result.output
    assert "plyctl project recipes" in result.output


def test_unconfigured_build_json_is_machine_readable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    create_progressive_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["build", "--plan", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "not_configured"
    assert payload["workflow"] == "build"
    assert "Build is not configured" in payload["message"]
