from pathlib import Path

import yaml

from nodrix.model import (
    EntityRef,
)
from nodrix.sdk import Workflow
from nodrix.workflow_definition import (
    load_canonical_workflow_definition,
    workflow_definition_digest,
    workflow_definition_record,
    workflow_entity_ref,
)


def _project(
    name: str = "demo",
) -> EntityRef:
    return EntityRef(
        kind="project",
        namespace="workspace",
        name=name,
    )


def _document() -> dict[str, object]:
    return {
        "schema": "nodrix.workflow/v1",
        "name": "build",
        "steps": [
            {
                "id": "compile",
                "run": "cmake --build build",
            },
        ],
    }


def test_workflow_entity_is_scoped_by_project_identity() -> None:
    ref = workflow_entity_ref(
        "build",
        project=_project(),
    )

    assert (
        ref.canonical
        == (
            "nodrix://workflow/"
            "workspace/demo/build"
        )
    )


def test_same_workflow_name_in_different_projects_has_different_identity() -> None:
    first = workflow_entity_ref(
        "build",
        project=_project("robot-a"),
    )

    second = workflow_entity_ref(
        "build",
        project=_project("robot-b"),
    )

    assert first != second


def test_workflow_definition_digest_is_mapping_order_independent() -> None:
    first = _document()

    second = {
        "steps": first["steps"],
        "name": "build",
        "schema": "nodrix.workflow/v1",
    }

    assert (
        workflow_definition_digest(first)
        == workflow_definition_digest(second)
    )


def test_workflow_definition_digest_is_content_sensitive() -> None:
    first = _document()

    second = _document()

    second["steps"] = [
        {
            "id": "compile",
            "run": "ninja -C build",
        },
    ]

    assert (
        workflow_definition_digest(first)
        != workflow_definition_digest(second)
    )


def test_workflow_definition_record_uses_workflow_revision() -> None:
    document = _document()

    record = workflow_definition_record(
        document,
        project=_project(),
    )

    assert (
        record.entity.kind
        == "workflow"
    )

    assert (
        record.revision.entity
        == record.entity
    )

    assert (
        record.revision.digest
        == workflow_definition_digest(
            document
        )
    )

    assert (
        record.schema
        == "nodrix.workflow/v1"
    )


def test_definition_metadata_does_not_change_workflow_revision() -> None:
    document = _document()
    project = _project()

    first = workflow_definition_record(
        document,
        project=project,
        metadata={
            "source_path": "/first/build.yaml",
        },
    )

    second = workflow_definition_record(
        document,
        project=project,
        metadata={
            "source_path": "/second/build.yaml",
        },
    )

    assert (
        first.revision
        == second.revision
    )


def test_python_sdk_and_yaml_have_same_definition_digest() -> None:
    workflow = Workflow(
        "build"
    )

    workflow.run(
        "compile",
        "cmake --build build",
    )

    sdk_document = (
        workflow.to_dict()
    )

    yaml_document = yaml.safe_load(
        yaml.safe_dump(
            sdk_document,
            sort_keys=False,
        )
    )

    assert (
        workflow_definition_digest(
            sdk_document
        )
        == workflow_definition_digest(
            yaml_document
        )
    )


def test_project_workflow_loader_returns_canonical_definition(
    tmp_path: Path,
) -> None:
    workflows = (
        tmp_path / "workflows"
    )

    workflows.mkdir()

    (
        tmp_path / "nodrix.yaml"
    ).write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.project/v1",
                "name": "robot",
                "workflows": {
                    "build": (
                        "workflows/build.yaml"
                    ),
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    (
        workflows / "build.yaml"
    ).write_text(
        yaml.safe_dump(
            _document(),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    record = (
        load_canonical_workflow_definition(
            "build",
            root=tmp_path,
        )
    )

    assert (
        record.entity.canonical
        == (
            "nodrix://workflow/"
            "workspace/robot/build"
        )
    )

    assert (
        record.metadata[
            "source_path"
        ]
        == str(
            (
                workflows
                / "build.yaml"
            ).resolve()
        )
    )


def test_definition_record_snapshots_workflow_document() -> None:
    document = _document()

    record = workflow_definition_record(
        document,
        project=_project(),
    )

    document["name"] = "changed"

    assert (
        record.definition["name"]
        == "build"
    )
