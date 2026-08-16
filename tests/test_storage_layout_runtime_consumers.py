from __future__ import annotations

from pathlib import Path

import yaml

from nodrix.storage_layout import StorageLayout
from nodrix.workspace import (
    resolve_project_root,
    set_active_context,
    supervisor_state,
)


def _workspace(
    root: Path,
) -> None:
    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    document = {
        "contexts": {
            "local": {},
        },
        "defaults": {
            "context": "local",
        },
    }

    (
        root
        / "nodrix.yaml"
    ).write_text(
        yaml.safe_dump(
            document,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_workspace_context_uses_storage_layout(
    tmp_path: Path,
) -> None:
    _workspace(
        tmp_path
    )

    target = set_active_context(
        tmp_path,
        "local",
    )

    layout = StorageLayout(
        tmp_path
    )

    assert (
        target
        == layout.context_file
    )

    assert (
        layout.context_file.read_text(
            encoding="utf-8",
        )
        == "local\n"
    )


def test_supervisor_state_uses_storage_layout(
    tmp_path: Path,
) -> None:
    assert (
        supervisor_state(
            tmp_path
        )
        == StorageLayout(
            tmp_path
        ).supervisor_file
    )


def test_existing_run_storage_identifies_project_root(
    tmp_path: Path,
) -> None:
    project = (
        tmp_path
        / "project"
    )

    layout = StorageLayout(
        project
    )

    layout.runs_root.mkdir(
        parents=True,
    )

    assert (
        resolve_project_root(
            project
        )
        == project.resolve()
    )
