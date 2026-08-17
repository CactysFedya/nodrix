from __future__ import annotations

from pathlib import Path

import pytest

from nodrix.system.source import (
    SystemSourceError,
    resolve_system_config,
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


def test_config_provenance_tracks_winning_source(
    tmp_path: Path,
) -> None:
    defaults = _write(
        tmp_path / "config/defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.1\n"
        "  point_stride: 1\n",
    )

    rpi5 = _write(
        tmp_path / "config/rpi5.yaml",
        "mapping:\n"
        "  point_stride: 2\n",
    )

    resolved = resolve_system_config(
        [
            "config/defaults.yaml",
            "config/rpi5.yaml",
        ],
        base_dir=tmp_path,
    )

    assert resolved.source_for(
        "mapping.voxel_size_m"
    ) == defaults.resolve()

    assert resolved.source_for(
        "mapping.point_stride"
    ) == rpi5.resolve()


def test_unmodified_sibling_keeps_original_provenance(
    tmp_path: Path,
) -> None:
    defaults = _write(
        tmp_path / "defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.1\n"
        "  max_voxels: 5000000\n",
    )

    override = _write(
        tmp_path / "override.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.2\n",
    )

    resolved = resolve_system_config(
        [
            defaults,
            override,
        ],
        base_dir=tmp_path,
    )

    assert resolved.source_for(
        "mapping.voxel_size_m"
    ) == override.resolve()

    assert resolved.source_for(
        "mapping.max_voxels"
    ) == defaults.resolve()


def test_scalar_replacing_mapping_replaces_child_provenance(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.1\n"
        "  point_stride: 1\n",
    )

    override = _write(
        tmp_path / "override.yaml",
        "mapping: disabled\n",
    )

    resolved = resolve_system_config(
        [
            "defaults.yaml",
            "override.yaml",
        ],
        base_dir=tmp_path,
    )

    assert resolved.config["mapping"] == "disabled"

    assert resolved.provenance == {
        "mapping": override.resolve(),
    }


def test_mapping_replacing_scalar_replaces_parent_provenance(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "defaults.yaml",
        "mapping: disabled\n",
    )

    override = _write(
        tmp_path / "override.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.1\n",
    )

    resolved = resolve_system_config(
        [
            "defaults.yaml",
            "override.yaml",
        ],
        base_dir=tmp_path,
    )

    assert "mapping" not in (
        resolved.provenance
    )

    assert resolved.source_for(
        "mapping.voxel_size_m"
    ) == override.resolve()


def test_list_is_one_replaceable_config_value(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "defaults.yaml",
        "underlays:\n"
        "  - /opt/ros/jazzy\n",
    )

    override = _write(
        tmp_path / "override.yaml",
        "underlays:\n"
        "  - custom/install\n",
    )

    resolved = resolve_system_config(
        [
            "defaults.yaml",
            "override.yaml",
        ],
        base_dir=tmp_path,
    )

    assert resolved.config["underlays"] == [
        "custom/install",
    ]

    assert resolved.source_for(
        "underlays"
    ) == override.resolve()


def test_dotted_config_key_is_rejected(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "bad.yaml",
        "'mapping.voxel_size_m': 0.1\n",
    )

    with pytest.raises(
        SystemSourceError,
        match=r"must not contain '\.'",
    ):
        resolve_system_config(
            "bad.yaml",
            base_dir=tmp_path,
        )


def test_empty_config_key_is_rejected(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "bad.yaml",
        "'': 1\n",
    )

    with pytest.raises(
        SystemSourceError,
        match="must not be empty",
    ):
        resolve_system_config(
            "bad.yaml",
            base_dir=tmp_path,
        )


def test_empty_mapping_overlay_does_not_steal_existing_provenance(
    tmp_path: Path,
) -> None:
    defaults = _write(
        tmp_path / "defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.1\n"
        "  point_stride: 1\n",
    )

    _write(
        tmp_path / "override.yaml",
        "mapping: {}\n",
    )

    resolved = resolve_system_config(
        [
            "defaults.yaml",
            "override.yaml",
        ],
        base_dir=tmp_path,
    )

    assert resolved.config == {
        "mapping": {
            "voxel_size_m": 0.1,
            "point_stride": 1,
        }
    }

    assert resolved.source_for(
        "mapping.voxel_size_m"
    ) == defaults.resolve()

    assert resolved.source_for(
        "mapping.point_stride"
    ) == defaults.resolve()
