from __future__ import annotations

from pathlib import Path

from nodrix.native_runtime import NativeToolchain
from nodrix.storage_layout import StorageLayout
from nodrix.workflow_execution import (
    _cache_state_path,
)


def test_engineering_roots_preserve_existing_layout(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        layout.benchmarks_root
        == tmp_path / ".nodrix" / "benchmarks"
    )

    assert (
        layout.optimization_root
        == tmp_path / ".nodrix" / "optimization"
    )

    assert (
        layout.generated_root
        == tmp_path / ".nodrix" / "generated"
    )

    assert (
        layout.operations_root
        == tmp_path / ".nodrix" / "operations"
    )


def test_cache_roots_are_managed_state(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        layout.cache_root
        == tmp_path / ".nodrix" / "cache"
    )

    assert (
        layout.workflow_cache_root
        == (
            tmp_path
            / ".nodrix"
            / "cache"
            / "workflows"
        )
    )


def test_native_build_preserves_compatibility_path(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        layout.native_build_root
        == tmp_path / ".nodrix" / "native-build"
    )


def test_system_generated_preserves_compatibility_path(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        layout.system_generated_root
        == (
            tmp_path
            / ".nodrix"
            / "system-generated"
        )
    )


def test_native_toolchain_uses_storage_layout(
    tmp_path: Path,
) -> None:
    toolchain = NativeToolchain(
        tmp_path
    )

    assert (
        toolchain.build_dir
        == StorageLayout(
            tmp_path
        ).native_build_root
    )


def test_workflow_cache_uses_storage_layout(
    tmp_path: Path,
) -> None:
    expected = (
        StorageLayout(
            tmp_path
        ).workflow_cache_root
        / "mapping"
        / "build.json"
    )

    assert (
        _cache_state_path(
            tmp_path,
            "mapping",
            "build",
        )
        == expected
    )


def test_layout_resolution_does_not_create_engineering_storage(
    tmp_path: Path,
) -> None:
    project = (
        tmp_path
        / "project"
    )

    layout = StorageLayout(
        project
    )

    _ = (
        layout.cache_root,
        layout.workflow_cache_root,
        layout.native_build_root,
        layout.system_generated_root,
        layout.benchmarks_root,
        layout.optimization_root,
        layout.operations_root,
    )

    assert not project.exists()
