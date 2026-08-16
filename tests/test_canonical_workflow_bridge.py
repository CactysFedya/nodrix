from __future__ import annotations

from dataclasses import replace

import pytest

from nodrix.model import (
    BUILD,
    WORKFLOW,
    EntityRef,
    Operation,
    RevisionRef,
)
from nodrix.workflow_canonical import (
    workflow_plan_digest,
    workflow_plan_record,
)
from nodrix.workflow_planning import (
    WorkflowPlanResult,
    WorkflowStepPlan,
)


def _subject() -> tuple[EntityRef, RevisionRef]:
    entity = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )
    revision = RevisionRef.from_sha256(
        entity,
        "a" * 64,
    )
    return entity, revision


def _plan(
    *,
    root: str = "/workspace/project",
    workflow_path: str = "/workspace/project/workflows/build.yaml",
    command: str = "cmake --build build",
    state_path: str = "/workspace/project/.nodrix/cache/build.json",
) -> WorkflowPlanResult:
    return WorkflowPlanResult(
        name="build",
        root=root,
        workflow_path=workflow_path,
        environment="robot",
        generated=False,
        steps=(
            WorkflowStepPlan(
                index=1,
                step_id="compile",
                status="planned",
                recipe="cmake",
                depends_on=(),
                cache="miss",
                reasons=("cache fingerprint changed",),
                command=command,
                cwd=".",
                cache_inputs=("src",),
                cache_outputs=("build",),
                cache_environment=("CC",),
                fingerprint="b" * 64,
                state_path=state_path,
            ),
        ),
    )


def test_workflow_plan_record_wraps_existing_domain_plan() -> None:
    entity, revision = _subject()
    operation = Operation(
        kind=BUILD,
        subject=entity,
        subject_revision=revision,
    )
    plan = _plan()

    record = workflow_plan_record(
        plan,
        operation=operation,
        subject_revision=revision,
    )

    assert record.kind == WORKFLOW
    assert record.operation is operation
    assert record.subject_revision == revision
    assert record.payload is plan
    assert record.plan_id.startswith(
        "plan-"
    )
    assert len(record.plan_id) == (
        len("plan-") + 64
    )
    assert record.metadata["workflow"] == "build"
    assert record.metadata["plan_sha256"] == workflow_plan_digest(plan)


def test_workflow_plan_digest_ignores_storage_locations() -> None:
    first = _plan()

    second = replace(
        first,
        root="/different/location",
        workflow_path="/different/location/build.yaml",
        steps=(
            replace(
                first.steps[0],
                state_path="/different/cache/location.json",
            ),
        ),
    )

    assert workflow_plan_digest(first) == workflow_plan_digest(second)


def test_workflow_plan_digest_changes_with_execution_semantics() -> None:
    first = _plan()
    second = _plan(command="ninja -C build")

    assert workflow_plan_digest(first) != workflow_plan_digest(second)


def test_workflow_plan_record_requires_matching_subject_revision() -> None:
    entity, revision = _subject()
    operation = Operation(
        kind=BUILD,
        subject=entity,
    )

    other = EntityRef(
        kind="system",
        namespace="project",
        name="other",
    )
    other_revision = RevisionRef.from_sha256(
        other,
        "c" * 64,
    )

    with pytest.raises(
        ValueError,
        match="subject_revision must reference the operation subject",
    ):
        workflow_plan_record(
            _plan(),
            operation=operation,
            subject_revision=other_revision,
        )


def test_workflow_plan_digest_rejects_wrong_type() -> None:
    with pytest.raises(
        TypeError,
        match="plan must be a WorkflowPlanResult",
    ):
        workflow_plan_digest(object())  # type: ignore[arg-type]


def test_workflow_plan_record_preserves_extra_metadata() -> None:
    entity, revision = _subject()
    operation = Operation(
        kind=BUILD,
        subject=entity,
    )

    record = workflow_plan_record(
        _plan(),
        operation=operation,
        subject_revision=revision,
        metadata={"source": "project-build"},
    )

    assert record.metadata["source"] == "project-build"


def test_workflow_plan_record_identity_includes_operation() -> None:
    entity, revision = _subject()
    plan = _plan()

    build = workflow_plan_record(
        plan,
        operation=Operation(
            kind="build",
            subject=entity,
            subject_revision=revision,
            parameters={
                "mode": "normal",
            },
        ),
        subject_revision=revision,
    )

    deploy = workflow_plan_record(
        plan,
        operation=Operation(
            kind="robot.deploy",
            subject=entity,
            subject_revision=revision,
            parameters={
                "mode": "normal",
            },
        ),
        subject_revision=revision,
    )

    assert (
        workflow_plan_digest(
            build.payload
        )
        == workflow_plan_digest(
            deploy.payload
        )
    )

    assert (
        build.plan_id
        != deploy.plan_id
    )
