from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
)
from nodrix.project_system import (
    load_project_system_details,
)
from nodrix.system import plan_system


runner = CliRunner()


def _project(
    root: Path,
) -> tuple[Path, Path, Path]:
    create_progressive_project(
        root
    )

    profile = add_project_resource(
        "profile",
        "rpi5",
        root=root,
    )

    profile.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.profile/v1",
                "name": "rpi5",
                "variables": {
                    "ROBOT_MODEL": "rpi5",
                },
                "runtime_profile": (
                    "realtime-low-latency"
                ),
                "config": {
                    "runtime": {
                        "threads": 8,
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = root / "config/defaults.yaml"
    config.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    config.write_text(
        "runtime:\n"
        "  threads: 4\n"
        "  mode: normal\n",
        encoding="utf-8",
    )

    system = root / "systems/mapping.yaml"
    system.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    system.write_text(
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: mapping\n"
        "config:\n"
        "  - ../config/defaults.yaml\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n"
        "    properties:\n"
        '      threads: "${config.runtime.threads}"\n'
        '      mode: "${config.runtime.mode}"\n',
        encoding="utf-8",
    )

    return (
        system,
        profile.path,
        config,
    )


def test_system_show_profile_applies_project_profile_config(
    tmp_path: Path,
) -> None:
    system, _, _ = _project(
        tmp_path
    )

    result = runner.invoke(
        app,
        [
            "system",
            "show",
            str(system),
            "--profile",
            "rpi5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output

    payload = json.loads(
        result.stdout
    )

    assert payload["targets"][0]["properties"] == {
        "threads": 8,
        "mode": "normal",
    }

    serialized = json.dumps(
        payload
    )

    assert "rpi5" not in serialized
    assert "runtime_profile" not in serialized
    assert "ROBOT_MODEL" not in serialized


def test_system_show_profile_resolution_reports_overlay(
    tmp_path: Path,
) -> None:
    system, profile, config = _project(
        tmp_path
    )

    result = runner.invoke(
        app,
        [
            "system",
            "show",
            str(system),
            "--profile",
            "rpi5",
            "--json",
            "--resolution",
        ],
    )

    assert result.exit_code == 0, result.output

    payload = json.loads(
        result.stdout
    )

    resolution = payload[
        "resolution"
    ]

    assert resolution[
        "configSources"
    ] == [
        str(config.resolve()),
    ]

    assert resolution[
        "configOverlaySources"
    ] == [
        str(profile.resolve()),
    ]

    assert resolution[
        "configProvenance"
    ][
        "runtime.threads"
    ] == str(
        profile.resolve()
    )

    assert resolution[
        "configProvenance"
    ][
        "runtime.mode"
    ] == str(
        config.resolve()
    )


def test_system_show_profile_resolution_renders_overlay(
    tmp_path: Path,
) -> None:
    system, _, _ = _project(
        tmp_path
    )

    result = runner.invoke(
        app,
        [
            "system",
            "show",
            str(system),
            "--profile",
            "rpi5",
            "--resolution",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "CONFIG OVERLAY" in result.output


def test_system_plan_profile_uses_resolved_system(
    tmp_path: Path,
) -> None:
    system, _, _ = _project(
        tmp_path
    )

    result = runner.invoke(
        app,
        [
            "system",
            "plan",
            str(system),
            "--profile",
            "rpi5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output

    payload = json.loads(
        result.stdout
    )

    expected_system = (
        load_project_system_details(
            system,
            profile="rpi5",
            root=tmp_path,
        )
        .system
    )

    expected = plan_system(
        expected_system
    ).model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
    )

    assert payload == expected


def test_system_profile_requires_project_context(
    tmp_path: Path,
) -> None:
    system = tmp_path / "standalone.yaml"

    system.write_text(
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: standalone\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "system",
            "show",
            str(system),
            "--profile",
            "rpi5",
            "--json",
        ],
    )

    assert result.exit_code == 1
    assert "--profile requires" in result.output


def test_system_profile_help_uses_project_profile_semantics() -> None:
    for command in (
        "show",
        "plan",
    ):
        result = runner.invoke(
            app,
            [
                "system",
                command,
                "--help",
            ],
        )

        assert result.exit_code == 0
        assert "--profile" in result.output
        assert "Project Profile" in result.output
        assert "RuntimePreset" in result.output
