from __future__ import annotations

from pathlib import Path

from nodrix.project_system import (
    system_execution_context_from_project,
)
from nodrix.system.execution_context import (
    SystemExecutionContext,
    SystemExecutionContextOverride,
    apply_system_execution_context_override,
    child_system_execution_context,
    system_execution_context_digest,
    system_execution_context_document,
)
from nodrix.workspace import ProjectExecutionContext


def _project_context(
    tmp_path: Path,
    *,
    context_name: str = "robot",
    environment_name: str = "ros2",
    profile_name: str = "mid360s",
    view: str = "operations",
    runtime_preset: str | None = (
        "realtime-low-latency"
    ),
) -> ProjectExecutionContext:
    return ProjectExecutionContext(
        root=tmp_path,
        config_path=tmp_path / "nodrix.yaml",
        config={},
        context_name=context_name,
        environment_name=environment_name,
        profile_name=profile_name,
        view=view,
        runtime_preset=runtime_preset,
        variables={
            "ROS_DISTRO": "jazzy",
            "FASTLIO_CONFIG_FILE": (
                "mid360s_handheld.yaml"
            ),
        },
        sources=(
            tmp_path / "setup.bash",
        ),
        checks=(
            {
                "type": "command",
                "command": "ros2 --help",
            },
        ),
    )


def test_project_context_resolves_system_execution_semantics(
    tmp_path: Path,
) -> None:
    project = _project_context(
        tmp_path
    )

    context = (
        system_execution_context_from_project(
            project
        )
    )

    assert isinstance(
        context,
        SystemExecutionContext,
    )

    assert context.variables == {
        "ROS_DISTRO": "jazzy",
        "FASTLIO_CONFIG_FILE": (
            "mid360s_handheld.yaml"
        ),
    }

    assert context.sources == (
        str(tmp_path / "setup.bash"),
    )

    assert context.runtime[
        "mode"
    ] == "realtime"

    assert context.runtime[
        "engine"
    ] == "unified"


def test_project_selection_names_do_not_enter_execution_semantics(
    tmp_path: Path,
) -> None:
    first = _project_context(
        tmp_path,
        context_name="robot",
        environment_name="ros2",
        profile_name="mid360s",
        view="operations",
    )

    second = _project_context(
        tmp_path,
        context_name="field",
        environment_name="another-env",
        profile_name="another-profile",
        view="compact",
    )

    first_system = (
        system_execution_context_from_project(
            first
        )
    )

    second_system = (
        system_execution_context_from_project(
            second
        )
    )

    assert first_system == second_system

    assert (
        system_execution_context_digest(
            first_system
        )
        == system_execution_context_digest(
            second_system
        )
    )


def test_checks_and_view_are_not_execution_plan_semantics(
    tmp_path: Path,
) -> None:
    project = _project_context(
        tmp_path
    )

    context = (
        system_execution_context_from_project(
            project
        )
    )

    document = (
        system_execution_context_document(
            context
        )
    )

    assert "checks" not in document
    assert "view" not in document
    assert "context_name" not in document
    assert "environment_name" not in document
    assert "profile_name" not in document
    assert "runtime_preset" not in document


def test_runtime_preset_is_resolved_before_system_execution(
    tmp_path: Path,
) -> None:
    project = _project_context(
        tmp_path,
        runtime_preset="debug",
    )

    context = (
        system_execution_context_from_project(
            project
        )
    )

    assert context.runtime[
        "mode"
    ] == "offline"

    assert context.runtime[
        "type_validation"
    ] == "always"

    document = (
        system_execution_context_document(
            context
        )
    )

    assert "debug" not in document.values()


def test_execution_context_digest_changes_with_effective_semantics(
    tmp_path: Path,
) -> None:
    first = _project_context(
        tmp_path,
        runtime_preset=(
            "realtime-low-latency"
        ),
    )

    second = _project_context(
        tmp_path,
        runtime_preset="debug",
    )

    assert (
        system_execution_context_digest(
            system_execution_context_from_project(
                first
            )
        )
        != system_execution_context_digest(
            system_execution_context_from_project(
                second
            )
        )
    )


def test_empty_project_runtime_preset_produces_empty_runtime_defaults(
    tmp_path: Path,
) -> None:
    project = _project_context(
        tmp_path,
        runtime_preset=None,
    )

    context = (
        system_execution_context_from_project(
            project
        )
    )

    assert context.runtime == {}
    assert context.node_defaults == {}
    assert context.edge_defaults == {}
    assert context.stream_defaults == {}


def test_child_execution_context_inherits_and_deep_merges_override() -> None:
    context = SystemExecutionContext(
        variables={"ROS_DISTRO": "jazzy", "MODE": "base"},
        sources=("/opt/ros/jazzy/setup.bash",),
        runtime={"mode": "realtime", "limits": {"cpu": 2}},
        systems={
            "mapping": SystemExecutionContextOverride(
                variables={"MODE": "mapping"},
                sources=("/workspace/install/setup.bash",),
                runtime={"limits": {"memory": "2G"}},
                systems={
                    "worker": SystemExecutionContextOverride(
                        variables={"THREADS": "4"},
                    ),
                },
            ),
        },
    )

    child = child_system_execution_context(context, "mapping")

    assert child is not None
    assert child.variables == {
        "ROS_DISTRO": "jazzy",
        "MODE": "mapping",
    }
    assert child.sources == (
        "/opt/ros/jazzy/setup.bash",
        "/workspace/install/setup.bash",
    )
    assert child.runtime == {
        "mode": "realtime",
        "limits": {
            "cpu": 2,
            "memory": "2G",
        },
    }
    assert set(child.systems) == {"worker"}


def test_execution_context_override_can_disable_inheritance() -> None:
    context = SystemExecutionContext(
        variables={"SECRET": "parent"},
        runtime={"mode": "realtime"},
    )
    isolated = apply_system_execution_context_override(
        context,
        SystemExecutionContextOverride(
            inherit=False,
            variables={"MODE": "isolated"},
        ),
    )

    assert isolated.variables == {"MODE": "isolated"}
    assert isolated.runtime == {}


def test_empty_system_context_tree_preserves_previous_digest_shape() -> None:
    context = SystemExecutionContext(
        variables={"MODE": "mapping"},
    )
    document = system_execution_context_document(context)

    assert "systems" not in document
    assert system_execution_context_digest(context) == (
        system_execution_context_digest(
            context.model_copy(update={"systems": {}})
        )
    )
