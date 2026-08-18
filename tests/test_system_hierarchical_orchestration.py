from __future__ import annotations

import pytest

from nodrix.system import (
    BackendCapabilities,
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    Graph,
    NodeInstance,
    OrchestrationError,
    PreparedExecution,
    SystemInstance,
    SystemModel,
    SystemOrchestrator,
    Target,
    plan_execution_scopes,
    plan_system,
)
from nodrix.system.definition import (
    system_definition_record,
)


class HierarchyBackend(
    ExecutionBackend
):
    def __init__(
        self,
        events: list[
            tuple[str, str]
        ],
        *,
        fail_start_system: str | None = None,
        fail_inspect_system: str | None = None,
        fail_stop_system: str | None = None,
    ) -> None:
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds={
                    "local",
                    "host",
                },
            ),
        )

        self.events = events
        self.fail_start_system = (
            fail_start_system
        )
        self.fail_inspect_system = (
            fail_inspect_system
        )
        self.fail_stop_system = (
            fail_stop_system
        )
        self.states: dict[
            str,
            BackendExecutionState,
        ] = {}
        self.counter = 0

    def _prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        self.events.append(
            (
                context.plan.system,
                "prepare",
            )
        )

        return PreparedExecution(
            backend=self.backend_id,
            context=context,
        )

    def _start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        system = (
            prepared.context.plan.system
        )

        self.events.append(
            (
                system,
                "start",
            )
        )

        if (
            system
            == self.fail_start_system
        ):
            raise RuntimeError(
                f"cannot start {system}"
            )

        self.counter += 1
        execution_id = (
            f"{system}-{self.counter}"
        )

        self.states[
            execution_id
        ] = BackendExecutionState.RUNNING

        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id=execution_id,
            prepared=prepared,
        )

    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        system = (
            handle
            .prepared
            .context
            .plan
            .system
        )

        self.events.append(
            (
                system,
                "inspect",
            )
        )

        if (
            system
            == self.fail_inspect_system
        ):
            raise RuntimeError(
                f"cannot inspect {system}"
            )

        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=self.states[
                handle.execution_id
            ],
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        system = (
            handle
            .prepared
            .context
            .plan
            .system
        )

        self.events.append(
            (
                system,
                "stop",
            )
        )

        if (
            system
            == self.fail_stop_system
        ):
            raise RuntimeError(
                f"cannot stop {system}"
            )

        self.states[
            handle.execution_id
        ] = BackendExecutionState.STOPPED

        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=BackendExecutionState.STOPPED,
            details={
                "timeout_seconds": timeout_seconds,
            },
        )


def _work_system(
    name: str,
) -> SystemModel:
    return SystemModel(
        name=name,
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                    ),
                ),
            ),
        ),
    )


