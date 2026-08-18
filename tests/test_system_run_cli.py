from __future__ import annotations

import json
from pathlib import Path
import re

import yaml

from typer.testing import CliRunner

import nodrix.cli_system_commands as system_cli
from nodrix.cli import app
from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
)
from nodrix.system import (
    BackendCapabilities,
    BackendDiagnostic,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    BackendValidationReport,
    ExecutionBackend,
    ExecutionHealthState,
    ExecutionObservation,
    Graph,
    NodeInstance,
    PreparedExecution,
    SystemModel,
    Target,
    dump_system,
)


runner = CliRunner()
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _plain(output: str) -> str:
    return _ANSI_ESCAPE.sub("", output)


class FakeLocalBackend(ExecutionBackend):
    instances: list["FakeLocalBackend"] = []
    statuses: list[BackendExecutionStatus] = []
    inspect_error: BaseException | None = None
    validation_report = BackendValidationReport(backend="local")
    stopped = False

    def __init__(self, **kwargs):
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds=frozenset({"local", "host"}),
            ),
        )
        self.kwargs = kwargs
        self.prepared_context = None
        self.started = False
        self.stop_timeout = None
        self.instance_number = len(type(self).instances) + 1
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.statuses = []
        cls.inspect_error = None
        cls.validation_report = BackendValidationReport(backend="local")
        cls.stopped = False

    def _validate(self, context):
        self.validated_context = context
        return type(self).validation_report.diagnostics

    def _prepare(self, context):
        self.prepared_context = context
        return PreparedExecution(
            backend="local",
            context=context,
            metadata={"manifest_path": "/tmp/generated-local.yaml"},
        )

    def _start(self, prepared):
        self.started = True
        return BackendExecutionHandle(
            backend="local",
            execution_id=f"fake-{self.instance_number:03d}",
            prepared=prepared,
        )

    def _inspect(self, handle):
        if type(self).inspect_error is not None:
            error = type(self).inspect_error
            type(self).inspect_error = None
            raise error
        if not type(self).statuses:
            raise AssertionError("FakeLocalBackend has no status to return")
        template = type(self).statuses.pop(0)
        return BackendExecutionStatus(
            backend="local",
            execution_id=handle.execution_id,
            state=template.state,
            message=template.message,
            details=template.details,
            observation=template.observation,
        )

    def _stop(self, handle, *, timeout_seconds=None):
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
    observation: ExecutionObservation | None = None,
) -> BackendExecutionStatus:
    return BackendExecutionStatus(
        backend="local",
        execution_id="template",
        state=state,
        message=message,
        observation=observation,
    )


def _write_local_system(path: Path, *, name: str = "run-test") -> None:
    dump_system(
        SystemModel(
            name=name,
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="worker", uses="demo.worker"),
                    ),
                ),
            ),
        ),
        path,
    )


def test_system_help_lists_run_command() -> None:
    result = runner.invoke(app, ["system", "--help"])
    assert result.exit_code == 0, result.output
    assert "run" in _plain(result.output)


def test_system_run_help_exposes_execution_options() -> None:
    result = runner.invoke(app, ["system", "run", "--help"])
    assert result.exit_code == 0, result.output
    output = _plain(result.output)
    assert "--project" in output
    assert "--profile" in output
    assert "Project Profile" in output
    assert "RuntimePreset" in output
    assert "--run-root" in output
    assert "--stop-timeout" in output
    assert "--warnings-as-errors" in output


def test_system_run_executes_local_backend_to_completion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "system.yaml"
    _write_local_system(path)
    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(BackendExecutionState.RUNNING),
        _status(BackendExecutionState.COMPLETED),
    ]
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)
    monkeypatch.setattr(system_cli.time, "sleep", lambda _: None)

    result = runner.invoke(app, ["system", "run", str(path)])

    assert result.exit_code == 0, result.output
    assert "PREPARED" in result.output
    assert "STARTED" in result.output
    assert "RUNNING" in result.output
    assert "COMPLETED" in result.output
    assert "local:local" in result.output
    backend = FakeLocalBackend.instances[-1]
    assert backend.prepared_context.plan.system == "run-test"
    assert backend.started is True
    assert backend.kwargs["working_directory"] == tmp_path.resolve()


