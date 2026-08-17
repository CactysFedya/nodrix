from __future__ import annotations

from pathlib import Path

import pytest

from nodrix.system.definition import (
    system_definition_digest,
)
from nodrix.system.io import load_system
from nodrix.system.source import (
    SystemSourceError,
    resolve_system_source_document,
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


def test_exact_config_reference_preserves_type(
    tmp_path: Path,
) -> None:
    config = _write(
        tmp_path / "config/defaults.yaml",
        "runtime:\n"
        "  threads: 4\n"
        "  enabled: true\n",
    )

    system_path = _write(
        tmp_path / "systems/robot.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "config:\n"
        "  - ../config/defaults.yaml\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n"
        "    properties:\n"
        '      threads: "${config.runtime.threads}"\n'
        '      enabled: "${config.runtime.enabled}"\n',
    )

    resolved = resolve_system_source_document(
        {
            "apiVersion": "nodrix.system/v1",
            "kind": "System",
            "name": "robot",
            "config": [
                "../config/defaults.yaml",
            ],
            "targets": [
                {
                    "name": "pi5",
                    "kind": "host",
                    "properties": {
                        "threads": "${config.runtime.threads}",
                        "enabled": "${config.runtime.enabled}",
                    },
                }
            ],
        },
        source=system_path,
    )

    properties = (
        resolved.document["targets"][0]["properties"]
    )

    assert properties["threads"] == 4
    assert isinstance(
        properties["threads"],
        int,
    )

    assert properties["enabled"] is True
    assert resolved.sources == (
        system_path.resolve(),
        config.resolve(),
    )

    system = load_system(
        system_path
    )

    assert (
        system.targets[0].properties["threads"]
        == 4
    )


def test_system_module_can_consume_root_config(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "config/defaults.yaml",
        "hardware:\n"
        "  architecture: aarch64\n",
    )

    _write(
        tmp_path / "modules/target.yaml",
        "schema: nodrix.system-module/v1\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n"
        "    properties:\n"
        '      architecture: "${config.hardware.architecture}"\n',
    )

    system_path = _write(
        tmp_path / "systems/robot.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "imports:\n"
        "  - ../modules/target.yaml\n"
        "config:\n"
        "  - ../config/defaults.yaml\n",
    )

    system = load_system(
        system_path
    )

    assert (
        system.targets[0]
        .properties["architecture"]
        == "aarch64"
    )


def test_unknown_config_reference_is_rejected(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "config/defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.1\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "config: [config/defaults.yaml]\n"
        "metadata:\n"
        '  value: "${config.mapping.missing}"\n',
    )

    with pytest.raises(
        SystemSourceError,
        match="Unknown System Config path",
    ):
        load_system(
            system_path
        )


def test_embedded_config_interpolation_is_rejected(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "config/defaults.yaml",
        "robot:\n"
        "  name: pi5\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "config: [config/defaults.yaml]\n"
        "metadata:\n"
        '  value: "robot-${config.robot.name}"\n',
    )

    with pytest.raises(
        SystemSourceError,
        match="Embedded System Config interpolation",
    ):
        load_system(
            system_path
        )


def test_config_binding_does_not_change_semantic_identity(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "config/defaults.yaml",
        "runtime:\n"
        "  threads: 4\n",
    )

    configured_path = _write(
        tmp_path / "configured.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "config: [config/defaults.yaml]\n"
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
        "      threads: 4\n",
    )

    configured = load_system(
        configured_path
    )

    literal = load_system(
        literal_path
    )

    assert (
        system_definition_digest(configured)
        == system_definition_digest(literal)
    )