def _parent_and_child_plan(
    *,
    parent_has_work: bool = True,
):
    child = _work_system(
        "livox-mid360"
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
        graphs=(
            (
                Graph(
                    name="parent",
                    nodes=(
                        NodeInstance(
                            name="supervisor",
                            uses="demo.supervisor",
                        ),
                    ),
                ),
            )
            if parent_has_work
            else ()
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


def _orchestrator(
    backend: HierarchyBackend,
) -> SystemOrchestrator:
    return SystemOrchestrator(
        {
            (
                "local",
                "local",
            ): backend,
        }
    )


def test_parent_scopes_do_not_flatten_child_scopes() -> None:
    plan = _parent_and_child_plan(
        parent_has_work=False
    )

    assert (
        plan_execution_scopes(plan)
        == ()
    )

    assert (
        plan_execution_scopes(
            plan.child("lidar").plan
        )
        != ()
    )


def test_validate_plan_recurses_into_child_systems() -> None:
    child = SystemModel(
        name="remote-child",
        targets=(
            Target(
                name="remote",
                kind="host",
                properties={
                    "backend": "remote",
                },
            ),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                        target="remote",
                    ),
                ),
            ),
        ),
    )

    revision = (
        system_definition_record(
            child
        ).revision
    )

    parent = SystemModel(
        name="parent",
        systems=(
            SystemInstance(
                name="worker",
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

    orchestrator = SystemOrchestrator(
        {}
    )

    report = orchestrator.validate_plan(
        plan
    )

    assert not report.valid

    error = next(
        item
        for item in report.errors
        if item.code == "ORCH101"
    )

    assert error.scope is not None
    assert error.scope.id == (
        "remote:remote"
    )
    assert error.path.startswith(
        "systems.worker."
    )


def test_prepare_plan_recurses_without_creating_parent_scope() -> None:
    plan = _parent_and_child_plan(
        parent_has_work=False
    )

    events: list[
        tuple[str, str]
    ] = []

    backend = HierarchyBackend(
        events
    )

    prepared = _orchestrator(
        backend
    ).prepare_plan(
        plan
    )

    assert prepared.scopes == ()
    assert len(prepared.systems) == 1

    child = prepared.child(
        "lidar"
    )

    assert (
        child.execution.plan.system
        == "livox-mid360"
    )

    assert events == [
        (
            "livox-mid360",
            "prepare",
        ),
    ]


def test_start_creates_distinct_parent_and_child_execution_ids() -> None:
    plan = _parent_and_child_plan()

    events: list[
        tuple[str, str]
    ] = []

    backend = HierarchyBackend(
        events
    )
    orchestrator = _orchestrator(
        backend
    )

    prepared = orchestrator.prepare_plan(
        plan
    )
    handle = orchestrator.start(
        prepared
    )

    child = handle.child(
        "lidar"
    )

    assert (
        handle.execution_id
        != child.handle.execution_id
    )

    assert events == [
        ("robot", "prepare"),
        ("livox-mid360", "prepare"),
        ("robot", "start"),
        ("livox-mid360", "start"),
    ]


def test_inspect_aggregates_nested_child_failure() -> None:
    plan = _parent_and_child_plan()

    events: list[
        tuple[str, str]
    ] = []

    backend = HierarchyBackend(
        events
    )
    orchestrator = _orchestrator(
        backend
    )

    handle = orchestrator.start(
        orchestrator.prepare_plan(
            plan
        )
    )

    child_handle = (
        handle
        .child("lidar")
        .handle
    )

    backend.states[
        child_handle
        .scopes[0]
        .handle
        .execution_id
    ] = BackendExecutionState.FAILED

    status = orchestrator.inspect(
        handle
    )

    assert (
        status.state
        is BackendExecutionState.FAILED
    )

    assert (
        status
        .child("lidar")
        .status
        .state
        is BackendExecutionState.FAILED
    )


def test_stop_reverses_hierarchical_start_order() -> None:
    plan = _parent_and_child_plan()

    events: list[
        tuple[str, str]
    ] = []

    backend = HierarchyBackend(
        events
    )
    orchestrator = _orchestrator(
        backend
    )

    handle = orchestrator.start(
        orchestrator.prepare_plan(
            plan
        )
    )

    events.clear()

    status = orchestrator.stop(
        handle,
        timeout_seconds=2.5,
    )

    assert events == [
        ("livox-mid360", "stop"),
        ("robot", "stop"),
    ]

    assert (
        status.state
        is BackendExecutionState.STOPPED
    )

    assert (
        status
        .child("lidar")
        .status
        .state
        is BackendExecutionState.STOPPED
    )


def test_child_start_failure_rolls_back_parent_scope() -> None:
    plan = _parent_and_child_plan()

    events: list[
        tuple[str, str]
    ] = []

    backend = HierarchyBackend(
        events,
        fail_start_system=(
            "livox-mid360"
        ),
    )
    orchestrator = _orchestrator(
        backend
    )

    prepared = orchestrator.prepare_plan(
        plan
    )

    with pytest.raises(
        OrchestrationError
    ) as exc_info:
        orchestrator.start(
            prepared,
            rollback_timeout_seconds=1.0,
        )

    assert (
        exc_info.value.code
        == "ORCH204"
    )

    assert (
        exc_info.value.path
        == "systems.lidar"
    )

    assert events[-3:] == [
        ("robot", "start"),
        ("livox-mid360", "start"),
        ("robot", "stop"),
    ]


def _three_level_plan():
    driver = _work_system(
        "driver"
    )

    driver_revision = (
        system_definition_record(
            driver
        ).revision
    )

    lidar = SystemModel(
        name="lidar",
        systems=(
            SystemInstance(
                name="driver",
                uses=(
                    driver_revision.canonical
                ),
            ),
        ),
    )

    lidar_revision = (
        system_definition_record(
            lidar
        ).revision
    )

    robot = SystemModel(
        name="robot",
        systems=(
            SystemInstance(
                name="lidar",
                uses=(
                    lidar_revision.canonical
                ),
            ),
        ),
    )

    definitions = {
        driver_revision.canonical: driver,
        lidar_revision.canonical: lidar,
    }

    return plan_system(
        robot,
        system_resolver=(
            lambda requested: (
                definitions.get(
                    requested.canonical
                )
            )
        ),
    )


def test_deep_child_failure_propagates_to_root() -> None:
    plan = _three_level_plan()

    events: list[
        tuple[str, str]
    ] = []

    backend = HierarchyBackend(
        events
    )

    orchestrator = _orchestrator(
        backend
    )

    handle = orchestrator.start(
        orchestrator.prepare_plan(
            plan
        )
    )

    driver_handle = (
        handle
        .child("lidar")
        .handle
        .child("driver")
        .handle
    )

    backend.states[
        driver_handle
        .scopes[0]
        .handle
        .execution_id
    ] = BackendExecutionState.FAILED

    status = orchestrator.inspect(
        handle
    )

    lidar_status = (
        status
        .child("lidar")
        .status
    )

    driver_status = (
        lidar_status
        .child("driver")
        .status
    )

    assert (
        driver_status.state
        is BackendExecutionState.FAILED
    )

    assert (
        lidar_status.state
        is BackendExecutionState.FAILED
    )

    assert (
        status.state
        is BackendExecutionState.FAILED
    )


def test_child_inspect_exception_is_preserved() -> None:
    plan = _parent_and_child_plan(
        parent_has_work=False
    )

    events: list[
        tuple[str, str]
    ] = []

    backend = HierarchyBackend(
        events,
        fail_inspect_system=(
            "livox-mid360"
        ),
    )

    orchestrator = _orchestrator(
        backend
    )

    handle = orchestrator.start(
        orchestrator.prepare_plan(
            plan
        )
    )

    status = orchestrator.inspect(
        handle
    )

    child = (
        status
        .child("lidar")
        .status
    )

    assert (
        status.state
        is BackendExecutionState.FAILED
    )

    assert (
        child.state
        is BackendExecutionState.FAILED
    )

    assert (
        child.message
        == "cannot inspect livox-mid360"
    )

    assert (
        child.details[
            "exception_type"
        ]
        == "RuntimeError"
    )


def test_child_stop_exception_is_preserved() -> None:
    plan = _parent_and_child_plan(
        parent_has_work=False
    )

    events: list[
        tuple[str, str]
    ] = []

    backend = HierarchyBackend(
        events,
        fail_stop_system=(
            "livox-mid360"
        ),
    )

    orchestrator = _orchestrator(
        backend
    )

    handle = orchestrator.start(
        orchestrator.prepare_plan(
            plan
        )
    )

    status = orchestrator.stop(
        handle
    )

    child = (
        status
        .child("lidar")
        .status
    )

    assert (
        status.state
        is BackendExecutionState.FAILED
    )

    assert (
        child.state
        is BackendExecutionState.FAILED
    )

    assert (
        child.message
        == "cannot stop livox-mid360"
    )

    assert (
        child.details[
            "exception_type"
        ]
        == "RuntimeError"
    )


def test_later_child_start_failure_rolls_back_started_child_then_parent() -> None:
    first = _work_system(
        "child-a"
    )
    second = _work_system(
        "child-b"
    )

    first_revision = (
        system_definition_record(
            first
        ).revision
    )
    second_revision = (
        system_definition_record(
            second
        ).revision
    )

    parent = SystemModel(
        name="parent",
        graphs=(
            Graph(
                name="parent",
                nodes=(
                    NodeInstance(
                        name="supervisor",
                        uses="demo.supervisor",
                    ),
                ),
            ),
        ),
        systems=(
            SystemInstance(
                name="a",
                uses=(
                    first_revision.canonical
                ),
            ),
            SystemInstance(
                name="b",
                uses=(
                    second_revision.canonical
                ),
            ),
        ),
    )

    definitions = {
        first_revision.canonical: first,
        second_revision.canonical: second,
    }

    plan = plan_system(
        parent,
        system_resolver=(
            lambda requested: (
                definitions.get(
                    requested.canonical
                )
            )
        ),
    )

    events: list[
        tuple[str, str]
    ] = []

    backend = HierarchyBackend(
        events,
        fail_start_system="child-b",
    )

    orchestrator = _orchestrator(
        backend
    )

    prepared = orchestrator.prepare_plan(
        plan
    )

    with pytest.raises(
        OrchestrationError
    ) as exc_info:
        orchestrator.start(
            prepared,
            rollback_timeout_seconds=1.0,
        )

    assert (
        exc_info.value.code
        == "ORCH204"
    )

    assert events[-5:] == [
        ("parent", "start"),
        ("child-a", "start"),
        ("child-b", "start"),
        ("child-a", "stop"),
        ("parent", "stop"),
    ]
