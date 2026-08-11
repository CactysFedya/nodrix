from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import nodrix.cli_system_commands as system_cli
from nodrix.cli import app
from nodrix.system import (
    BackendDiagnostic,
    BackendExecutionState,
    BackendExecutionStatus,
    BackendValidationReport,
    Graph,
    NodeInstance,
    SystemModel,
    Target,
    dump_system,
)


runner = CliRunner()


class FakeLocalBackend:
    instances: list["FakeLocalBackend"] = []
    statuses: list[BackendExecutionStatus] = []
    inspect_error: BaseException | None = None
    validation_report = BackendValidationReport(backend="local")
    stopped = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.prepared_plan = None
        self.started = False
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.statuses = []
        cls.inspect_error = None
        cls.validation_report = BackendValidationReport(backend="local")
        cls.stopped = False

    def validate_plan(self, plan):
        self.plan = plan
        return type(self).validation_report

    def prepare_plan(self, plan):
        self.prepared_plan = plan
        return SimpleNamespace(
            metadata={"manifest_path": "/tmp/generated-local.yaml"},
        )

    def start(self, prepared):
        self.started = True
        return SimpleNamespace(execution_id="fake-001")

    def inspect(self, handle):
        if type(self).inspect_error is not None:
            error = type(self).inspect_error
            type(self).inspect_error = None
            raise error
        if not type(self).statuses:
            raise AssertionError("FakeLocalBackend has no status to return")
        return type(self).statuses.pop(0)

    def stop(self, handle, *, timeout_seconds=None):
        type(self).stopped = True
        self.stop_timeout = timeout_seconds
        return BackendExecutionStatus(
            backend="local",
            execution_id=handle.execution_id,
            state=BackendExecutionState.STOPPED,
        )


def _status(
    state: BackendExecutionState,
    *,
    message: str | None = None,
    details: dict | None = None,
):
    return BackendExecutionStatus(
        backend="local",
        execution_id="fake-001",
        state=state,
        message=message,
        details=details or {},
    )


def _write_local_system(
    path: Path,
    *,
    name: str = "run-test",
    uses: str = "demo.worker",
) -> None:
    dump_system(
        SystemModel(
            name=name,
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="worker", uses=uses),
                    ),
                ),
            ),
        ),
        path,
    )


def test_system_help_lists_run_command() -> None:
    result = runner.invoke(app, ["system", "--help"])
    assert result.exit_code == 0, result.output
    assert "run" in result.output


def test_system_run_help_exposes_execution_options() -> None:
    result = runner.invoke(app, ["system", "run", "--help"])
    assert result.exit_code == 0, result.output
    assert "--project" in result.output
    assert "--run-root" in result.output
    assert "--stop-timeout" in result.output
    assert "--warnings-as-errors" in result.output


def test_system_run_executes_local_backend_to_completion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "system.yaml"
    _write_local_system(path)
    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(BackendExecutionState.RUNNING),
        _status(
            BackendExecutionState.COMPLETED,
            details={
                "report": {
                    "pipeline": "run-test",
                    "status": "completed",
                    "duration_seconds": 0.25,
                    "nodes": {
                        "worker": {
                            "messages": 12,
                            "errors": 0,
                            "rate_hz": 10.0,
                            "health": {"status": "healthy"},
                        }
                    },
                    "edges": [],
                    "run_dir": "/tmp/project/.nodrix/runs/run-1",
                }
            },
        ),
    ]
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)
    monkeypatch.setattr(system_cli.time, "sleep", lambda _: None)

    result = runner.invoke(app, ["system", "run", str(path)])

    assert result.exit_code == 0, result.output
    assert "NODRIX RUN run-test" in result.output
    assert "FLOW" in result.output
    assert "PREPARED" in result.output
    assert "STARTED" in result.output
    assert "RUNNING" in result.output
    assert "COMPLETED" in result.output
    assert "Reason" in result.output
    assert "runtime returned normally" in result.output
    assert "Traffic" in result.output
    assert "12 messages" in result.output
    assert "COMPONENTS" in result.output
    assert "worker" in result.output
    assert "Artifacts" in result.output
    assert ".nodrix/runs/run-1" in result.output
    backend = FakeLocalBackend.instances[-1]
    assert backend.prepared_plan.system == "run-test"
    assert backend.started is True
    assert backend.kwargs["working_directory"] == tmp_path.resolve()


def test_system_run_failed_backend_status_returns_nonzero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "system.yaml"
    _write_local_system(path, name="failed-run")
    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(
            BackendExecutionState.FAILED,
            message="RuntimeError: boom",
        ),
    ]
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)

    result = runner.invoke(app, ["system", "run", str(path)])

    assert result.exit_code == 1
    assert "FAILED" in result.output
    assert "Reason" in result.output
    assert "RuntimeError: boom" in result.output


