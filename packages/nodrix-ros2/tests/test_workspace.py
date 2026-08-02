from pathlib import Path

from nodrix_ros2.workspace import (
    RosBuildSpec,
    RosWorkspaceSpec,
    build_command,
    capture_sourced_environment,
    resolve_setup_file,
    workspace_fingerprint,
    RosWorkspaceManager,
    base_ros_environment,
)
import pytest


def test_setup_environment_is_captured_without_mutating_parent(tmp_path: Path) -> None:
    underlay = tmp_path / "underlay"
    underlay.mkdir()
    setup = underlay / "setup.bash"
    setup.write_text("export ROS_DISTRO=jazzy\nexport TEST_NODRIX_ROS2=ready\n")

    assert resolve_setup_file(underlay) == setup
    environment = capture_sourced_environment((setup,), base_environment={"PATH": "/usr/bin:/bin"})
    assert environment["ROS_DISTRO"] == "jazzy"
    assert environment["TEST_NODRIX_ROS2"] == "ready"


def test_workspace_fingerprint_changes_with_source(tmp_path: Path) -> None:
    package = tmp_path / "src" / "demo"
    package.mkdir(parents=True)
    source = package / "node.cpp"
    source.write_text("int main() { return 0; }\n")
    first = workspace_fingerprint(tmp_path, strict=True)
    source.write_text("int main() { return 1; }\n")
    second = workspace_fingerprint(tmp_path, strict=True)
    assert first != second


def test_build_command_is_deterministic() -> None:
    spec = RosBuildSpec(
        symlink_install=True,
        packages_up_to=("fast_livo",),
        parallel_workers=4,
    )
    assert build_command(spec) == (
        "colcon",
        "build",
        "--symlink-install",
        "--parallel-workers",
        "4",
        "--packages-up-to",
        "fast_livo",
    )


def test_default_workspace_uses_ros_distro_underlay() -> None:
    spec = RosWorkspaceSpec.from_mapping({"distro": "jazzy"})
    assert str(spec.underlays[0]) == "/opt/ros/jazzy"


def test_relative_workspace_and_underlay_resolve_from_project(tmp_path: Path) -> None:
    spec = RosWorkspaceSpec.from_mapping(
        {"path": "robot_ws", "underlays": ["ros_underlay"]},
        base_dir=tmp_path,
    )
    assert spec.path == (tmp_path / "robot_ws").resolve()
    assert spec.underlays == ((tmp_path / "ros_underlay").resolve(),)


def test_runtime_does_not_source_underlay_twice(tmp_path: Path) -> None:
    underlay = tmp_path / "underlay"
    workspace = tmp_path / "workspace"
    (workspace / "install").mkdir(parents=True)
    underlay.mkdir()
    (underlay / "setup.bash").write_text(
        "export NODRIX_SOURCE_COUNT=$(( ${NODRIX_SOURCE_COUNT:-0} + 1 ))\n",
        encoding="utf-8",
    )
    (workspace / "install" / "setup.bash").write_text(
        "export NODRIX_INSTALL_SEES_COUNT=${NODRIX_SOURCE_COUNT}\n",
        encoding="utf-8",
    )
    spec = RosWorkspaceSpec.from_mapping(
        {
            "underlays": [str(underlay)],
            "path": str(workspace),
            "build": {"mode": "never"},
        }
    )
    prepared = RosWorkspaceManager(spec).prepare()
    assert prepared.environment["NODRIX_SOURCE_COUNT"] == "1"
    assert prepared.environment["NODRIX_INSTALL_SEES_COUNT"] == "1"


def test_base_environment_requires_explicit_secret_pass(monkeypatch) -> None:
    monkeypatch.setenv("NODRIX_PRIVATE_TOKEN", "secret")
    assert "NODRIX_PRIVATE_TOKEN" not in base_ros_environment()
    assert base_ros_environment(pass_names=("NODRIX_PRIVATE_TOKEN",))[
        "NODRIX_PRIVATE_TOKEN"
    ] == "secret"


def test_project_trust_rejects_workspace_outside_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    workspace = tmp_path / "outside"
    project.mkdir()
    workspace.mkdir()
    spec = RosWorkspaceSpec.from_mapping(
        {
            "path": str(workspace),
            "trust": "project",
            "build": {"mode": "never"},
        }
    )
    manager = RosWorkspaceManager(spec, project_dir=project)
    with pytest.raises(PermissionError, match="outside the Nodrix project"):
        manager.prepare()


def test_readonly_workspace_cannot_build(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = RosWorkspaceSpec.from_mapping(
        {"path": str(workspace), "trust": "readonly"}
    )
    with pytest.raises(PermissionError, match="build.mode=never"):
        RosWorkspaceManager(spec).prepare()
