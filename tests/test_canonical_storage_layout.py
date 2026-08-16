from __future__ import annotations

from pathlib import Path

from nodrix.run_document import (
    canonical_run_root,
)
from nodrix.runs import run_root
from nodrix.storage_layout import StorageLayout


def test_storage_layout_normalizes_project_root(
    tmp_path: Path,
) -> None:
    project = (
        tmp_path
        / "nested"
        / ".."
        / "project"
    )

    layout = StorageLayout(
        project
    )

    assert (
        layout.project_root
        == project.resolve()
    )


def test_managed_state_is_under_dot_nodrix(
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
        layout.runs_root
        == tmp_path / ".nodrix" / "runs"
    )

    assert (
        layout.logs_root
        == tmp_path / ".nodrix" / "logs"
    )

    assert (
        layout.operations_root
        == tmp_path / ".nodrix" / "operations"
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
        layout.build_root
        == tmp_path / ".nodrix" / "build"
    )

    assert (
        layout.prefix_root
        == tmp_path / ".nodrix" / "prefix"
    )

    assert (
        layout.generated_root
        == tmp_path / ".nodrix" / "generated"
    )


def test_managed_state_files_use_canonical_root(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        layout.context_file
        == tmp_path / ".nodrix" / "context"
    )

    assert (
        layout.shell_rc_file
        == tmp_path / ".nodrix" / "shell.rc"
    )

    assert (
        layout.supervisor_file
        == tmp_path / ".nodrix" / "supervisor.json"
    )


def test_materialized_data_is_outside_managed_state(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        layout.datasets_root
        == tmp_path / "datasets"
    )

    assert (
        layout.artifacts_root
        == tmp_path / "artifacts"
    )

    assert (
        layout.managed_root
        not in layout.datasets_root.parents
    )

    assert (
        layout.managed_root
        not in layout.artifacts_root.parents
    )


def test_outputs_root_is_explicitly_legacy(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        layout.legacy_outputs_root
        == tmp_path / "outputs"
    )


def test_layout_resolution_does_not_create_storage(
    tmp_path: Path,
) -> None:
    project = (
        tmp_path
        / "not-created"
    )

    layout = StorageLayout(
        project
    )

    assert (
        layout.project_root
        == project.resolve()
    )

    assert not project.exists()
    assert not layout.managed_root.exists()
    assert not layout.datasets_root.exists()
    assert not layout.artifacts_root.exists()


def test_canonical_run_writer_uses_storage_layout(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        canonical_run_root(
            tmp_path
        )
        == layout.runs_root
    )


def test_run_index_uses_storage_layout(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(
        tmp_path
    )

    assert (
        run_root(
            tmp_path
        )
        == layout.runs_root
    )