def test_system_run_warns_on_fast_unrequested_continuous_completion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "continuous.yaml"
    _write_local_system(
        path,
        name="continuous-run",
        uses="media.ffmpeg_source",
    )
    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(
            BackendExecutionState.COMPLETED,
            details={
                "report": {
                    "pipeline": "continuous-run",
                    "status": "completed",
                    "duration_seconds": 0.1,
                }
            },
        ),
    ]
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)

    result = runner.invoke(app, ["system", "run", str(path)])

    assert result.exit_code == 0, result.output
    assert "completed without a stop request" in result.output
    assert "source EOF" in result.output


def test_system_run_rejects_non_local_backend_before_prepare(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "remote.yaml"
    dump_system(
        SystemModel(
            name="remote-run",
            targets=(
                Target(
                    name="worker",
                    kind="host",
                    properties={"backend": "remote"},
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="worker",
                            uses="demo.worker",
                            target="worker",
                        ),
                    ),
                ),
            ),
        ),
        path,
    )
    FakeLocalBackend.reset()
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)

    result = runner.invoke(app, ["system", "run", str(path)])

    assert result.exit_code == 1
    assert "RUN101" in result.output
    assert "remote" in result.output
    assert FakeLocalBackend.instances == []


def test_system_run_surfaces_backend_validation_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "system.yaml"
    _write_local_system(path)
    FakeLocalBackend.reset()
    FakeLocalBackend.validation_report = BackendValidationReport(
        backend="local",
        diagnostics=(
            BackendDiagnostic(
                level="error",
                code="LOCAL999",
                path="graphs.main",
                message="unsupported test scope",
            ),
        ),
    )
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)

    result = runner.invoke(app, ["system", "run", str(path)])

    assert result.exit_code == 1
    assert "BACKEND" in result.output
    assert "LOCAL999" in result.output
    assert "RUN103" in result.output
    assert FakeLocalBackend.instances[-1].prepared_plan is None


def test_system_run_ctrl_c_requests_backend_stop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "system.yaml"
    _write_local_system(path)
    FakeLocalBackend.reset()
    FakeLocalBackend.inspect_error = KeyboardInterrupt()
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)

    result = runner.invoke(
        app,
        [
            "system",
            "run",
            str(path),
            "--stop-timeout",
            "0.25",
        ],
    )

    assert result.exit_code == 130
    assert "STOPPING" in result.output
    assert "STOPPED" in result.output
    assert "stop requested by user" in result.output
    assert FakeLocalBackend.stopped is True
    assert FakeLocalBackend.instances[-1].stop_timeout == 0.25


def test_system_run_execution_exception_attempts_stop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "system.yaml"
    _write_local_system(path)
    FakeLocalBackend.reset()
    FakeLocalBackend.inspect_error = RuntimeError("inspect exploded")
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)

    result = runner.invoke(app, ["system", "run", str(path)])

    assert result.exit_code == 1
    assert "EXECUTION FAILED" in result.output
    assert "inspect exploded" in result.output
    assert FakeLocalBackend.stopped is True


def test_system_run_with_project_resolves_sdk_and_passes_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    components = project / "components"
    components.mkdir(parents=True)
    (components / "nodes.py").write_text(
        "from plyctl import node\n\n"
        "@node\n"
        "def worker() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )
    path = project / "system.yaml"
    dump_system(
        SystemModel(
            name="project-run",
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="worker", uses="local.worker"),
                    ),
                ),
            ),
        ),
        path,
    )
    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(BackendExecutionState.COMPLETED),
    ]
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)

    result = runner.invoke(
        app,
        [
            "system",
            "run",
            str(path),
            "--project",
            str(project),
            "--run-root",
            str(tmp_path / "runs"),
        ],
    )

    assert result.exit_code == 0, result.output
    backend = FakeLocalBackend.instances[-1]
    assert backend.kwargs["project"] == project
    assert backend.kwargs["run_root"] == tmp_path / "runs"
    assert "COMPLETED" in result.output
    assert "Reason" in result.output


def test_system_run_warnings_as_errors_refuses_cycle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "cycle.yaml"
    dump_system(
        SystemModel(
            name="cycle-run",
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="a", uses="demo.a"),
                        NodeInstance(name="b", uses="demo.b"),
                    ),
                    connections=(
                        {"from": "a.output", "to": "b.input"},
                        {"from": "b.output", "to": "a.input"},
                    ),
                ),
            ),
        ),
        path,
    )
    FakeLocalBackend.reset()
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)

    result = runner.invoke(
        app,
        ["system", "run", str(path), "--warnings-as-errors"],
    )

    assert result.exit_code == 1
    assert "RUN102" in result.output
    assert "PLAN101" in result.output
    assert FakeLocalBackend.instances == []
