from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.project_foundation import (
    add_project_authoring_asset,
    create_progressive_project,
)
from nodrix.system import load_system


runner = CliRunner()


def _project(
    tmp_path: Path,
    *,
    language: str = "en",
) -> Path:
    root = tmp_path / "robot"

    create_progressive_project(
        root,
        language=language,
    )

    return root


def test_project_init_does_not_create_authoring_directories(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path
    )

    assert not (
        root / "modules"
    ).exists()

    assert not (
        root / "config"
    ).exists()


def test_module_is_created_lazily_without_project_registration(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path
    )

    before = yaml.safe_load(
        (
            root / "nodrix.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    asset = add_project_authoring_asset(
        "module",
        "sensing",
        root=root,
    )

    assert asset.path == (
        root
        / "modules"
        / "sensing.yaml"
    )

    assert asset.path.is_file()

    document = yaml.safe_load(
        asset.path.read_text(
            encoding="utf-8"
        )
    )

    assert document == {
        "schema": "nodrix.system-module/v1",
    }

    after = yaml.safe_load(
        (
            root / "nodrix.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert after == before
    assert "modules" not in after


def test_config_is_created_lazily_without_project_registration(
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

    assert asset.path == (
        root
        / "config"
        / "defaults.yaml"
    )

    assert yaml.safe_load(
        asset.path.read_text(
            encoding="utf-8"
        )
    ) == {}

    project = yaml.safe_load(
        (
            root / "nodrix.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert "config" not in project


def test_generated_module_can_be_imported_by_system(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path
    )

    add_project_authoring_asset(
        "module",
        "sensing",
        root=root,
    )

    systems = root / "systems"
    systems.mkdir()

    system_path = (
        systems / "main.yaml"
    )

    system_path.write_text(
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: main\n"
        "imports:\n"
        "  - ../modules/sensing.yaml\n",
        encoding="utf-8",
    )

    system = load_system(
        system_path
    )

    assert system.name == "main"


def test_authoring_assets_follow_project_language(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path,
        language="ru",
    )

    module = add_project_authoring_asset(
        "module",
        "mapping",
        root=root,
    )

    config = add_project_authoring_asset(
        "config",
        "defaults",
        root=root,
    )

    module_text = module.path.read_text(
        encoding="utf-8"
    )

    config_text = config.path.read_text(
        encoding="utf-8"
    )

    assert "Что это:" in module_text
    assert "переиспользуемая" in module_text

    assert "Что это:" in config_text
    assert "${config.mapping}" in config_text


def test_project_add_module_cli_creates_only_authoring_asset(
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
        ],
    )

    assert result.exit_code == 0, result.output
    assert "authoring asset" in result.output
    assert (
        root
        / "modules"
        / "sensing.yaml"
    ).is_file()

    project = yaml.safe_load(
        (
            root / "nodrix.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert "modules" not in project


def test_project_add_config_cli_creates_only_authoring_asset(
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
        ],
    )

    assert result.exit_code == 0, result.output
    assert "authoring asset" in result.output
    assert (
        root
        / "config"
        / "defaults.yaml"
    ).is_file()


def test_module_and_config_cannot_be_project_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _project(
        tmp_path
    )

    monkeypatch.chdir(
        root
    )

    for kind in (
        "module",
        "config",
    ):
        result = runner.invoke(
            app,
            [
                "project",
                "add",
                kind,
                "example",
                "--default",
            ],
        )

        assert result.exit_code == 1
        assert "--default" in result.output


def test_system_scaffold_teaches_progressive_composition(
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
            "system",
            "main",
        ],
    )

    assert result.exit_code == 0, result.output

    path = (
        root
        / "systems"
        / "main.yaml"
    )

    text = path.read_text(
        encoding="utf-8"
    )

    assert "System Source" in text

    # Adding the System still does not eagerly create unrelated capabilities.
    assert not (
        root / "modules"
    ).exists()

    assert not (
        root / "config"
    ).exists()
