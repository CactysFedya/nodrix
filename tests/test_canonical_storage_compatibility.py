from __future__ import annotations

from pathlib import Path

from nodrix.project_templates import (
    SKELETON_FILES,
)
from nodrix.storage_layout import StorageLayout


def test_new_project_skeleton_uses_canonical_materialized_roots() -> None:
    assert (
        "datasets/.gitkeep"
        in SKELETON_FILES
    )

    assert (
        "artifacts/.gitkeep"
        in SKELETON_FILES
    )

    assert (
        "outputs/.gitkeep"
        not in SKELETON_FILES
    )


def test_new_project_gitignore_protects_materialized_data() -> None:
    gitignore = SKELETON_FILES[
        ".gitignore"
    ]

    assert "/datasets/*" in gitignore
    assert "!/datasets/.gitkeep" in gitignore

    assert "/artifacts/*" in gitignore
    assert "!/artifacts/.gitkeep" in gitignore


def test_new_project_keeps_legacy_outputs_ignored_without_scaffolding_it() -> None:
    gitignore = SKELETON_FILES[
        ".gitignore"
    ]

    assert "/outputs/" in gitignore
    assert "outputs/.gitkeep" not in gitignore


def test_storage_layout_keeps_legacy_outputs_addressable(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        layout.legacy_outputs_root
        == tmp_path / "outputs"
    )

    assert (
        layout.legacy_outputs_root
        not in {
            layout.datasets_root,
            layout.artifacts_root,
        }
    )


def test_storage_layout_keeps_global_and_project_concepts_separate(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        layout.managed_root
        == tmp_path / ".nodrix"
    )

    assert (
        layout.datasets_root.parent
        == layout.project_root
    )

    assert (
        layout.artifacts_root.parent
        == layout.project_root
    )


def test_storage_layout_does_not_create_legacy_or_canonical_roots(
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
        layout.datasets_root,
        layout.artifacts_root,
        layout.legacy_outputs_root,
        layout.managed_root,
    )

    assert not project.exists()
