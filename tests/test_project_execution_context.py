from __future__ import annotations

from pathlib import Path

from nodrix.workspace import (
    ProjectExecutionContext,
    resolve_pipeline_reference,
    resolve_project_execution_context,
)


def _write(
    path: Path,
    text: str,
) -> Path:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        text,
        encoding="utf-8",
    )
    return path


def _project(
    root: Path,
) -> None:
    _write(
        root / "nodrix.yaml",
        "schema: nodrix.project/v1\n"
        "name: demo\n"
        "\n"
        "defaults:\n"
        "  pipeline: demo\n"
        "  context: robot\n"
        "  view: compact\n"
        "\n"
        "pipelines:\n"
        "  demo: pipeline.yaml\n"
        "\n"
        "contexts:\n"
        "  robot:\n"
        "    environment: ros2\n"
        "    profile: mid360s\n"
        "    view: operations\n"
        "    variables:\n"
        "      SHARED: context\n"
        "      CONTEXT_ONLY: yes\n"
        "\n"
        "environments:\n"
        "  ros2: environments/ros2.yaml\n"
        "  local: environments/local.yaml\n"
        "\n"
        "profiles:\n"
        "  mid360s: profiles/mid360s.yaml\n"
        "  debug: profiles/debug.yaml\n",
    )

    _write(
        root / "pipeline.yaml",
        "{}\n",
    )

    _write(
        root / "environments/ros2.yaml",
        "schema: nodrix.environment/v1\n"
        "name: ros2\n"
        "shell:\n"
        "  source:\n"
        "    - ${PROJECT_ROOT}/env/setup.bash\n"
        "environment:\n"
        "  ROS_DISTRO: jazzy\n"
        "  SHARED: environment\n"
        "checks:\n"
        "  - type: command\n"
        "    command: ros2 --help\n",
    )

    _write(
        root / "environments/local.yaml",
        "schema: nodrix.environment/v1\n"
        "name: local\n"
        "environment:\n"
        "  LOCAL_ONLY: yes\n",
    )

    _write(
        root / "profiles/mid360s.yaml",
        "schema: nodrix.profile/v1\n"
        "name: mid360s\n"
        "runtime_profile: realtime-low-latency\n"
        "variables:\n"
        "  FASTLIO_CONFIG_FILE: mid360s_handheld.yaml\n"
        "  SHARED: profile\n",
    )

    _write(
        root / "profiles/debug.yaml",
        "schema: nodrix.profile/v1\n"
        "name: debug\n"
        "runtime_profile: debug\n"
        "variables:\n"
        "  DEBUG_PROFILE: enabled\n",
    )


def test_project_execution_context_is_pipeline_neutral(
    tmp_path: Path,
) -> None:
    _project(
        tmp_path
    )

    resolved = resolve_project_execution_context(
        tmp_path
    )

    assert isinstance(
        resolved,
        ProjectExecutionContext,
    )

    assert not hasattr(
        resolved,
        "pipeline",
    )

    assert not hasattr(
        resolved,
        "pipeline_name",
    )

    assert resolved.context_name == "robot"
    assert resolved.environment_name == "ros2"
    assert resolved.profile_name == "mid360s"
    assert resolved.view == "operations"

    assert resolved.runtime_preset == (
        "realtime-low-latency"
    )


def test_execution_context_preserves_variable_precedence(
    tmp_path: Path,
) -> None:
    _project(
        tmp_path
    )

    resolved = resolve_project_execution_context(
        tmp_path
    )

    assert resolved.variables == {
        "ROS_DISTRO": "jazzy",
        "SHARED": "context",
        "FASTLIO_CONFIG_FILE": (
            "mid360s_handheld.yaml"
        ),
        "CONTEXT_ONLY": "True",
    }


def test_execution_context_preserves_environment_sources_and_checks(
    tmp_path: Path,
) -> None:
    _project(
        tmp_path
    )

    resolved = resolve_project_execution_context(
        tmp_path
    )

    assert resolved.sources == (
        (
            tmp_path
            / "env/setup.bash"
        ).resolve(),
    )

    assert resolved.checks == (
        {
            "type": "command",
            "command": "ros2 --help",
        },
    )


def test_explicit_profile_overrides_context_profile(
    tmp_path: Path,
) -> None:
    _project(
        tmp_path
    )

    resolved = resolve_project_execution_context(
        tmp_path,
        profile="debug",
    )

    assert resolved.context_name == "robot"
    assert resolved.environment_name == "ros2"
    assert resolved.profile_name == "debug"

    assert resolved.runtime_preset == "debug"

    assert resolved.variables[
        "DEBUG_PROFILE"
    ] == "enabled"

    assert (
        "FASTLIO_CONFIG_FILE"
        not in resolved.variables
    )


def test_legacy_workspace_uses_same_execution_context_semantics(
    tmp_path: Path,
) -> None:
    _project(
        tmp_path
    )

    execution = resolve_project_execution_context(
        tmp_path
    )

    workspace = resolve_pipeline_reference(
        None,
        start=tmp_path,
    )

    assert workspace.context_name == (
        execution.context_name
    )

    assert workspace.environment_name == (
        execution.environment_name
    )

    assert workspace.profile_name == (
        execution.profile_name
    )

    assert workspace.view == execution.view

    assert workspace.runtime_profile == (
        execution.runtime_preset
    )

    assert workspace.variables == (
        execution.variables
    )

    assert workspace.sources == (
        execution.sources
    )

    assert workspace.checks == (
        execution.checks
    )
