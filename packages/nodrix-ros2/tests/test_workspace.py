from pathlib import Path

from nodrix_ros2.workspace import (
    RosBuildSpec,
    RosWorkspaceSpec,
    build_command,
    capture_sourced_environment,
    resolve_setup_file,
    workspace_fingerprint,
    RosWorkspaceManager,
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
