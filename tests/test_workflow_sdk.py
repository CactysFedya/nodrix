from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
)
from nodrix.sdk import (
    WORKFLOW_SCHEMA,
    Workflow,
    WorkflowStep,
)
from nodrix.workflow_planning import (
    plan_workflow,
)


def test_workflow_sdk_builds_canonical_definition() -> None:
    build = Workflow(
        "build"
    )

    clone = build.run(
        "clone",
        "git clone https://example.test/lib.git sources/lib",
    )

    configure = build.run(
        "configure",
        "cmake -S sources/lib -B build/lib",
        after=clone,
    )

    build.run(
        "compile",
        "cmake --build build/lib",
        after=configure,
    )

    assert isinstance(
        clone,
        WorkflowStep,
    )

    assert build.to_dict() == {
        "schema": WORKFLOW_SCHEMA,
        "name": "build",
        "steps": [
            {
                "id": "clone",
                "run": (
                    "git clone "
                    "https://example.test/lib.git "
                    "sources/lib"
                ),
            },
            {
                "id": "configure",
                "run": (
                    "cmake -S sources/lib "
                    "-B build/lib"
                ),
                "depends_on": [
                    "clone"
                ],
            },
            {
                "id": "compile",
                "run": (
                    "cmake --build build/lib"
                ),
                "depends_on": [
                    "configure"
                ],
            },
        ],
    }


def test_workflow_sdk_combines_named_and_object_dependencies() -> None:
    workflow = Workflow(
        "package"
    )

    prepare = workflow.run(
        "prepare",
        "echo prepare",
    )

    compile_step = workflow.run(
        "compile",
        "echo compile",
    )

    package = workflow.run(
        "package",
        "echo package",
        depends_on="prepare",
        after=[
            prepare,
            compile_step,
        ],
    )

    assert package.depends_on == (
        "prepare",
        "compile",
    )


def test_workflow_sdk_rejects_invalid_dependencies() -> None:
    first = Workflow(
        "first"
    )

    second = Workflow(
        "second"
    )

    foreign = first.run(
        "foreign",
        "echo foreign",
    )

    with pytest.raises(
        ValueError,
        match="another workflow",
    ):
        second.run(
            "use-foreign",
            "echo invalid",
            after=foreign,
        )

    with pytest.raises(
        ValueError,
        match="unknown or later",
    ):
        second.run(
            "later",
            "echo invalid",
            depends_on="missing",
        )


def test_workflow_sdk_document_uses_existing_planner(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    resource = add_project_resource(
        "workflow",
        "build",
        root=tmp_path,
    )

    build = Workflow(
        "build"
    )

    configure = build.run(
        "configure",
        "echo configure",
    )

    build.run(
        "compile",
        "echo compile",
        after=configure,
    )

    resource.path.write_text(
        yaml.safe_dump(
            build.to_dict(),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = plan_workflow(
        "build",
        root=tmp_path,
    )

    assert [
        step.step_id
        for step
        in plan.steps
    ] == [
        "configure",
        "compile",
    ]

    assert (
        plan.steps[0].command
        == "echo configure"
    )

    assert (
        plan.steps[1].command
        == "echo compile"
    )

    assert (
        plan.steps[1].depends_on
        == ("configure",)
    )


def test_workflow_sdk_has_yaml_definition_parity() -> None:
    source = """
schema: nodrix.workflow/v1
name: build
steps:
  - id: configure
    run: cmake -S . -B build
  - id: compile
    run: cmake --build build
    depends_on:
      - configure
"""

    expected = yaml.safe_load(
        source
    )

    workflow = Workflow(
        "build"
    )

    configure = workflow.run(
        "configure",
        "cmake -S . -B build",
    )

    workflow.run(
        "compile",
        "cmake --build build",
        after=configure,
    )

    assert (
        workflow.to_dict()
        == expected
    )
