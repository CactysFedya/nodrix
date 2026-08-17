from __future__ import annotations

from pathlib import Path

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


def test_new_project_does_not_advertise_pipeline_resources(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    project = _project_document(
        tmp_path
    )

    assert "pipelines" not in project

    resources = list_project_resources(
        root=tmp_path
    )

    assert "pipeline" not in resources
    assert "system" in resources


def test_explicit_legacy_pipeline_can_still_be_registered(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    pipeline = add_project_resource(
        "pipeline",
        "legacy-dataflow",
        root=tmp_path,
        make_default=True,
    )

    project = _project_document(
        tmp_path
    )

    assert project["pipelines"] == {
        "legacy-dataflow": (
            "pipelines/"
            "legacy-dataflow.yaml"
        ),
    }

    assert (
        project["defaults"]["pipeline"]
        == "legacy-dataflow"
    )

    document = yaml.safe_load(
        pipeline.path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        document["kind"]
        == "Pipeline"
    )

    assert (
        document["apiVersion"]
        == "plyctl.dev/v2"
    )


def test_existing_pipeline_registration_remains_resolvable(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    pipeline = add_project_resource(
        "pipeline",
        "legacy-dataflow",
        root=tmp_path,
    )

    resolved = resolve_project_resource(
        "pipeline",
        "legacy-dataflow",
        root=tmp_path,
    )

    assert resolved.kind == "pipeline"
    assert resolved.name == "legacy-dataflow"
    assert resolved.path == pipeline.path


def test_default_listing_surfaces_pipeline_only_when_registered(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    before = list_project_resources(
        root=tmp_path
    )

    assert "pipeline" not in before

    add_project_resource(
        "pipeline",
        "legacy-dataflow",
        root=tmp_path,
    )

    after = list_project_resources(
        root=tmp_path
    )

    assert after["pipeline"] == {
        "legacy-dataflow": (
            "pipelines/"
            "legacy-dataflow.yaml"
        )
    }


def test_explicit_pipeline_listing_remains_supported_when_empty(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    assert list_project_resources(
        "pipeline",
        root=tmp_path,
    ) == {
        "pipeline": {},
    }
