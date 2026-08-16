from __future__ import annotations

import pytest

from nodrix.model import (
    DefinitionRecord as ModelDefinitionRecord,
)
from nodrix.model import (
    EntityRef as ModelEntityRef,
)
from nodrix.model import (
    RevisionRef as ModelRevisionRef,
)
from nodrix.sdk import (
    DefinitionRecord,
    EntityRef,
    RevisionRef,
    Workflow,
)
from nodrix.workflow_definition import (
    workflow_definition_record,
)


def _project(
    name: str = "demo",
) -> EntityRef:
    return EntityRef(
        kind="project",
        namespace="workspace",
        name=name,
    )


def _workflow() -> Workflow:
    workflow = Workflow(
        "build",
        implements="build",
    )

    workflow.run(
        "compile",
        "cmake --build build",
    )

    return workflow


def test_sdk_reexports_canonical_identity_types() -> None:
    assert EntityRef is ModelEntityRef

    assert (
        RevisionRef
        is ModelRevisionRef
    )

    assert (
        DefinitionRecord
        is ModelDefinitionRecord
    )


def test_sdk_can_author_custom_canonical_entity_reference() -> None:
    entity = EntityRef(
        kind="robot.firmware",
        namespace="acme/rover-01",
        name="navigation",
    )

    assert (
        entity.canonical
        == (
            "nodrix://robot.firmware/"
            "acme/rover-01/navigation"
        )
    )


def test_workflow_definition_record_matches_canonical_bridge() -> None:
    workflow = _workflow()
    project = _project()

    sdk_record = (
        workflow.definition_record(
            project=project,
        )
    )

    canonical_record = (
        workflow_definition_record(
            workflow.to_dict(),
            project=project,
        )
    )

    assert (
        sdk_record.entity
        == canonical_record.entity
    )

    assert (
        sdk_record.revision
        == canonical_record.revision
    )

    assert (
        sdk_record.schema
        == canonical_record.schema
    )

    assert (
        sdk_record.definition
        == canonical_record.definition
    )


def test_workflow_definition_metadata_does_not_change_revision() -> None:
    workflow = _workflow()
    project = _project()

    first = (
        workflow.definition_record(
            project=project,
            metadata={
                "source": "python-sdk",
            },
        )
    )

    second = (
        workflow.definition_record(
            project=project,
            metadata={
                "source": "generated",
            },
        )
    )

    assert (
        first.revision
        == second.revision
    )


def test_workflow_definition_record_requires_project_entity() -> None:
    workflow = _workflow()

    invalid = EntityRef(
        kind="component",
        namespace="acme",
        name="robot",
    )

    with pytest.raises(
        ValueError,
        match="kind 'project'",
    ):
        workflow.definition_record(
            project=invalid,
        )


def test_workflow_definition_record_does_not_guess_project() -> None:
    workflow = _workflow()

    with pytest.raises(
        TypeError,
    ):
        workflow.definition_record()  # type: ignore[call-arg]
