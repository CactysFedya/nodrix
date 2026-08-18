from __future__ import annotations

import pytest

from nodrix.system import (
    BackendExecutionState,
    ChildSystemExecutionStatus,
    PreparedChildSystemExecution,
    PreparedSystemExecution,
    RunningChildSystemExecution,
    SystemExecutionHandle,
    SystemExecutionStatus,
    SystemInstance,
    SystemModel,
    plan_system,
)
from nodrix.system.definition import (
    system_definition_record,
)


def _hierarchical_plan():
    child = SystemModel(
        name="livox-mid360",
    )

    revision = (
        system_definition_record(
            child
        ).revision
    )

    parent = SystemModel(
        name="robot",
        systems=(
            SystemInstance(
                name="lidar",
                uses=revision.canonical,
            ),
        ),
    )

    plan = plan_system(
        parent,
        system_resolver=(
            lambda requested: (
                child
                if requested == revision
                else None
            )
        ),
    )

    return plan


def test_prepared_execution_preserves_child_system_boundary() -> None:
    plan = _hierarchical_plan()
    instance = plan.child("lidar")

    child_execution = PreparedSystemExecution(
        plan=instance.plan,
    )

    prepared = PreparedSystemExecution(
        plan=plan,
        systems=(
            PreparedChildSystemExecution(
                instance=instance,
                execution=child_execution,
            ),
        ),
    )

    child = prepared.child(
        "lidar"
    )

    assert child.name == "lidar"
    assert child.ordinal == 0
    assert child.revision == instance.revision
    assert (
        child.execution.plan
        == instance.plan
    )


def test_composition_only_parent_requires_no_direct_scope() -> None:
    plan = _hierarchical_plan()
    instance = plan.child("lidar")

    prepared = PreparedSystemExecution(
        plan=plan,
        scopes=(),
        systems=(
            PreparedChildSystemExecution(
                instance=instance,
                execution=PreparedSystemExecution(
                    plan=instance.plan,
                ),
            ),
        ),
    )

    assert prepared.scopes == ()
    assert len(prepared.systems) == 1


def test_prepared_child_rejects_different_plan() -> None:
    plan = _hierarchical_plan()
    instance = plan.child("lidar")

    with pytest.raises(
        ValueError,
        match="different child System plan",
    ):
        PreparedChildSystemExecution(
            instance=instance,
            execution=PreparedSystemExecution(
                plan=plan,
            ),
        )


def test_running_execution_preserves_nested_execution_identity() -> None:
    plan = _hierarchical_plan()
    instance = plan.child("lidar")

    child_prepared = PreparedSystemExecution(
        plan=instance.plan,
    )

    child_handle = SystemExecutionHandle(
        execution_id="system-child-001",
        prepared=child_prepared,
    )

    parent_prepared = PreparedSystemExecution(
        plan=plan,
        systems=(
            PreparedChildSystemExecution(
                instance=instance,
                execution=child_prepared,
            ),
        ),
    )

    parent_handle = SystemExecutionHandle(
        execution_id="system-parent-001",
        prepared=parent_prepared,
        systems=(
            RunningChildSystemExecution(
                instance=instance,
                handle=child_handle,
            ),
        ),
    )

    child = parent_handle.child(
        "lidar"
    )

    assert (
        child.handle.execution_id
        == "system-child-001"
    )
    assert (
        parent_handle.execution_id
        == "system-parent-001"
    )

    assert (
        child.handle.execution_id
        != parent_handle.execution_id
    )


def test_running_child_rejects_different_plan() -> None:
    plan = _hierarchical_plan()
    instance = plan.child("lidar")

    wrong = SystemExecutionHandle(
        execution_id="wrong",
        prepared=PreparedSystemExecution(
            plan=plan,
        ),
    )

    with pytest.raises(
        ValueError,
        match="different child System plan",
    ):
        RunningChildSystemExecution(
            instance=instance,
            handle=wrong,
        )


def test_system_status_preserves_recursive_child_status() -> None:
    plan = _hierarchical_plan()
    instance = plan.child("lidar")

    child_status = SystemExecutionStatus(
        execution_id="system-child-001",
        state=BackendExecutionState.COMPLETED,
    )

    parent = SystemExecutionStatus(
        execution_id="system-parent-001",
        state=BackendExecutionState.COMPLETED,
        systems=(
            ChildSystemExecutionStatus(
                instance=instance,
                status=child_status,
            ),
        ),
    )

    child = parent.child(
        "lidar"
    )

    assert child.name == "lidar"
    assert (
        child.status.execution_id
        == "system-child-001"
    )
    assert (
        child.status.state
        is BackendExecutionState.COMPLETED
    )

    assert parent.terminal
    assert parent.successful


def test_public_hierarchical_execution_types_are_available() -> None:
    from nodrix.system import (
        ChildSystemExecutionStatus as PublicStatus,
        PreparedChildSystemExecution as PublicPrepared,
        RunningChildSystemExecution as PublicRunning,
    )

    assert (
        PublicPrepared
        is PreparedChildSystemExecution
    )

    assert (
        PublicRunning
        is RunningChildSystemExecution
    )

    assert (
        PublicStatus
        is ChildSystemExecutionStatus
    )