def test_system_run_failed_scope_stops_remaining_execution(
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
    assert "RuntimeError: boom" in result.output
    assert FakeLocalBackend.stopped is True


def test_system_run_reports_missing_non_local_backend_binding(
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
    assert "ORCH101" in result.output
    assert "RUN103" in result.output
    assert "worker:remote" in result.output
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
    assert "LOCAL999" in result.output
    assert "RUN103" in result.output
    assert FakeLocalBackend.instances[-1].prepared_context is None


def test_system_run_ctrl_c_requests_orchestrated_stop(
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
    assert "Stopping" in result.output
    assert "STOPPED" in result.output
    assert FakeLocalBackend.stopped is True
    assert FakeLocalBackend.instances[-1].stop_timeout == 0.25


def test_system_run_inspect_exception_becomes_failure_and_stops(
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
    assert "FAILED" in result.output
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
    assert backend.kwargs["project"] == project.resolve()
    assert backend.kwargs["run_root"] == tmp_path / "runs"
    assert "COMPLETED" in result.output


def test_system_run_handles_multiple_independent_local_scopes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "multi-local.yaml"
    dump_system(
        SystemModel(
            name="multi-local",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={"backend": "local"},
                ),
                Target(
                    name="workstation",
                    kind="host",
                    properties={"backend": "local"},
                ),
            ),
            graphs=(
                Graph(
                    name="robot_graph",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="demo.source",
                            target="robot",
                        ),
                    ),
                ),
                Graph(
                    name="workstation_graph",
                    nodes=(
                        NodeInstance(
                            name="sink",
                            uses="demo.sink",
                            target="workstation",
                        ),
                    ),
                ),
            ),
        ),
        path,
    )
    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(BackendExecutionState.RUNNING),
        _status(BackendExecutionState.RUNNING),
        _status(BackendExecutionState.COMPLETED),
        _status(BackendExecutionState.COMPLETED),
    ]
    monkeypatch.setattr(system_cli, "LocalBackend", FakeLocalBackend)
    monkeypatch.setattr(system_cli.time, "sleep", lambda _: None)

    result = runner.invoke(app, ["system", "run", str(path)])

    assert result.exit_code == 0, result.output
    assert len(FakeLocalBackend.instances) == 2
    assert "robot:local" in result.output
    assert "workstation:local" in result.output
    assert "scopes=2" in result.output


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


def test_system_run_profile_uses_exact_profile_bound_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"

    create_progressive_project(
        project
    )

    profile = add_project_resource(
        "profile",
        "field",
        root=project,
    )

    profile.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.profile/v1",
                "name": "field",
                "variables": {
                    "RUN_MARKER": "profile-value",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    system_path = (
        project
        / "systems"
        / "run.yaml"
    )
    system_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    _write_local_system(
        system_path,
        name="profile-run",
    )

    planned = runner.invoke(
        app,
        [
            "system",
            "plan",
            str(system_path),
            "--profile",
            "field",
            "--json",
        ],
    )

    assert planned.exit_code == 0, planned.output

    expected_plan = json.loads(
        planned.stdout
    )

    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(
            BackendExecutionState.COMPLETED
        ),
    ]

    monkeypatch.setattr(
        system_cli,
        "LocalBackend",
        FakeLocalBackend,
    )
    monkeypatch.setattr(
        system_cli.time,
        "sleep",
        lambda _: None,
    )

    executed = runner.invoke(
        app,
        [
            "system",
            "run",
            str(system_path),
            "--profile",
            "field",
        ],
    )

    assert executed.exit_code == 0, executed.output

    backend = FakeLocalBackend.instances[-1]
    context = backend.prepared_context

    assert context is not None
    assert (
        context.plan.model_dump(
            by_alias=True,
            exclude_none=True,
            mode="json",
        )
        == expected_plan
    )

    assert (
        context.execution_context
        is not None
    )

    assert (
        context.execution_context.variables[
            "RUN_MARKER"
        ]
        == "profile-value"
    )

    # Selection metadata/raw execution values remain outside the Plan.
    serialized = json.dumps(
        expected_plan
    )

    assert "RUN_MARKER" not in serialized
    assert "profile-value" not in serialized
    assert '"field"' not in serialized


