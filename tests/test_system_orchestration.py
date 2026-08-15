from __future__ import annotations

import pytest

from nodrix.system import (
    BackendCapabilities,
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    ExecutionScope,
    Graph,
    NodeInstance,
    OrchestrationError,
    PreparedExecution,
    SystemLink,
    SystemModel,
    SystemOrchestrator,
    Target,
    backend_context_for_scope,
    plan_execution_scopes,
    plan_system,
)


class RecordingBackend(ExecutionBackend):
    def __init__(
        self,
        backend_id: str,
        events: list[tuple[str, str, str]],
        *,
        fail_start: bool = False,
    ) -> None:
        super().__init__(
            backend_id,
            capabilities=BackendCapabilities(
                target_kinds={"host", "local"},
                transport_uses={"demo.transport"},
            ),
        )
        self.events = events
        self.fail_start = fail_start
        self.state = BackendExecutionState.PREPARED

    @staticmethod
    def _target(context: BackendContext) -> str:
        assert len(context.targets) == 1
        return context.targets[0].name

    def _prepare(self, context: BackendContext) -> PreparedExecution:
        target = self._target(context)
        self.events.append((target, self.backend_id, "prepare"))
        self.state = BackendExecutionState.PREPARED
        return PreparedExecution(
            backend=self.backend_id,
            context=context,
            payload={"target": target},
        )

    def _start(self, prepared: PreparedExecution) -> BackendExecutionHandle:
        target = self._target(prepared.context)
        self.events.append((target, self.backend_id, "start"))
        if self.fail_start:
            raise RuntimeError("synthetic start failure")
        self.state = BackendExecutionState.RUNNING
        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id=f"{target}-{self.backend_id}",
            prepared=prepared,
        )

    def _inspect(self, handle: BackendExecutionHandle) -> BackendExecutionStatus:
        target = self._target(handle.prepared.context)
        self.events.append((target, self.backend_id, "inspect"))
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=self.state,
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        target = self._target(handle.prepared.context)
        self.events.append((target, self.backend_id, "stop"))
        self.state = BackendExecutionState.STOPPED
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=self.state,
            details={"timeout_seconds": timeout_seconds},
        )


def _two_scope_plan():
    return plan_system(
        SystemModel(
            name="distributed-demo",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={"backend": "robot-exec"},
                ),
                Target(
                    name="workstation",
                    kind="host",
                    properties={"backend": "desktop-exec"},
                ),
            ),
            graphs=(
                Graph(
                    name="robot_graph",
                    nodes=(
                        NodeInstance(
                            name="producer",
                            uses="demo.producer",
                            target="robot",
                        ),
                    ),
                ),
                Graph(
                    name="desktop_graph",
                    nodes=(
                        NodeInstance(
                            name="consumer",
                            uses="demo.consumer",
                            target="workstation",
                        ),
                    ),
                ),
            ),
        )
    )


def test_plan_execution_scopes_keeps_target_and_backend_separate() -> None:
    plan = _two_scope_plan()

    assert plan_execution_scopes(plan) == (
        ExecutionScope("robot", "robot-exec"),
        ExecutionScope("workstation", "desktop-exec"),
    )


def test_scope_context_splits_cross_target_link_even_for_same_backend_kind() -> None:
    plan = plan_system(
        SystemModel(
            name="same-backend-two-hosts",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={"backend": "worker"},
                ),
                Target(
                    name="workstation",
                    kind="host",
                    properties={"backend": "worker"},
                ),
            ),
            graphs=(
                Graph(
                    name="capture",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="demo.source",
                            target="robot",
                        ),
                    ),
                ),
                Graph(
                    name="view",
                    nodes=(
                        NodeInstance(
                            name="sink",
                            uses="demo.sink",
                            target="workstation",
                        ),
                    ),
                ),
            ),
            links=(
                SystemLink(
                    **{
                        "from": "capture/source.output",
                        "to": "view/sink.input",
                        "uses": "demo.transport",
                    }
                ),
            ),
        )
    )

    robot = backend_context_for_scope(
        plan,
        ExecutionScope("robot", "worker"),
    )
    workstation = backend_context_for_scope(
        plan,
        ExecutionScope("workstation", "worker"),
    )

    assert [node.id for node in robot.nodes] == ["capture/source"]
    assert robot.internal_links == ()
    assert len(robot.outbound_links) == 1
    assert robot.inbound_links == ()

    assert [node.id for node in workstation.nodes] == ["view/sink"]
    assert workstation.internal_links == ()
    assert len(workstation.inbound_links) == 1
    assert workstation.outbound_links == ()


def test_scope_model_supports_backend_override_inside_one_target() -> None:
    plan = plan_system(
        SystemModel(
            name="mixed-backend-host",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={"backend": "cpu"},
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="preprocess",
                            uses="demo.preprocess",
                            target="robot",
                        ),
                        NodeInstance(
                            name="inference",
                            uses="demo.inference",
                            target="robot",
                            backend="accelerator",
                        ),
                    ),
                ),
            ),
        )
    )

    assert plan_execution_scopes(plan) == (
        ExecutionScope("robot", "cpu"),
        ExecutionScope("robot", "accelerator"),
    )


