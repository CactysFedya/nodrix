from __future__ import annotations

from pathlib import Path

import pytest

from nodrix.system.definition import system_definition_digest
from nodrix.system.io import (
    load_system,
    loads_system,
    system_to_canonical,
)
from nodrix.system.model import SystemModel
from nodrix.system.source import (
    SystemSourceError,
    resolve_system_source_document,
)


def test_canonical_system_source_passes_through_unchanged() -> None:
    raw = {
        "apiVersion": "nodrix.system/v1",
        "kind": "System",
        "name": "robot",
        "targets": [],
    }

    resolved = resolve_system_source_document(raw)

    assert resolved.document == raw
    assert resolved.document is not raw
    assert resolved.source is None
    assert resolved.sources == ()


def test_file_source_records_authoring_source_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "robot.yaml"

    resolved = resolve_system_source_document(
        {
            "apiVersion": "nodrix.system/v1",
            "kind": "System",
            "name": "robot",
        },
        source=path,
    )

    assert resolved.source == path.resolve()
    assert resolved.sources == (path.resolve(),)


def test_authoring_fields_are_not_canonical_system_fields() -> None:
    assert "imports" not in SystemModel.model_fields
    assert "config" not in SystemModel.model_fields

    with pytest.raises(
        SystemSourceError,
        match="reserved but not enabled",
    ):
        resolve_system_source_document({
            "apiVersion": "nodrix.system/v1",
            "kind": "System",
            "name": "robot",
            "imports": ["modules/sensing.yaml"],
            "config": ["config/defaults.yaml"],
        })


def test_source_boundary_preserves_system_revision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "robot.yaml"

    path.write_text(
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n",
        encoding="utf-8",
    )

    from_file = load_system(path)

    from_text = loads_system(
        path.read_text(encoding="utf-8")
    )

    assert system_to_canonical(from_file) == (
        system_to_canonical(from_text)
    )

    assert system_definition_digest(from_file) == (
        system_definition_digest(from_text)
    )
