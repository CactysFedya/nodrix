from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.cli_admin_commands import _format_status_memory
from nodrix.cli_project_commands import _effective_run_root
from nodrix.ux import _node_line

runner = CliRunner()


def test_default_run_root_uses_invocation_project(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    manifest_dir = project / "integrations" / "demo"
    manifest_dir.mkdir(parents=True)
    monkeypatch.chdir(project)
    assert _effective_run_root(None) == (project / ".nodrix" / "runs").resolve()
    assert _effective_run_root(None) != (manifest_dir / ".nodrix" / "runs").resolve()


def test_explicit_run_root_is_preserved(tmp_path: Path) -> None:
    selected = tmp_path / "custom-runs"
    assert _effective_run_root(selected) == selected.resolve()


def test_admin_commands_hide_missing_run_tracebacks(tmp_path: Path) -> None:
    expected_root = str(tmp_path / ".nodrix" / "runs")
    for command in ("status", "health", "top", "metrics"):
        result = runner.invoke(app, [command, "--project", str(tmp_path)])
        assert result.exit_code == 1
        assert "No Plyctl runs found" in result.output
        assert "Traceback" not in result.output
        assert expected_root in result.output
        assert "plyctl run pipeline.yaml" in result.output


def test_shared_executor_memory_is_labelled() -> None:
    assert _format_status_memory({"scope": "executor_shared"}, 1024) == "1.0 KiB shared"
    assert _format_status_memory({"scope": "process"}, 1024) == "1.0 KiB"


def test_health_node_rate_is_monitor_rate() -> None:
    line = _node_line(
        "lidar_health",
        {
            "rate_hz": 2.0,
            "p95_ms": 0.03,
            "resources": {"cpu_percent": 0.0},
            "health": {"status": "healthy"},
        },
        0.03,
    )
    assert "2.0 monitor Hz" in line.plain


def test_fastlio2_primary_is_headless() -> None:
    root = Path(__file__).resolve().parents[1]
    pipeline_dir = root / "integrations/nodrix-fast-lio2/pipelines"
    primary = yaml.safe_load((pipeline_dir / "fastlio2.yaml").read_text(encoding="utf-8"))
    rviz = yaml.safe_load((pipeline_dir / "fastlio2-rviz.yaml").read_text(encoding="utf-8"))
    assert "rviz" not in primary.get("applications", {})
    assert all(
        not str(edge.get("from", "")).startswith("rviz.")
        and not str(edge.get("to", "")).startswith("rviz.")
        for edge in primary.get("edges", [])
    )
    assert "rviz" in rviz.get("applications", {})