def _write_hierarchical_run_systems(
    root: Path,
) -> tuple[Path, Path]:
    child_path = (
        root / "livox-mid360.yaml"
    )

    _write_local_system(
        child_path,
        name="livox-mid360",
    )

    parent_path = (
        root / "rpi5-mapping.yaml"
    )

    parent_path.write_text(
        yaml.safe_dump(
            {
                "apiVersion": (
                    "nodrix.system/v1"
                ),
                "kind": "System",
                "name": "rpi5-mapping",
                "systems": [
                    {
                        "name": "lidar",
                        "uses": (
                            "./livox-mid360.yaml"
                        ),
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    return (
        parent_path,
        child_path,
    )


def test_system_run_executes_child_system_hierarchy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (
        parent_path,
        _,
    ) = _write_hierarchical_run_systems(
        tmp_path
    )

    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(
            BackendExecutionState.COMPLETED
        ),
    ]

    monkeypatch.setattr(
        system_cli,
        "LocalBackend",
        FakeLocalBackend,
    )
    monkeypatch.setattr(
        system_cli.time,
        "sleep",
        lambda _: None,
    )

    result = runner.invoke(
        app,
        [
            "system",
            "run",
            str(parent_path),
        ],
    )

    assert (
        result.exit_code == 0
    ), result.output

    assert "PREPARED" in result.output
    assert "STARTED" in result.output
    assert "rpi5-mapping" in result.output
    assert "lidar" in result.output
    assert "systems=1" in result.output
    assert "COMPLETED" in result.output

    # Composition-only parent creates no backend scope.
    # Its child System owns the executable local scope.
    assert (
        len(
            FakeLocalBackend.instances
        )
        == 1
    )

    backend = (
        FakeLocalBackend.instances[0]
    )

    assert (
        backend
        .prepared_context
        .plan
        .system
        == "livox-mid360"
    )


def test_system_run_executes_child_system_standalone(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (
        _,
        child_path,
    ) = _write_hierarchical_run_systems(
        tmp_path
    )

    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(
            BackendExecutionState.COMPLETED
        ),
    ]

    monkeypatch.setattr(
        system_cli,
        "LocalBackend",
        FakeLocalBackend,
    )
    monkeypatch.setattr(
        system_cli.time,
        "sleep",
        lambda _: None,
    )

    result = runner.invoke(
        app,
        [
            "system",
            "run",
            str(child_path),
        ],
    )

    assert (
        result.exit_code == 0
    ), result.output

    assert "livox-mid360" in result.output
    assert "systems=0" in result.output
    assert "COMPLETED" in result.output

    assert (
        len(
            FakeLocalBackend.instances
        )
        == 1
    )

    assert (
        FakeLocalBackend
        .instances[0]
        .prepared_context
        .plan
        .system
        == "livox-mid360"
    )


def test_system_run_renders_scope_transition_while_parent_stays_running(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "transition.yaml"

    dump_system(
        SystemModel(
            name="transition-run",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={
                        "backend": "local",
                    },
                ),
                Target(
                    name="workstation",
                    kind="host",
                    properties={
                        "backend": "local",
                    },
                ),
            ),
            graphs=(
                Graph(
                    name="robot_graph",
                    nodes=(
                        NodeInstance(
                            name="robot_worker",
                            uses="demo.worker",
                            target="robot",
                        ),
                    ),
                ),
                Graph(
                    name="workstation_graph",
                    nodes=(
                        NodeInstance(
                            name="workstation_worker",
                            uses="demo.worker",
                            target="workstation",
                        ),
                    ),
                ),
            ),
        ),
        path,
    )

    FakeLocalBackend.reset()

    # inspect #1
    #   robot       RUNNING
    #   workstation RUNNING
    #
    # inspect #2
    #   robot       COMPLETED
    #   workstation RUNNING
    #
    # Parent remains RUNNING here.
    #
    # inspect #3
    #   robot       COMPLETED
    #   workstation COMPLETED
    FakeLocalBackend.statuses = [
        _status(
            BackendExecutionState.RUNNING
        ),
        _status(
            BackendExecutionState.RUNNING
        ),
        _status(
            BackendExecutionState.COMPLETED
        ),
        _status(
            BackendExecutionState.RUNNING
        ),
        _status(
            BackendExecutionState.COMPLETED
        ),
        _status(
            BackendExecutionState.COMPLETED
        ),
    ]

    monkeypatch.setattr(
        system_cli,
        "LocalBackend",
        FakeLocalBackend,
    )
    monkeypatch.setattr(
        system_cli.time,
        "sleep",
        lambda _: None,
    )

    result = runner.invoke(
        app,
        [
            "system",
            "run",
            str(path),
        ],
    )

    assert (
        result.exit_code == 0
    ), result.output

    output = _plain(
        result.output
    )

    assert (
        len(
            FakeLocalBackend.instances
        )
        == 2
    )

    # Three visible tree snapshots must be rendered:
    # initial RUNNING, nested transition while the parent
    # remains RUNNING, and final COMPLETED.
    assert (
        output.count(
            "robot:local"
        )
        == 3
    )
    assert (
        output.count(
            "workstation:local"
        )
        == 3
    )


def test_system_run_renders_observation_transition_without_state_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "observation.yaml"
    _write_local_system(
        path,
        name="observation-run",
    )

    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(
            BackendExecutionState.RUNNING,
            observation=ExecutionObservation(
                ready=True,
                health=ExecutionHealthState.HEALTHY,
            ),
        ),
        _status(
            BackendExecutionState.RUNNING,
            observation=ExecutionObservation(
                ready=True,
                health=ExecutionHealthState.DEGRADED,
                message="camera latency is elevated",
            ),
        ),
        _status(
            BackendExecutionState.COMPLETED,
            observation=ExecutionObservation(
                ready=False,
                health=ExecutionHealthState.HEALTHY,
            ),
        ),
    ]

    monkeypatch.setattr(
        system_cli,
        "LocalBackend",
        FakeLocalBackend,
    )
    monkeypatch.setattr(
        system_cli.time,
        "sleep",
        lambda _: None,
    )

    result = runner.invoke(
        app,
        [
            "system",
            "run",
            str(path),
        ],
    )

    assert result.exit_code == 0, result.output

    output = _plain(result.output)

    assert "ready=yes" in output
    assert "ready=no" in output
    assert "health=healthy" in output
    assert "health=degraded" in output
    assert "camera latency is elevated" in output


def test_system_run_renders_nested_system_observation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent_path, _ = _write_hierarchical_run_systems(
        tmp_path
    )

    FakeLocalBackend.reset()
    FakeLocalBackend.statuses = [
        _status(
            BackendExecutionState.COMPLETED,
            observation=ExecutionObservation(
                ready=False,
                health=ExecutionHealthState.HEALTHY,
            ),
        ),
    ]

    monkeypatch.setattr(
        system_cli,
        "LocalBackend",
        FakeLocalBackend,
    )
    monkeypatch.setattr(
        system_cli.time,
        "sleep",
        lambda _: None,
    )

    result = runner.invoke(
        app,
        [
            "system",
            "run",
            str(parent_path),
        ],
    )

    assert result.exit_code == 0, result.output

    output = _plain(result.output)

    assert "systems=1" in output
    assert "lidar → livox-mid360" in output
    assert "health=healthy" in output
