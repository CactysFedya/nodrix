from __future__ import annotations

from pathlib import Path

import pytest

from nodrix.system.source import (
    SystemConfigOverlay,
    SystemSourceError,
    apply_system_config_overlay,
    apply_system_config_overlays,
    resolve_system_config,
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


def test_overlay_has_higher_precedence_than_config_files(
    tmp_path: Path,
) -> None:
    defaults = _write(
        tmp_path / "config/defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.2\n"
        "  point_stride: 4\n"
        "  max_voxels: 5000000\n",
    )

    profile = tmp_path / "profiles/rpi5.yaml"

    resolved = resolve_system_config(
        defaults,
    )

    resolved = apply_system_config_overlay(
        resolved,
        SystemConfigOverlay(
            config={
                "mapping": {
                    "voxel_size_m": 0.1,
                    "point_stride": 1,
                },
            },
            source=profile,
        ),
    )

    assert resolved.config == {
        "mapping": {
            "voxel_size_m": 0.1,
            "point_stride": 1,
            "max_voxels": 5000000,
        },
    }

    assert resolved.source_for(
        "mapping.max_voxels"
    ) == defaults.resolve()

    assert resolved.source_for(
        "mapping.voxel_size_m"
    ) == profile.resolve()

    assert resolved.source_for(
        "mapping.point_stride"
    ) == profile.resolve()

    assert resolved.sources == (
        defaults.resolve(),
    )

    assert resolved.overlay_sources == (
        profile.resolve(),
    )


def test_multiple_overlays_apply_in_declared_order(
    tmp_path: Path,
) -> None:
    first = tmp_path / "profiles/rpi5.yaml"
    second = tmp_path / "contexts/field.yaml"

    resolved = apply_system_config_overlays(
        resolve_system_config(None),
        [
            SystemConfigOverlay(
                config={
                    "mapping": {
                        "voxel_size_m": 0.1,
                        "point_stride": 1,
                    },
                },
                source=first,
            ),
            SystemConfigOverlay(
                config={
                    "mapping": {
                        "point_stride": 2,
                    },
                },
                source=second,
            ),
        ],
    )

    assert resolved.config == {
        "mapping": {
            "voxel_size_m": 0.1,
            "point_stride": 2,
        },
    }

    assert resolved.source_for(
        "mapping.voxel_size_m"
    ) == first.resolve()

    assert resolved.source_for(
        "mapping.point_stride"
    ) == second.resolve()

    assert resolved.overlay_sources == (
        first.resolve(),
        second.resolve(),
    )


def test_empty_overlay_does_not_steal_provenance(
    tmp_path: Path,
) -> None:
    defaults = _write(
        tmp_path / "defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.1\n",
    )

    resolved = resolve_system_config(
        defaults
    )

    overlaid = apply_system_config_overlay(
        resolved,
        SystemConfigOverlay(
            config={},
            source=tmp_path / "profile.yaml",
        ),
    )

    assert overlaid.config == resolved.config

    assert overlaid.source_for(
        "mapping.voxel_size_m"
    ) == defaults.resolve()


def test_overlay_uses_same_config_key_validation(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        SystemSourceError,
        match=r"must not contain '\.'",
    ):
        apply_system_config_overlay(
            resolve_system_config(None),
            SystemConfigOverlay(
                config={
                    "mapping.voxel_size_m": 0.1,
                },
                source=tmp_path / "profile.yaml",
            ),
        )


def test_source_resolution_binds_values_after_overlays(
    tmp_path: Path,
) -> None:
    defaults = _write(
        tmp_path / "config/defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.2\n"
        "  point_stride: 4\n",
    )

    system_path = tmp_path / "systems/mapping.yaml"

    raw = {
        "apiVersion": "nodrix.system/v1",
        "kind": "System",
        "name": "mapping",
        "config": [
            "../config/defaults.yaml",
        ],
        "applications": [
            {
                "name": "mapper",
                "uses": "mapping.voxel_map",
                "parameters": "${config.mapping}",
            },
        ],
    }

    profile = tmp_path / "profiles/rpi5.yaml"

    resolved = resolve_system_source_document(
        raw,
        source=system_path,
        config_overlays=(
            SystemConfigOverlay(
                config={
                    "mapping": {
                        "voxel_size_m": 0.1,
                    },
                },
                source=profile,
            ),
        ),
    )

    assert resolved.document["applications"][0][
        "parameters"
    ] == {
        "voxel_size_m": 0.1,
        "point_stride": 4,
    }

    assert resolved.config_sources == (
        defaults.resolve(),
    )

    assert resolved.config_overlay_sources == (
        profile.resolve(),
    )

    assert resolved.config_provenance[
        "mapping.voxel_size_m"
    ] == profile.resolve()

    assert resolved.config_provenance[
        "mapping.point_stride"
    ] == defaults.resolve()


def test_overlay_source_is_authoring_provenance_not_system_content(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profiles/rpi5.yaml"

    raw = {
        "apiVersion": "nodrix.system/v1",
        "kind": "System",
        "name": "mapping",
        "metadata": {
            "value": "${config.robot.mode}",
        },
    }

    resolved = resolve_system_source_document(
        raw,
        source=tmp_path / "system.yaml",
        config_overlays=(
            SystemConfigOverlay(
                config={
                    "robot": {
                        "mode": "field",
                    },
                },
                source=profile,
            ),
        ),
    )

    assert resolved.document["metadata"] == {
        "value": "field",
    }

    assert "config" not in resolved.document
    assert "config_overlays" not in resolved.document
    assert str(profile) not in str(
        resolved.document
    )
