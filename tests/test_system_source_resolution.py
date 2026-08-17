from __future__ import annotations

from pathlib import Path

import pytest

from nodrix.system.definition import system_definition_digest
from nodrix.system.io import load_system
from nodrix.system.model import SystemModel
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


def test_canonical_source_still_passes_through() -> None:
    raw = {
        "apiVersion": "nodrix.system/v1",
        "kind": "System",
        "name": "robot",
    }

    resolved = resolve_system_source_document(raw)

    assert resolved.document == raw
    assert resolved.document is not raw
    assert resolved.sources == ()


def test_imports_system_module_into_system(
    tmp_path: Path,
) -> None:
    module = _write(
        tmp_path / "modules/sensing.yaml",
        "schema: nodrix.system-module/v1\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n",
    )

    system_path = _write(
        tmp_path / "systems/robot.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "imports:\n"
        "  - ../modules/sensing.yaml\n",
    )

    system = load_system(system_path)

    assert [item.name for item in system.targets] == [
        "pi5",
    ]

    resolved = resolve_system_source_document(
        {
            "apiVersion": "nodrix.system/v1",
            "kind": "System",
            "name": "robot",
            "imports": ["../modules/sensing.yaml"],
        },
        source=system_path,
    )

    assert "imports" not in resolved.document
    assert resolved.sources == (
        system_path.resolve(),
        module.resolve(),
    )


def test_nested_module_imports_are_resolved(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "modules/base.yaml",
        "schema: nodrix.system-module/v1\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n",
    )

    _write(
        tmp_path / "modules/mapping.yaml",
        "schema: nodrix.system-module/v1\n"
        "imports:\n"
        "  - base.yaml\n"
        "targets:\n"
        "  - name: workstation\n"
        "    kind: host\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "imports:\n"
        "  - modules/mapping.yaml\n",
    )

    system = load_system(system_path)

    assert [
        item.name
        for item in system.targets
    ] == [
        "pi5",
        "workstation",
    ]


def test_module_requires_authoring_schema(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "module.yaml",
        "targets: []\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "imports: [module.yaml]\n",
    )

    with pytest.raises(
        SystemSourceError,
        match="must declare schema",
    ):
        load_system(system_path)


def test_duplicate_named_structure_is_rejected(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "module.yaml",
        "schema: nodrix.system-module/v1\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "imports: [module.yaml]\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n",
    )

    with pytest.raises(
        SystemSourceError,
        match="Duplicate targets name 'pi5'",
    ):
        load_system(system_path)


def test_recursive_module_import_is_rejected(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "a.yaml",
        "schema: nodrix.system-module/v1\n"
        "imports: [b.yaml]\n",
    )

    _write(
        tmp_path / "b.yaml",
        "schema: nodrix.system-module/v1\n"
        "imports: [a.yaml]\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "imports: [a.yaml]\n",
    )

    with pytest.raises(
        SystemSourceError,
        match="Recursive System Module import",
    ):
        load_system(system_path)


def test_same_module_cannot_be_imported_twice(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "module.yaml",
        "schema: nodrix.system-module/v1\n"
        "targets: []\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "imports:\n"
        "  - module.yaml\n"
        "  - module.yaml\n",
    )

    with pytest.raises(
        SystemSourceError,
        match="imported more than once",
    ):
        load_system(system_path)


def test_module_layout_does_not_change_semantic_revision(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "module.yaml",
        "schema: nodrix.system-module/v1\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n",
    )

    composed_path = _write(
        tmp_path / "composed.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "imports: [module.yaml]\n",
    )

    monolithic_path = _write(
        tmp_path / "monolithic.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n",
    )

    composed = load_system(
        composed_path
    )
    monolithic = load_system(
        monolithic_path
    )

    assert (
        system_definition_digest(composed)
        == system_definition_digest(monolithic)
    )


def test_config_is_authoring_only(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "config/defaults.yaml",
        "{}\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "config:\n"
        "  - config/defaults.yaml\n",
    )

    system = load_system(
        system_path
    )

    assert system.name == "robot"
    assert "config" not in SystemModel.model_fields


def test_authoring_fields_are_not_system_model_fields() -> None:
    assert "imports" not in SystemModel.model_fields
    assert "config" not in SystemModel.model_fields
