from __future__ import annotations

from pathlib import Path

from nodrix.profiles import runtime_preset_names


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (
        ROOT
        / path
    ).read_text(
        encoding="utf-8"
    )


def test_optimization_pipeline_identity_is_compatibility_scoped() -> None:
    text = _read(
        "src/nodrix/optimization_operation.py"
    )

    assert (
        "2.x Pipeline Definition"
        in text
    )

    assert (
        "canonical pipeline identity"
        not in text.lower()
    )


def test_pipeline_profile_cli_help_uses_runtime_preset_semantics() -> None:
    for filename in (
        "src/nodrix/cli_dev_commands.py",
        "src/nodrix/cli_project_commands.py",
    ):
        text = _read(filename)

        assert (
            "Pipeline RuntimePreset"
            in text
        )

        assert (
            "manifest performance profile"
            not in text
        )


def test_workspace_tutorial_uses_real_runtime_preset_name() -> None:
    assert (
        "realtime-balanced"
        in runtime_preset_names()
    )

    for filename in (
        "docs/tutorials/workspace-operations.md",
        "docs/ru/tutorials/workspace-operations.md",
    ):
        text = _read(filename)

        assert (
            "runtime_profile: realtime-balanced"
            in text
        )

        assert (
            "runtime_profile: balanced"
            not in text
        )


def test_legacy_profile_option_remains_available_in_source_contract() -> None:
    text = (
        _read("src/nodrix/cli_dev_commands.py")
        + _read("src/nodrix/cli_project_commands.py")
        + _read("src/nodrix/cli_operation_commands.py")
    )

    assert "--profile" in text
