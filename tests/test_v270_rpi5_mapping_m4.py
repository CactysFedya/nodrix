from __future__ import annotations

from pathlib import Path
import os

import pytest
import yaml
from typer.testing import CliRunner

import nodrix.cli_system_commands as system_cli
from nodrix.build_recipes import compile_project_build_workflow
from nodrix.cli import app
from nodrix.system import (
    ApplicationInstance,
    BackendCapabilities,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    PreparedExecution,
    ResourceInstance,
    SystemModel,
    Graph,
    NodeInstance,
    dump_system,
    load_system,
    plan_system,
    validate_system,
)
from nodrix.system.backend import BackendContext
from nodrix.system.local_backend import LocalBackend, lower_local_context


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _requires_repo_path(relative: str):
    return pytest.mark.skipif(
        not (ROOT / relative).exists(),
        reason=f"repository fixture is not shipped in sdist: {relative}",
    )


def _project() -> dict:
    return yaml.safe_load((ROOT / "nodrix.yaml").read_text(encoding="utf-8"))


@_requires_repo_path("nodrix.yaml")
def test_root_project_registers_rpi5_mapping_dogfood() -> None:
    project = _project()
    assert project["defaults"]["system"] == "rpi5-mapping"
    assert project["systems"]["rpi5-mapping"] == "systems/rpi5-mapping.yaml"
    assert project["workflows"]["prepare"] == "workflows/prepare.yaml"
    assert project["workflows"]["test"] == "workflows/test.yaml"
    assert project["contexts"]["rpi5-mapping"]["environment"] == "rpi5-jazzy"

    build = project["build"]
    assert build["livox-driver"]["depends_on"] == ["livox-sdk2"]
    assert build["fast-lio2"]["depends_on"] == ["livox-driver"]
    assert build["nodrix-spatial-ros2"]["depends_on"] == [
        "nodrix-ros2",
        "nodrix-spatial",
    ]
    assert build["nodrix-mapping"]["environment"][
        "NODRIX_MAPPING_NATIVE_ARCH_NATIVE"
    ] == "1"
    assert build["nodrix-mapping"]["environment"][
        "NODRIX_MAPPING_NATIVE_LTO"
    ] == "1"


@_requires_repo_path("systems/rpi5-mapping.yaml")
def test_reference_system_is_structurally_valid_and_maps_registered_cloud() -> None:
    system = load_system(ROOT / "systems/rpi5-mapping.yaml")
    report = validate_system(system)
    assert report.valid, report.diagnostics

    ros = next(item for item in system.resources if item.name == "ros")
    assert ros.uses == "ros2.session"
    assert ros.extensions.get("legacy_role") is None

    applications = {item.name: item for item in system.applications}
    assert applications["livox"].resources["session"] == "ros"
    assert applications["fast_lio"].resources["session"] == "ros"

    graph = system.graphs[0]
    nodes = {item.name: item for item in graph.nodes}
    assert nodes["registered_cloud"].uses == "ros2.point_cloud2_source"
    assert nodes["registered_cloud"].resources["session"] == "ros"
    assert nodes["voxel_map"].uses == "mapping.voxel_map"
    assert nodes["ply_store"].uses == "mapping.ply_store"
    assert {(item.source, item.target) for item in graph.connections} == {
        ("registered_cloud.cloud", "voxel_map.cloud"),
        ("voxel_map.snapshot", "ply_store.map"),
    }
    assert system.artifacts[0].path == "artifacts/maps/metric/latest.ply"


@pytest.mark.skipif(
    os.name == "nt",
    reason="RPi5 build recipe setup requires a POSIX shell",
)
@_requires_repo_path("nodrix.yaml")
def test_build_recipe_compiler_exposes_real_dependency_chain() -> None:
    compiled = compile_project_build_workflow(ROOT, project=_project())
    assert compiled is not None
    document, _ = compiled
    steps = {item["id"]: item for item in document["steps"]}
    assert steps["livox-sdk2"]["recipe"] == "cmake.release"
    assert steps["livox-driver"]["depends_on"] == ["livox-sdk2"]
    assert steps["fast-lio2"]["depends_on"] == ["livox-driver"]
    assert steps["nodrix-mapping"]["recipe"] == "python.editable"


def test_new_system_session_binding_lowers_without_legacy_extension(
    tmp_path: Path,
) -> None:
    system = SystemModel(
        name="session-dogfood",
        resources=(ResourceInstance(name="ros", uses="demo.session"),),
        applications=(
            ApplicationInstance(
                name="worker",
                uses="demo.app",
                resources={"session": "ros"},
            ),
        ),
    )
    plan = plan_system(system)
    context = BackendContext.from_plan(plan, "local")
    lowering = lower_local_context(context)

    assert "ros" in lowering.manifest.sessions
    assert "ros" not in lowering.manifest.resources
    assert lowering.manifest.applications["worker"].bindings["session"] == "ros"

    backend = LocalBackend(working_directory=tmp_path)
    report = backend.validate_plan(plan)
    assert report.valid, report.diagnostics


