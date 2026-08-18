from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from nodrix.system import (
    BackendCapabilities,
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    ExecutionHealthState,
    ExecutionObservation,
    Graph,
    NodeInstance,
    OrchestrationError,
    PreparedExecution,
    SystemDependency,
    SystemInstance,
    SystemModel,
    SystemOrchestrator,
    SystemStartupEvent,
    SystemStartupEventKind,
    plan_system,
)
from nodrix.system.definition import system_definition_record


@dataclass
class FakeClock:
    now: float = 0.0
    waits: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.now

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


ObservationProvider = Callable[
    [str, float],
    ExecutionObservation | None,
]
StateProvider = Callable[
    [str, float],
    BackendExecutionState,
]


class DependencyBackend(ExecutionBackend):
    def __init__(
        self,
        clock: FakeClock,
        *,
        observation: ObservationProvider,
        state: StateProvider | None = None,
        start_delays: dict[str, float] | None = None,
    ) -> None:
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds=frozenset({"local", "host"}),
                features=frozenset({"readiness", "health"}),
            ),
        )
        self.clock = clock
        self.observation = observation
        self.state = state or (
            lambda _system, _now: BackendExecutionState.RUNNING
        )
        self.start_delays = dict(start_delays or {})
        self.events: list[tuple[str, str, float]] = []
        self.system_by_execution: dict[str, str] = {}
        self.counter = 0

    def _prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        return PreparedExecution(
            backend=self.backend_id,
            context=context,
        )

    def _start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        system = prepared.context.plan.system
        self.events.append((system, "start", self.clock()))
        self.clock.advance(
            self.start_delays.get(system, 0.0)
        )
        self.counter += 1
        execution_id = f"{system}-{self.counter}"
        self.system_by_execution[execution_id] = system
        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id=execution_id,
            prepared=prepared,
        )

    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        system = self.system_by_execution[handle.execution_id]
        self.events.append((system, "inspect", self.clock()))
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=self.state(system, self.clock()),
            observation=self.observation(system, self.clock()),
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        system = self.system_by_execution[handle.execution_id]
        self.events.append((system, "stop", self.clock()))
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=BackendExecutionState.STOPPED,
            observation=self.observation(system, self.clock()),
            details={"timeout_seconds": timeout_seconds},
        )


def _child(name: str) -> SystemModel:
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


def _plan(
    names: tuple[str, ...],
    dependencies: tuple[SystemDependency, ...],
):
    definitions = {
        name: _child(name)
        for name in names
    }
    revisions = {
        name: system_definition_record(system).revision
        for name, system in definitions.items()
    }
    parent = SystemModel(
        name="parent",
        systems=tuple(
            SystemInstance(
                name=name,
                uses=revisions[name].canonical,
            )
            for name in names
        ),
        dependencies=dependencies,
    )
    by_revision = {
        revisions[name].canonical: definitions[name]
        for name in names
    }
    return plan_system(
        parent,
        system_resolver=lambda requested: by_revision.get(
            requested.canonical
        ),
    )


def _dependency(
    system: str,
    requires: str,
    condition: str,
    timeout: float = 1.0,
) -> SystemDependency:
    return SystemDependency.model_validate(
        {
            "system": system,
            "requires": requires,
            "condition": condition,
            "timeoutSeconds": timeout,
        }
    )


def _orchestrator(
    backend: DependencyBackend,
    clock: FakeClock,
) -> SystemOrchestrator:
    return SystemOrchestrator(
        {("local", "local"): backend},
        clock=clock,
        wait=clock.wait,
        dependency_poll_interval_seconds=0.1,
    )


def _action_systems(
    backend: DependencyBackend,
    action: str,
) -> list[str]:
    return [
        system
        for system, event, _ in backend.events
        if event == action
    ]


def test_started_dependency_uses_compiled_order_and_reverse_actual_stop() -> None:
    clock = FakeClock()
    backend = DependencyBackend(
        clock,
        observation=lambda _system, _now: ExecutionObservation(
            ready=True,
            health=ExecutionHealthState.HEALTHY,
        ),
    )
    plan = _plan(
        ("b", "c", "a"),
        (_dependency("b", "a", "started"),),
    )
    orchestrator = _orchestrator(backend, clock)

    handle = orchestrator.start(orchestrator.prepare_plan(plan))

    assert [child.name for child in handle.systems] == ["c", "a", "b"]
    assert _action_systems(backend, "start") == ["c", "a", "b"]

    orchestrator.stop(handle)
    assert _action_systems(backend, "stop") == ["b", "a", "c"]


def test_ready_dependency_waits_without_blocking_independent_root() -> None:
    clock = FakeClock()
    backend = DependencyBackend(
        clock,
        observation=lambda system, now: ExecutionObservation(
            ready=(now >= 0.3 if system == "a" else True),
            health=ExecutionHealthState.HEALTHY,
        ),
    )
    plan = _plan(
        ("a", "c", "b"),
        (_dependency("b", "a", "ready"),),
    )
    orchestrator = _orchestrator(backend, clock)
    startup_events: list[SystemStartupEvent] = []

    orchestrator.start(
        orchestrator.prepare_plan(plan),
        startup_event_sink=startup_events.append,
    )

    starts = [
        (system, at)
        for system, event, at in backend.events
        if event == "start"
    ]
    assert [system for system, _ in starts] == ["a", "c", "b"]
    assert [at for _, at in starts] == pytest.approx([0.0, 0.0, 0.3])
    assert clock.waits == pytest.approx([0.1, 0.1, 0.1])
    assert [event.event for event in startup_events] == [
        SystemStartupEventKind.CHILD_STARTED,
        SystemStartupEventKind.CHILD_STARTED,
        SystemStartupEventKind.DEPENDENCY_WAITING,
        SystemStartupEventKind.DEPENDENCY_SATISFIED,
        SystemStartupEventKind.CHILD_STARTED,
    ]
    dependency_events = [
        event
        for event in startup_events
        if event.requires is not None
    ]
    assert [event.elapsed_seconds for event in dependency_events] == (
        pytest.approx([0.0, 0.3])
    )


