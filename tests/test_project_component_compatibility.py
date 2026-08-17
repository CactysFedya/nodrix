from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
    list_project_resources,
    resolve_project_resource,
)


def _project_document(
    root: Path,
) -> dict:
    return yaml.safe_load(
        (root / "nodrix.yaml").read_text(
            encoding="utf-8"
        )
    )


def _register_legacy_component(
    root: Path,
) -> Path:
    target = (
        root
        / "legacy"
        / "worker.yaml"
    )
    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    target.write_text(
        "schema: nodrix.component/v1\n"
        "name: worker\n",
        encoding="utf-8",
    )

    project = _project_document(root)
    project["components"] = {
        "worker": "legacy/worker.yaml",
    }

    (root / "nodrix.yaml").write_text(
        yaml.safe_dump(
            project,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    return target.resolve()


def test_new_project_does_not_advertise_component_resources(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    project = _project_document(
        tmp_path
    )

    assert "components" not in project

    resources = list_project_resources(
        root=tmp_path
    )

    assert "component" not in resources


def test_new_component_resource_creation_is_rejected(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match=(
            "Component resources are "
            "compatibility-only"
        ),
    ):
        add_project_resource(
            "component",
            "worker",
            root=tmp_path,
        )

    assert not (
        tmp_path
        / "components"
        / "worker.yaml"
    ).exists()

    assert "components" not in (
        _project_document(
            tmp_path
        )
    )


def test_explicit_legacy_component_registration_remains_resolvable(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    target = (
        _register_legacy_component(
            tmp_path
        )
    )

    listed = list_project_resources(
        "component",
        root=tmp_path,
    )

    assert listed == {
        "component": {
            "worker": "legacy/worker.yaml",
        }
    }

    resolved = resolve_project_resource(
        "component",
        "worker",
        root=tmp_path,
    )

    assert resolved.kind == "component"
    assert resolved.name == "worker"
    assert resolved.path == target


def test_default_listing_preserves_existing_legacy_components(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    _register_legacy_component(
        tmp_path
    )

    resources = list_project_resources(
        root=tmp_path
    )

    assert resources["component"] == {
        "worker": "legacy/worker.yaml",
    }