def test_orchestrator_reports_missing_and_mismatched_bindings() -> None:
    plan = _two_scope_plan()
    events: list[tuple[str, str, str]] = []

    missing = SystemOrchestrator(
        {("robot", "robot-exec"): RecordingBackend("robot-exec", events)}
    ).validate_plan(plan)
    assert not missing.valid
    assert any(item.code == "ORCH101" for item in missing.errors)

    mismatched = SystemOrchestrator(
        {
            ("robot", "robot-exec"): RecordingBackend("wrong", events),
            ("workstation", "desktop-exec"): RecordingBackend(
                "desktop-exec", events
            ),
        }
    ).validate_plan(plan)
    assert not mismatched.valid
    assert any(item.code == "ORCH102" for item in mismatched.errors)


def test_orchestrator_runs_multiple_scopes_and_stops_in_reverse_order() -> None:
    plan = _two_scope_plan()
    events: list[tuple[str, str, str]] = []
    robot = RecordingBackend("robot-exec", events)
    desktop = RecordingBackend("desktop-exec", events)
    orchestrator = SystemOrchestrator(
        {
            ("robot", "robot-exec"): robot,
            ("workstation", "desktop-exec"): desktop,
        }
    )

    report = orchestrator.validate_plan(plan)
    assert report.valid

    prepared = orchestrator.prepare_plan(plan)
    assert events == [
        ("robot", "robot-exec", "prepare"),
        ("workstation", "desktop-exec", "prepare"),
    ]

    handle = orchestrator.start(prepared)
    assert events[-2:] == [
        ("robot", "robot-exec", "start"),
        ("workstation", "desktop-exec", "start"),
    ]

    status = orchestrator.inspect(handle)
    assert status.state is BackendExecutionState.RUNNING
    assert not status.terminal

    stopped = orchestrator.stop(handle, timeout_seconds=2.5)
    assert stopped.state is BackendExecutionState.STOPPED
    assert stopped.terminal
    assert stopped.successful
    assert events[-2:] == [
        ("workstation", "desktop-exec", "stop"),
        ("robot", "robot-exec", "stop"),
    ]
    assert all(
        item.status.details["timeout_seconds"] == 2.5
        for item in stopped.scopes
    )


def test_start_failure_rolls_back_already_started_scopes() -> None:
    plan = _two_scope_plan()
    events: list[tuple[str, str, str]] = []
    orchestrator = SystemOrchestrator(
        {
            ("robot", "robot-exec"): RecordingBackend("robot-exec", events),
            ("workstation", "desktop-exec"): RecordingBackend(
                "desktop-exec",
                events,
                fail_start=True,
            ),
        }
    )

    prepared = orchestrator.prepare_plan(plan)
    with pytest.raises(OrchestrationError) as exc_info:
        orchestrator.start(prepared, rollback_timeout_seconds=1.0)

    assert exc_info.value.code == "ORCH202"
    assert events[-3:] == [
        ("robot", "robot-exec", "start"),
        ("workstation", "desktop-exec", "start"),
        ("robot", "robot-exec", "stop"),
    ]


def test_same_backend_kind_can_use_distinct_instances_per_target() -> None:
    plan = plan_system(
        SystemModel(
            name="worker-pool",
            targets=(
                Target(name="robot", kind="host", properties={"backend": "worker"}),
                Target(
                    name="workstation",
                    kind="host",
                    properties={"backend": "worker"},
                ),
            ),
            graphs=(
                Graph(
                    name="a",
                    nodes=(
                        NodeInstance(
                            name="one",
                            uses="demo.one",
                            target="robot",
                        ),
                    ),
                ),
                Graph(
                    name="b",
                    nodes=(
                        NodeInstance(
                            name="two",
                            uses="demo.two",
                            target="workstation",
                        ),
                    ),
                ),
            ),
        )
    )
    events: list[tuple[str, str, str]] = []
    robot_backend = RecordingBackend("worker", events)
    workstation_backend = RecordingBackend("worker", events)
    orchestrator = SystemOrchestrator(
        {
            ("robot", "worker"): robot_backend,
            ("workstation", "worker"): workstation_backend,
        }
    )

    prepared = orchestrator.prepare_plan(plan)

    assert prepared.scopes[0].backend is robot_backend
    assert prepared.scopes[1].backend is workstation_backend
    assert prepared.scopes[0].prepared.context.targets[0].name == "robot"
    assert prepared.scopes[1].prepared.context.targets[0].name == "workstation"


def test_orchestrator_is_exposed_through_plyctl_public_api() -> None:
    from plyctl import SystemOrchestrator as PublicSystemOrchestrator

    assert PublicSystemOrchestrator is SystemOrchestrator
