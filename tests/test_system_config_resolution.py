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


def test_empty_config_resolution() -> None:
    resolved = resolve_system_config(None)

    assert resolved.config == {}
    assert resolved.sources == ()


def test_single_config_document_is_plain_mapping(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path / "config/defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.1\n"
        "  point_stride: 1\n",
    )

    resolved = resolve_system_config(
        "config/defaults.yaml",
        base_dir=tmp_path,
    )

    assert resolved.config == {
        "mapping": {
            "voxel_size_m": 0.1,
            "point_stride": 1,
        }
    }

    assert resolved.sources == (
        path.resolve(),
    )


def test_config_documents_merge_in_declared_order(
    tmp_path: Path,
) -> None:
    defaults = _write(
        tmp_path / "config/defaults.yaml",
        "mapping:\n"
        "  voxel_size_m: 0.1\n"
        "  point_stride: 1\n"
        "  max_voxels: 5000000\n"
        "lidar:\n"
        "  frame: livox_frame\n"
        "devices:\n"
        "  - default\n",
    )

    rpi5 = _write(
        tmp_path / "config/rpi5.yaml",
        "mapping:\n"
        "  point_stride: 2\n"
        "lidar:\n"
        "  rate_hz: 10\n"
        "devices:\n"
        "  - rpi5\n",
    )

    resolved = resolve_system_config(
        [
            "config/defaults.yaml",
            "config/rpi5.yaml",
        ],
        base_dir=tmp_path,
    )

    assert resolved.config == {
        "mapping": {
            "voxel_size_m": 0.1,
            "point_stride": 2,
            "max_voxels": 5000000,
        },
        "lidar": {
            "frame": "livox_frame",
            "rate_hz": 10,
        },
        "devices": [
            "rpi5",
        ],
    }

    assert resolved.sources == (
        defaults.resolve(),
        rpi5.resolve(),
    )


def test_config_requires_mapping_document(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "bad.yaml",
        "- one\n"
        "- two\n",
    )

    with pytest.raises(
        SystemSourceError,
        match="must contain a YAML mapping",
    ):
        resolve_system_config(
            "bad.yaml",
            base_dir=tmp_path,
        )


def test_missing_config_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        SystemSourceError,
        match="does not exist",
    ):
        resolve_system_config(
            "config/missing.yaml",
            base_dir=tmp_path,
        )
