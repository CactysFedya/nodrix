from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.project_foundation import (
    add_project_authoring_asset,
    add_project_resource,
    attach_project_authoring_asset,
    create_progressive_project,
)
from nodrix.system import load_system


runner = CliRunner()


def _project(
    tmp_path: Path,
) -> Path:
    root = tmp_path / "robot"

    create_progressive_project(
        root
    )

    add_project_resource(
        "system",
        "mapping",
        root=root,
        make_default=True,
    )

    return root


def test_module_can_be_attached_to_registered_system(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path
    )

    asset = add_project_authoring_asset(
        "module",
        "sensing",
        root=root,
    )

    attachment = attach_project_authoring_asset(
        asset,
        system="mapping",
    )

    assert attachment.changed is True
    assert attachment.field == "imports"
    assert attachment.reference == (
        "../modules/sensing.yaml"
    )

    system_path = (
        root / "systems/mapping.yaml"
    )

    source = system_path.read_text(
        encoding="utf-8"
    )

    assert "# Nodrix System" in source
    assert "imports:" in source
    assert "  - ../modules/sensing.yaml" in source

    system = load_system(
        system_path
    )

    assert system.name == "mapping"


def test_config_can_be_attached_to_registered_system(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path
    )

    asset = add_project_authoring_asset(
        "config",
        "defaults",
        root=root,
    )

    attachment = attach_project_authoring_asset(
        asset,
        system="mapping",
    )

    assert attachment.changed is True
    assert attachment.field == "config"
    assert attachment.reference == (
        "../config/defaults.yaml"
    )

    source = (
        root / "systems/mapping.yaml"
    ).read_text(
        encoding="utf-8"
    )

    assert "config:" in source
    assert "  - ../config/defaults.yaml" in source


def test_attachment_is_idempotent(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path
    )

    asset = add_project_authoring_asset(
        "module",
        "sensing",
        root=root,
    )

    first = attach_project_authoring_asset(
        asset,
        system="mapping",
    )

    second = attach_project_authoring_asset(
        asset,
        system="mapping",
    )

    assert first.changed is True
    assert second.changed is False

    source = (
        root / "systems/mapping.yaml"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        source.count(
            "../modules/sensing.yaml"
        )
        == 1
    )


def test_attachment_preserves_system_scaffold_comments(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path
    )

    system_path = (
        root / "systems/mapping.yaml"
    )

    before = system_path.read_text(
        encoding="utf-8"
    )

    assert "# Nodrix System" in before
    assert "# Typical next sections:" in before

    asset = add_project_authoring_asset(
        "config",
        "defaults",
        root=root,
    )

    attach_project_authoring_asset(
        asset,
        system="mapping",
    )

    after = system_path.read_text(
        encoding="utf-8"
    )

    assert "# Nodrix System" in after
    assert "# Typical next sections:" in after


def test_module_and_config_can_both_be_attached(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path
    )

    module = add_project_authoring_asset(
        "module",
        "sensing",
        root=root,
    )

    config = add_project_authoring_asset(
        "config",
        "defaults",
        root=root,
    )

    attach_project_authoring_asset(
        module,
        system="mapping",
    )

    attach_project_authoring_asset(
        config,
        system="mapping",
    )

    document = yaml.safe_load(
        (
            root / "systems/mapping.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert document["imports"] == [
        "../modules/sensing.yaml",
    ]

    assert document["config"] == [
        "../config/defaults.yaml",
    ]


def test_project_add_module_system_creates_and_attaches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _project(
        tmp_path
    )

    monkeypatch.chdir(
        root
    )

    result = runner.invoke(
        app,
        [
            "project",
            "add",
            "module",
            "sensing",
            "--system",
            "mapping",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Attached" in result.output

    assert (
        root / "modules/sensing.yaml"
    ).is_file()

    document = yaml.safe_load(
        (
            root / "systems/mapping.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert document["imports"] == [
        "../modules/sensing.yaml",
    ]


def test_project_add_config_system_creates_and_attaches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _project(
        tmp_path
    )

    monkeypatch.chdir(
        root
    )

    result = runner.invoke(
        app,
        [
            "project",
            "add",
            "config",
            "defaults",
            "--system",
            "mapping",
        ],
    )

    assert result.exit_code == 0, result.output

    document = yaml.safe_load(
        (
            root / "systems/mapping.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert document["config"] == [
        "../config/defaults.yaml",
    ]


def test_unknown_system_does_not_leave_asset_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _project(
        tmp_path
    )

    monkeypatch.chdir(
        root
    )

    result = runner.invoke(
        app,
        [
            "project",
            "add",
            "module",
            "orphan",
            "--system",
            "missing",
        ],
    )

    assert result.exit_code == 1

    assert not (
        root / "modules/orphan.yaml"
    ).exists()


def test_system_option_is_rejected_for_registered_resources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _project(
        tmp_path
    )

    monkeypatch.chdir(
        root
    )

    result = runner.invoke(
        app,
        [
            "project",
            "add",
            "workflow",
            "build",
            "--system",
            "mapping",
        ],
    )

    assert result.exit_code == 1
    assert "only for Module or Config" in result.output


def test_multiple_modules_append_to_existing_imports(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path
    )

    sensing = add_project_authoring_asset(
        "module",
        "sensing",
        root=root,
    )

    health = add_project_authoring_asset(
        "module",
        "health",
        root=root,
    )

    first = attach_project_authoring_asset(
        sensing,
        system="mapping",
    )

    second = attach_project_authoring_asset(
        health,
        system="mapping",
    )

    assert first.changed is True
    assert second.changed is True

    system_path = (
        root / "systems/mapping.yaml"
    )

    document = yaml.safe_load(
        system_path.read_text(
            encoding="utf-8"
        )
    )

    assert document["imports"] == [
        "../modules/sensing.yaml",
        "../modules/health.yaml",
    ]

    rendered = system_path.read_text(
        encoding="utf-8"
    )

    assert (
        "imports:\n"
        "  - ../modules/sensing.yaml\n"
        "  - ../modules/health.yaml\n"
        in rendered
    )

    assert (
        "\n\n  - ../modules/health.yaml"
        not in rendered
    )

    # The resulting composed System must still be directly loadable.
    system = load_system(
        system_path
    )

    assert system.name == "mapping"

    # The comment-rich self-describing source must survive mutation.
    source = system_path.read_text(
        encoding="utf-8"
    )

    assert "# Nodrix System" in source
