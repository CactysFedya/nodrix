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


def test_workflow_sdk_has_full_yaml_field_parity() -> None:
    source = """
schema: nodrix.workflow/v1
name: build
environment:
  GLOBAL_FLAG: enabled
steps:
  - id: configure
    run: cmake -S . -B build
  - id: compile
    run: cmake --build build
    depends_on:
      - configure
    recipe: cmake.build
    cwd: work
    environment:
      CC: clang
      CXX: clang++
    when:
      environment: GLOBAL_FLAG
    timeout_seconds: 300.0
    continue_on_error: true
    cache:
      inputs:
        - source.txt
      outputs:
        - out.txt
      environment:
        - CC
        - CXX
"""

    expected = yaml.safe_load(
        source
    )

    workflow = Workflow(
        "build",
        environment={
            "GLOBAL_FLAG": "enabled",
        },
    )

    configure = workflow.run(
        "configure",
        "cmake -S . -B build",
    )

    workflow.run(
        "compile",
        "cmake --build build",
        after=configure,
        recipe="cmake.build",
        cwd="work",
        environment={
            "CC": "clang",
            "CXX": "clang++",
        },
        when={
            "environment": (
                "GLOBAL_FLAG"
            ),
        },
        timeout_seconds=300,
        continue_on_error=True,
        cache={
            "inputs": [
                "source.txt",
            ],
            "outputs": [
                "out.txt",
            ],
            "environment": [
                "CC",
                "CXX",
            ],
        },
    )

    assert (
        workflow.to_dict()
        == expected
    )


def test_workflow_sdk_full_definition_uses_existing_planner(
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

    (tmp_path / "work").mkdir()

    (tmp_path / "source.txt").write_text(
        "source\n",
        encoding="utf-8",
    )

    workflow = Workflow(
        "build",
        environment={
            "GLOBAL_FLAG": "enabled",
        },
    )

    step = workflow.run(
        "compile",
        "echo compile",
        recipe="cmake.build",
        cwd="work",
        environment={
            "CC": "clang",
        },
        when={
            "environment": (
                "GLOBAL_FLAG"
            ),
        },
        timeout_seconds=120,
        continue_on_error=True,
        cache={
            "inputs": [
                "source.txt",
            ],
            "outputs": [
                "out.txt",
            ],
            "environment": [
                "CC",
            ],
        },
    )

    assert (
        step.recipe
        == "cmake.build"
    )

    resource.path.write_text(
        yaml.safe_dump(
            workflow.to_dict(),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = plan_workflow(
        "build",
        root=tmp_path,
    )

    assert len(plan.steps) == 1

    planned = plan.steps[0]

    assert (
        planned.step_id
        == "compile"
    )

    assert (
        planned.command
        == "echo compile"
    )

    assert (
        planned.recipe
        == "cmake.build"
    )

    assert (
        planned.cwd
        == "work"
    )

    assert (
        planned.environment_overrides
        == (
            ("CC", "clang"),
        )
    )

    assert (
        planned.when_json
        == '{"environment":"GLOBAL_FLAG"}'
    )

    assert (
        planned.timeout_seconds
        == 120.0
    )

    assert (
        planned.continue_on_error
        is True
    )

    assert (
        planned.cache_enabled
        is True
    )

    assert (
        planned.cache_inputs
        == ("source.txt",)
    )

    assert (
        planned.cache_outputs
        == ("out.txt",)
    )

    assert (
        planned.cache_environment
        == ("CC",)
    )

    resolved_environment = dict(
        plan.execution_environment
    )

    assert (
        resolved_environment[
            "GLOBAL_FLAG"
        ]
        == "enabled"
    )


def test_workflow_sdk_preserves_explicit_boolean_definition_values() -> None:
    workflow = Workflow(
        "conditional"
    )

    step = workflow.run(
        "disabled",
        "echo disabled",
        when=False,
        cache=False,
    )

    assert step.to_dict() == {
        "id": "disabled",
        "run": "echo disabled",
        "when": False,
        "cache": False,
    }


def test_workflow_sdk_operation_binding_has_yaml_parity() -> None:
    source = """
schema: nodrix.workflow/v1
name: flash
implements: robot.flash
steps:
  - id: write
    run: tool flash firmware.bin
"""

    expected = yaml.safe_load(
        source
    )

    workflow = Workflow(
        "flash",
        implements="robot.flash",
    )

    workflow.run(
        "write",
        "tool flash firmware.bin",
    )

    assert workflow.to_dict() == expected


def test_workflow_operation_binding_reaches_plan_and_digest(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    resource = add_project_resource(
        "workflow",
        "flash",
        root=tmp_path,
    )

    workflow = Workflow(
        "flash",
        implements="robot.flash",
    )

    workflow.run(
        "write",
        "echo flash",
    )

    resource.path.write_text(
        yaml.safe_dump(
            workflow.to_dict(),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    first = plan_workflow(
        "flash",
        root=tmp_path,
    )

    assert first.implements == "robot.flash"

    from nodrix.workflow_canonical import (
        workflow_plan_digest,
    )

    first_digest = workflow_plan_digest(
        first
    )

    replacement = Workflow(
        "flash",
        implements="robot.deploy",
    )

    replacement.run(
        "write",
        "echo flash",
    )

    resource.path.write_text(
        yaml.safe_dump(
            replacement.to_dict(),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    second = plan_workflow(
        "flash",
        root=tmp_path,
    )

    assert second.implements == "robot.deploy"

    second_digest = workflow_plan_digest(
        second
    )

    assert first_digest != second_digest

    assert [
        item.command
        for item in first.steps
    ] == [
        item.command
        for item in second.steps
    ]
