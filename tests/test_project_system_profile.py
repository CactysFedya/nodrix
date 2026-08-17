from __future__ import annotations

from pathlib import Path

import yaml

from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
)
from nodrix.project_system import (
    load_project_system_details,
    resolve_project_profile_overlay,
)
from nodrix.system.definition import (
    system_definition_digest,
)
from nodrix.system.io import load_system


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


def test_project_profile_config_overlays_system_config(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "rpi5",
        root=tmp_path,
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

    defaults = _write(
        tmp_path / "config/defaults.yaml",
        "runtime:\n"
        "  threads: 4\n"
        "  mode: normal\n",
    )

    system_path = _write(
        tmp_path / "systems/mapping.yaml",
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
    )

    details = load_project_system_details(
        system_path,
        profile="rpi5",
        root=tmp_path,
    )

    target = details.system.targets[0]

    assert target.properties == {
        "threads": 8,
        "mode": "normal",
    }

    assert details.resolution.config_sources == (
        defaults.resolve(),
    )

    assert (
        details.resolution.config_overlay_sources
        == (
            profile.path.resolve(),
        )
    )

    assert details.resolution.config_provenance[
        "runtime.threads"
    ] == profile.path.resolve()

    assert details.resolution.config_provenance[
        "runtime.mode"
    ] == defaults.resolve()


def test_profile_non_config_fields_do_not_enter_system(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "field",
        root=tmp_path,
    )

    profile.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.profile/v1",
                "name": "field",
                "variables": {
                    "SECRET_PROFILE_VALUE": "outside-system",
                },
                "runtime_profile": (
                    "realtime-low-latency"
                ),
                "config": {
                    "robot": {
                        "mode": "field",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "metadata:\n"
        '  mode: "${config.robot.mode}"\n',
    )

    details = load_project_system_details(
        system_path,
        profile="field",
        root=tmp_path,
    )

    canonical_text = str(
        details.canonical
    )

    assert details.system.metadata == {
        "mode": "field",
    }

    assert "SECRET_PROFILE_VALUE" not in canonical_text
    assert "realtime-low-latency" not in canonical_text
    assert "variables" not in details.canonical
    assert "runtime_profile" not in details.canonical


def test_profile_source_does_not_change_system_identity(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "rpi5",
        root=tmp_path,
    )

    profile.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.profile/v1",
                "name": "rpi5",
                "variables": {},
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

    configured_path = _write(
        tmp_path / "configured.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n"
        "    properties:\n"
        '      threads: "${config.runtime.threads}"\n',
    )

    literal_path = _write(
        tmp_path / "literal.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n"
        "    properties:\n"
        "      threads: 8\n",
    )

    configured = load_project_system_details(
        configured_path,
        profile="rpi5",
        root=tmp_path,
    ).system

    literal = load_system(
        literal_path
    )

    assert (
        system_definition_digest(
            configured
        )
        == system_definition_digest(
            literal
        )
    )


def test_project_profile_adapter_produces_generic_overlay(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "robot",
        root=tmp_path,
    )

    profile.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.profile/v1",
                "name": "robot",
                "variables": {},
                "config": {
                    "mapping": {
                        "voxel_size_m": 0.1,
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    overlay = resolve_project_profile_overlay(
        "robot",
        root=tmp_path,
    )

    assert overlay.config == {
        "mapping": {
            "voxel_size_m": 0.1,
        },
    }

    assert overlay.source == profile.path
