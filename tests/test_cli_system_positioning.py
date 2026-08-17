from __future__ import annotations

from nodrix.cli_context import (
    app,
    block_app,
    config_app,
    fragment_app,
)
from nodrix.cli_foundation_commands import (
    project_app,
)


def test_root_cli_is_system_positioned() -> None:
    help_text = app.info.help or ""

    assert (
        "Executable system architecture"
        in help_text
    )

    assert (
        "Pipeline OS"
        not in help_text
    )


def test_project_cli_is_system_first() -> None:
    help_text = (
        project_app.info.help
        or ""
    )

    assert (
        "canonical Systems"
        in help_text
    )


def test_runtime_configuration_uses_runtime_preset_terminology() -> None:
    help_text = (
        config_app.info.help
        or ""
    )

    assert (
        "runtime presets"
        in help_text
    )


def test_pipeline_block_cli_is_explicitly_compatibility_scoped() -> None:
    help_text = (
        block_app.info.help
        or ""
    )

    assert (
        "2.x Pipeline"
        in help_text
    )


def test_pipeline_fragment_cli_does_not_claim_generic_fragment_semantics() -> None:
    help_text = (
        fragment_app.info.help
        or ""
    )

    assert (
        "2.x Pipeline"
        in help_text
    )