@pytest.mark.skipif(
    os.name == "nt",
    reason="RPi5 ROS environment expansion is POSIX-targeted",
)
@_requires_repo_path("packages/nodrix-ros2/src")
def test_ros_session_expands_project_root_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_src = ROOT / "packages/nodrix-ros2/src"
    monkeypatch.syspath_prepend(str(package_src))
    from nodrix_ros2.workspace import RosWorkspaceSpec

    spec = RosWorkspaceSpec.from_mapping(
        {
            "environment": {
                "LD_LIBRARY_PATH": "${PROJECT_ROOT}/.nodrix/prefix/lib",
            }
        },
        base_dir=tmp_path,
    )
    assert spec.environment["LD_LIBRARY_PATH"] == str(
        tmp_path.resolve() / ".nodrix/prefix/lib"
    )


class _FakeBackend(ExecutionBackend):
    instances: list["_FakeBackend"] = []

    def __init__(self, **kwargs):
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds=frozenset({"local", "host"}),
            ),
        )
        self.kwargs = kwargs
        type(self).instances.append(self)

    def _validate(self, context):
        return ()

    def _prepare(self, context):
        return PreparedExecution(
            backend=self.backend_id,
            context=context,
            metadata={"manifest_path": "/tmp/generated.yaml"},
        )

    def _start(self, prepared):
        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id="m4",
            prepared=prepared,
        )

    def _inspect(self, handle):
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=BackendExecutionState.COMPLETED,
        )

    def _stop(self, handle, *, timeout_seconds=None):
        return self._inspect(handle)


def test_nested_registered_system_executes_from_workspace_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    systems = project / "systems"
    systems.mkdir(parents=True)
    (project / "nodrix.yaml").write_text(
        "schema: nodrix.project/v1\n"
        "name: test\n"
        "defaults:\n"
        "  system: main\n"
        "systems:\n"
        "  main: systems/main.yaml\n",
        encoding="utf-8",
    )
    dump_system(
        SystemModel(
            name="main",
            graphs=(
                Graph(
                    name="main",
                    nodes=(NodeInstance(name="worker", uses="demo.worker"),),
                ),
            ),
        ),
        systems / "main.yaml",
    )

    _FakeBackend.instances.clear()
    monkeypatch.chdir(project)
    monkeypatch.setattr(system_cli, "LocalBackend", _FakeBackend)

    result = runner.invoke(app, ["system", "run"])
    assert result.exit_code == 0, result.output
    assert _FakeBackend.instances[-1].kwargs["working_directory"] == project.resolve()


@_requires_repo_path("environments/rpi5-jazzy.yaml")
def test_rpi5_environment_uses_supported_check_schema() -> None:
    environment = yaml.safe_load(
        (ROOT / "environments/rpi5-jazzy.yaml").read_text(encoding="utf-8")
    )
    assert environment["platform"] == {
        "system": "Linux",
        "architecture": "aarch64",
    }
    assert all("type" in item for item in environment["checks"])
    assert not any("kind" in item for item in environment["checks"])


def test_build_plan_skips_foreign_platform_without_sourcing_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nodrix.workflow_execution as workflow_execution
    from nodrix.workflow_planning import plan_workflow

    (tmp_path / "workflows").mkdir()
    (tmp_path / "environments").mkdir()

    (tmp_path / "nodrix.yaml").write_text(
        "schema: nodrix.project/v1\n"
        "name: foreign-plan\n"
        "defaults:\n"
        "  context: robot\n"
        "contexts:\n"
        "  robot:\n"
        "    environment: ros\n"
        "environments:\n"
        "  ros: environments/ros.yaml\n"
        "workflows:\n"
        "  build: workflows/build.yaml\n",
        encoding="utf-8",
    )
    (tmp_path / "environments/ros.yaml").write_text(
        "schema: nodrix.environment/v1\n"
        "name: ros\n"
        "shell:\n"
        "  source:\n"
        "    - /definitely/missing/ros/setup.bash\n"
        "environment: {}\n"
        "checks: []\n",
        encoding="utf-8",
    )
    (tmp_path / "workflows/build.yaml").write_text(
        "schema: nodrix.workflow/v1\n"
        "name: build\n"
        "steps:\n"
        "  - id: pi-only\n"
        "    run: echo build\n"
        "    when:\n"
        "      system: Linux\n"
        "      architecture: aarch64\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(workflow_execution.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(workflow_execution.platform, "machine", lambda: "arm64")

    result = plan_workflow("build", root=tmp_path)

    assert result.environment == "ros"
    assert len(result.steps) == 1
    assert result.steps[0].status == "skipped"
    assert result.steps[0].reasons == ("system is Darwin",)