def test_satisfied_dependency_is_a_startup_latch() -> None:
    clock = FakeClock()
    backend = DependencyBackend(
        clock,
        observation=lambda system, now: ExecutionObservation(
            ready=(
                now < 0.1
                if system == "a"
                else now >= 0.2
            ),
            health=ExecutionHealthState.HEALTHY,
        ),
    )
    plan = _plan(
        ("a", "c", "b"),
        (
            _dependency("b", "a", "ready"),
            _dependency("b", "c", "ready"),
        ),
    )
    orchestrator = _orchestrator(backend, clock)

    orchestrator.start(orchestrator.prepare_plan(plan))

    assert _action_systems(backend, "start") == ["a", "c", "b"]
    assert sum(
        system == "a" and event == "inspect"
        for system, event, _ in backend.events
    ) == 1
    assert next(
        at
        for system, event, at in backend.events
        if system == "b" and event == "start"
    ) == pytest.approx(0.2)


def test_healthy_dependency_waits_through_degraded_observation() -> None:
    clock = FakeClock()
    backend = DependencyBackend(
        clock,
        observation=lambda system, now: ExecutionObservation(
            ready=True,
            health=(
                ExecutionHealthState.DEGRADED
                if system == "a" and now < 0.2
                else ExecutionHealthState.HEALTHY
            ),
        ),
    )
    plan = _plan(
        ("b", "a"),
        (_dependency("b", "a", "healthy"),),
    )
    orchestrator = _orchestrator(backend, clock)

    orchestrator.start(orchestrator.prepare_plan(plan))

    assert _action_systems(backend, "start") == ["a", "b"]
    assert next(
        at
        for system, event, at in backend.events
        if system == "b" and event == "start"
    ) == pytest.approx(0.2)


def test_dependency_timeout_rolls_back_reverse_actual_start_order() -> None:
    clock = FakeClock()
    backend = DependencyBackend(
        clock,
        observation=lambda _system, _now: ExecutionObservation(
            ready=False,
            health=ExecutionHealthState.HEALTHY,
        ),
    )
    plan = _plan(
        ("a", "c", "b"),
        (_dependency("b", "a", "ready", timeout=0.25),),
    )
    orchestrator = _orchestrator(backend, clock)

    with pytest.raises(OrchestrationError) as exc_info:
        orchestrator.start(
            orchestrator.prepare_plan(plan),
            rollback_timeout_seconds=2.0,
        )

    assert exc_info.value.code == "ORCH301"
    assert exc_info.value.path == "dependencies.0"
    assert clock() == pytest.approx(0.25)
    assert _action_systems(backend, "start") == ["a", "c"]
    assert _action_systems(backend, "stop") == ["c", "a"]


def test_dependency_deadline_begins_when_prerequisite_start_is_invoked() -> None:
    clock = FakeClock()
    backend = DependencyBackend(
        clock,
        observation=lambda _system, _now: ExecutionObservation(
            ready=True,
            health=ExecutionHealthState.HEALTHY,
        ),
        start_delays={"a": 0.3},
    )
    plan = _plan(
        ("b", "a"),
        (_dependency("b", "a", "started", timeout=0.25),),
    )
    orchestrator = _orchestrator(backend, clock)

    with pytest.raises(OrchestrationError) as exc_info:
        orchestrator.start(orchestrator.prepare_plan(plan))

    assert exc_info.value.code == "ORCH301"
    assert clock() == pytest.approx(0.3)
    assert _action_systems(backend, "start") == ["a"]
    assert _action_systems(backend, "stop") == ["a"]


@pytest.mark.parametrize(
    ("state", "observation", "code"),
    [
        (
            BackendExecutionState.FAILED,
            ExecutionObservation(
                ready=False,
                health=ExecutionHealthState.UNHEALTHY,
                message="driver exited",
            ),
            "ORCH302",
        ),
        (
            BackendExecutionState.RUNNING,
            ExecutionObservation(
                ready=False,
                health=ExecutionHealthState.UNHEALTHY,
                message="sensor disconnected",
            ),
            "ORCH303",
        ),
        (
            BackendExecutionState.RUNNING,
            None,
            "ORCH304",
        ),
    ],
)
def test_dependency_fails_immediately_for_terminal_unhealthy_or_unsupported(
    state: BackendExecutionState,
    observation: ExecutionObservation | None,
    code: str,
) -> None:
    clock = FakeClock()
    backend = DependencyBackend(
        clock,
        observation=lambda _system, _now: observation,
        state=lambda _system, _now: state,
    )
    plan = _plan(
        ("b", "a"),
        (_dependency("b", "a", "ready"),),
    )
    orchestrator = _orchestrator(backend, clock)

    with pytest.raises(OrchestrationError) as exc_info:
        orchestrator.start(orchestrator.prepare_plan(plan))

    assert exc_info.value.code == code
    assert clock.waits == []
    assert _action_systems(backend, "start") == ["a"]
    assert _action_systems(backend, "stop") == ["a"]
