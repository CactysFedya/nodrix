"""Target/backend orchestration for Nodrix 2.8.

The planner decides *where* work belongs (Target) and *how* it should be
executed (backend id).  This module owns the next layer: coordinating every
``(target, backend)`` execution scope as one System lifecycle.

It deliberately does not implement remote deployment or cross-scope data
transport.  Backends remain responsible for one scope; transports and remote
agents can be added behind the same orchestration boundary in later 2.8
milestones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

from ..errors import NodrixError
from .backend import (
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    BackendSystemLink,
    ExecutionBackend,
    ExecutionHealthState,
    ExecutionObservation,
    PreparedExecution,
)
from .execution_context import (
    SystemExecutionContext,
    SystemExecutionContextBindingError,
    child_system_execution_context,
    validate_system_execution_context_binding,
)
from .dependencies import SystemDependencyCondition
from .planning import (
    PlannedChildSystemResourceBinding,
    PlannedSystemDependency,
    PlannedSystemInstance,
    PlannedTarget,
    SystemExecutionPlan,
)
from .graph import SystemEndpointKind, parse_system_endpoint


class OrchestrationError(NodrixError):
    """The resolved System cannot be coordinated as one execution."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str = "",
    ) -> None:
        self.code = code
        self.path = path
        self.message = message
        prefix = code if not path else f"{code} {path}"
        super().__init__(f"{prefix}: {message}")


@dataclass(frozen=True, slots=True)
class ExecutionScope:
    """Smallest independently controlled System execution scope.

    ``target`` answers *where* work runs. ``backend`` answers *how* that work is
    executed.  Keeping both dimensions is important because one backend kind
    can serve multiple targets and one target can contain backend overrides.
    """

    target: str
    backend: str

    def __post_init__(self) -> None:
        target = self.target.strip()
        backend = self.backend.strip()
        if not target:
            raise ValueError("ExecutionScope.target must be non-empty")
        if not backend:
            raise ValueError("ExecutionScope.backend must be non-empty")
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "backend", backend)

    @property
    def id(self) -> str:
        return f"{self.target}:{self.backend}"


@dataclass(frozen=True, slots=True)
class _RoutedSystemLink:
    binding: BackendSystemLink
    remaining_system_path: tuple[str, ...]
    target: str
    backend: str


def _resolve_system_link_endpoint(
    plan: SystemExecutionPlan,
    value: str,
    *,
    direction: str,
) -> tuple[tuple[str, ...], str]:
    """Resolve a public endpoint through arbitrarily nested child Systems."""

    current = plan
    current_value = value
    system_path: list[str] = []

    while True:
        endpoint = parse_system_endpoint(current_value)
        if endpoint.kind is not SystemEndpointKind.SYSTEM:
            return tuple(system_path), current_value

        child = current.child(endpoint.instance)
        system_path.append(child.name)
        if direction == "source":
            binding = child.plan.bindings.output(endpoint.port)
        else:
            binding = child.plan.bindings.input(endpoint.port)
        current = child.plan
        current_value = binding.endpoint


def _plan_system_link_routes(
    plan: SystemExecutionPlan,
) -> tuple[_RoutedSystemLink, ...]:
    routes: list[_RoutedSystemLink] = []
    for link in plan.links:
        if link.boundary != "system":
            continue

        source_path, source_endpoint = _resolve_system_link_endpoint(
            plan,
            link.source,
            direction="source",
        )
        target_path, target_endpoint = _resolve_system_link_endpoint(
            plan,
            link.target,
            direction="target",
        )
        routes.extend(
            (
                _RoutedSystemLink(
                    binding=BackendSystemLink(
                        link=link,
                        direction="outbound",
                        local_endpoint=source_endpoint,
                        remote_endpoint=target_endpoint,
                        local_system_path=source_path,
                        remote_system_path=target_path,
                    ),
                    remaining_system_path=source_path,
                    target=link.source_target,
                    backend=link.source_backend,
                ),
                _RoutedSystemLink(
                    binding=BackendSystemLink(
                        link=link,
                        direction="inbound",
                        local_endpoint=target_endpoint,
                        remote_endpoint=source_endpoint,
                        local_system_path=target_path,
                        remote_system_path=source_path,
                    ),
                    remaining_system_path=target_path,
                    target=link.target_target,
                    backend=link.target_backend,
                ),
            )
        )
    return tuple(routes)


def plan_execution_scopes(plan: SystemExecutionPlan) -> tuple[ExecutionScope, ...]:
    """Return deterministic ``(target, backend)`` scopes used by a plan.

    Empty declarative targets do not require a backend binding.  A scope appears
    only when some executable/planned object, link endpoint, or artifact uses it.
    Target declaration order is authoritative; first occurrence of a backend
    inside that target is preserved.
    """

    discovered: list[ExecutionScope] = []
    seen: set[ExecutionScope] = set()

    def add(target: str | None, backend: str | None) -> None:
        if not target or not backend:
            return
        scope = ExecutionScope(target=target, backend=backend)
        if scope not in seen:
            seen.add(scope)
            discovered.append(scope)

    for item in plan.resources:
        add(item.target, item.backend)
    for item in plan.applications:
        add(item.target, item.backend)
    for graph in plan.graphs:
        for node in graph.nodes:
            add(node.target, node.backend)
        for connection in graph.connections:
            add(connection.placement_target, connection.backend)
    for link in plan.links:
        if link.boundary == "system":
            continue
        add(link.source_target, link.source_backend)
        add(link.target_target, link.target_backend)
    for artifact in plan.artifacts:
        add(artifact.target, artifact.backend)

    target_order = {target.name: index for index, target in enumerate(plan.targets)}
    discovery_order = {scope: index for index, scope in enumerate(discovered)}
    return tuple(
        sorted(
            discovered,
            key=lambda scope: (
                target_order.get(scope.target, len(target_order)),
                discovery_order[scope],
            ),
        )
    )


def backend_context_for_scope(
    plan: SystemExecutionPlan,
    scope: ExecutionScope,
    *,
    execution_context: SystemExecutionContext | None = None,
    inherited_resources: tuple[
        PlannedChildSystemResourceBinding,
        ...,
    ] = (),
    system_inbound_links: tuple[BackendSystemLink, ...] = (),
    system_outbound_links: tuple[BackendSystemLink, ...] = (),
) -> BackendContext:
    """Project one global SystemExecutionPlan into one orchestration scope."""

    try:
        target: PlannedTarget = plan.target(scope.target)
    except KeyError as exc:
        raise OrchestrationError(
            "ORCH001",
            f"execution scope references unknown target {scope.target!r}",
            path="scope.target",
        ) from exc

    resources = tuple(
        item
        for item in plan.resources
        if item.target == scope.target and item.backend == scope.backend
    )
    applications = tuple(
        item
        for item in plan.applications
        if item.target == scope.target and item.backend == scope.backend
    )
    nodes = tuple(
        node
        for graph in plan.graphs
        for node in graph.nodes
        if node.target == scope.target and node.backend == scope.backend
    )
    connections = tuple(
        connection
        for graph in plan.graphs
        for connection in graph.connections
        if (
            connection.placement_target == scope.target
            and connection.backend == scope.backend
        )
    )

    def is_source(link) -> bool:
        return (
            link.source_target == scope.target
            and link.source_backend == scope.backend
        )

    def is_target(link) -> bool:
        return (
            link.target_target == scope.target
            and link.target_backend == scope.backend
        )

    internal_links = tuple(
        link
        for link in plan.links
        if (
            link.boundary != "system"
            and is_source(link)
            and is_target(link)
        )
    )
    inbound_links = tuple(
        link
        for link in plan.links
        if (
            link.boundary != "system"
            and is_target(link)
            and not is_source(link)
        )
    )
    outbound_links = tuple(
        link
        for link in plan.links
        if (
            link.boundary != "system"
            and is_source(link)
            and not is_target(link)
        )
    )
    artifacts = tuple(
        item
        for item in plan.artifacts
        if item.target == scope.target and item.backend == scope.backend
    )

    resource_names = {item.name for item in resources}
    resource_order = tuple(
        name for name in plan.resource_order if name in resource_names
    )

    return BackendContext(
        plan=plan,
        backend=scope.backend,
        execution_context=execution_context,
        system_parameters={
            parameter.name: parameter.value
            for parameter in plan.parameters
            if parameter.configured or parameter.default is not None
        },
        inherited_resources=tuple(
            binding
            for binding in inherited_resources
            if (
                binding.target == scope.target
                and binding.backend == scope.backend
            )
        ),
        targets=(target,),
        resources=resources,
        resource_order=resource_order,
        applications=applications,
        nodes=nodes,
        connections=connections,
        internal_links=internal_links,
        inbound_links=inbound_links,
        outbound_links=outbound_links,
        system_inbound_links=system_inbound_links,
        system_outbound_links=system_outbound_links,
        artifacts=artifacts,
    )


@dataclass(frozen=True, slots=True)
class OrchestrationDiagnostic:
    level: str
    code: str
    message: str
    scope: ExecutionScope | None = None
    path: str = ""
    source: str = "orchestrator"

    def __post_init__(self) -> None:
        if self.level not in {"error", "warning"}:
            raise ValueError(
                "OrchestrationDiagnostic.level must be 'error' or 'warning'"
            )


@dataclass(frozen=True, slots=True)
class OrchestrationValidationReport:
    scopes: tuple[ExecutionScope, ...] = ()
    diagnostics: tuple[OrchestrationDiagnostic, ...] = ()

    @property
    def errors(self) -> tuple[OrchestrationDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.level == "error")

    @property
    def warnings(self) -> tuple[OrchestrationDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.level == "warning")

    @property
    def valid(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise OrchestrationValidationError(self)


class OrchestrationValidationError(OrchestrationError):
    def __init__(self, report: OrchestrationValidationReport) -> None:
        self.report = report
        detail = "; ".join(
            (
                f"{item.code} "
                f"{item.scope.id if item.scope is not None else '-'} "
                f"{item.path}: {item.message}"
            ).strip()
            for item in report.errors
        )
        super().__init__(
            "ORCH100",
            detail or "orchestration validation failed",
        )


@dataclass(frozen=True, slots=True)
class PreparedScopeExecution:
    scope: ExecutionScope
    backend: ExecutionBackend = field(repr=False, compare=False)
    prepared: PreparedExecution


@dataclass(frozen=True, slots=True)
class PreparedChildSystemExecution:
    """Prepared execution of one child System instance."""

    instance: PlannedSystemInstance
    execution: "PreparedSystemExecution"

    def __post_init__(self) -> None:
        if not isinstance(
            self.instance,
            PlannedSystemInstance,
        ):
            raise TypeError(
                "instance must be a PlannedSystemInstance"
            )

        if not isinstance(
            self.execution,
            PreparedSystemExecution,
        ):
            raise TypeError(
                "execution must be a PreparedSystemExecution"
            )

        if (
            self.execution.plan
            != self.instance.plan
        ):
            raise ValueError(
                "prepared child execution belongs to "
                "a different child System plan"
            )

    @property
    def ordinal(self) -> int:
        return self.instance.ordinal

    @property
    def name(self) -> str:
        return self.instance.name

    @property
    def revision(self) -> str:
        return self.instance.revision


@dataclass(frozen=True, slots=True)
class PreparedSystemExecution:
    plan: SystemExecutionPlan
    execution_context: SystemExecutionContext | None = field(
        default=None,
        repr=False,
    )
    inherited_resources: tuple[
        PlannedChildSystemResourceBinding,
        ...,
    ] = ()
    system_links: tuple[BackendSystemLink, ...] = ()
    scopes: tuple[PreparedScopeExecution, ...] = ()
    systems: tuple[PreparedChildSystemExecution, ...] = ()

    def child(
        self,
        name: str,
    ) -> PreparedChildSystemExecution:
        for child in self.systems:
            if child.name == name:
                return child

        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class RunningScopeExecution:
    scope: ExecutionScope
    backend: ExecutionBackend = field(repr=False, compare=False)
    handle: BackendExecutionHandle


@dataclass(frozen=True, slots=True)
class RunningChildSystemExecution:
    """Live handle for one nested child System execution."""

    instance: PlannedSystemInstance
    handle: "SystemExecutionHandle"

    def __post_init__(self) -> None:
        if not isinstance(
            self.instance,
            PlannedSystemInstance,
        ):
            raise TypeError(
                "instance must be a PlannedSystemInstance"
            )

        if not isinstance(
            self.handle,
            SystemExecutionHandle,
        ):
            raise TypeError(
                "handle must be a SystemExecutionHandle"
            )

        if (
            self.handle.prepared.plan
            != self.instance.plan
        ):
            raise ValueError(
                "running child execution belongs to "
                "a different child System plan"
            )

    @property
    def ordinal(self) -> int:
        return self.instance.ordinal

    @property
    def name(self) -> str:
        return self.instance.name

    @property
    def revision(self) -> str:
        return self.instance.revision


@dataclass(frozen=True, slots=True)
class SystemExecutionHandle:
    execution_id: str
    prepared: PreparedSystemExecution
    scopes: tuple[RunningScopeExecution, ...] = ()
    systems: tuple[RunningChildSystemExecution, ...] = ()

    def child(
        self,
        name: str,
    ) -> RunningChildSystemExecution:
        for child in self.systems:
            if child.name == name:
                return child

        raise KeyError(name)


class SystemStartupEventKind(StrEnum):
    """Observable transition emitted by the 2.20 startup scheduler."""

    CHILD_STARTED = "child_started"
    DEPENDENCY_WAITING = "dependency_waiting"
    DEPENDENCY_SATISFIED = "dependency_satisfied"
    DEPENDENCY_FAILED = "dependency_failed"


@dataclass(frozen=True, slots=True)
class SystemStartupEvent:
    """Typed startup event independent from CLI and storage formats."""

    event: SystemStartupEventKind
    execution_id: str
    system: str
    child: str
    child_execution_id: str | None = None
    dependency_ordinal: int | None = None
    requires: str | None = None
    condition: SystemDependencyCondition | None = None
    timeout_seconds: float | None = None
    elapsed_seconds: float | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event, SystemStartupEventKind):
            raise TypeError("event must be a SystemStartupEventKind")

        for field_name in (
            "execution_id",
            "system",
            "child",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())

        if (
            self.child_execution_id is not None
            and (
                not isinstance(self.child_execution_id, str)
                or not self.child_execution_id.strip()
            )
        ):
            raise ValueError(
                "child_execution_id must be a non-empty string or None"
            )

        if (
            self.message is not None
            and (
                not isinstance(self.message, str)
                or not self.message.strip()
            )
        ):
            raise ValueError("message must be a non-empty string or None")

        if self.event is SystemStartupEventKind.CHILD_STARTED:
            if not self.child_execution_id:
                raise ValueError(
                    "child_started events require child_execution_id"
                )
            return

        if (
            not isinstance(self.dependency_ordinal, int)
            or isinstance(self.dependency_ordinal, bool)
            or self.dependency_ordinal < 0
        ):
            raise ValueError(
                "dependency_ordinal must be a non-negative integer"
            )
        if not isinstance(self.requires, str) or not self.requires.strip():
            raise ValueError("requires must be a non-empty string")
        if not isinstance(self.condition, SystemDependencyCondition):
            raise TypeError("condition must be a SystemDependencyCondition")
        if (
            self.timeout_seconds is None
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if (
            self.elapsed_seconds is None
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError(
                "elapsed_seconds must be finite and non-negative"
            )


@dataclass(frozen=True, slots=True)
class ScopeExecutionStatus:
    scope: ExecutionScope
    status: BackendExecutionStatus


@dataclass(frozen=True, slots=True)
class ChildSystemExecutionStatus:
    """Observed lifecycle state of one nested child System."""

    instance: PlannedSystemInstance
    status: "SystemExecutionStatus"

    def __post_init__(self) -> None:
        if not isinstance(
            self.instance,
            PlannedSystemInstance,
        ):
            raise TypeError(
                "instance must be a PlannedSystemInstance"
            )

        if not isinstance(
            self.status,
            SystemExecutionStatus,
        ):
            raise TypeError(
                "status must be a SystemExecutionStatus"
            )

    @property
    def ordinal(self) -> int:
        return self.instance.ordinal

    @property
    def name(self) -> str:
        return self.instance.name

    @property
    def revision(self) -> str:
        return self.instance.revision


@dataclass(frozen=True, slots=True)
class SystemExecutionStatus:
    execution_id: str
    state: BackendExecutionState
    scopes: tuple[ScopeExecutionStatus, ...] = ()
    systems: tuple[ChildSystemExecutionStatus, ...] = ()
    message: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    observation: ExecutionObservation | None = None

    def __post_init__(self) -> None:
        if (
            self.message is not None
            and not isinstance(self.message, str)
        ):
            raise TypeError(
                "SystemExecutionStatus.message must be "
                "a string or None"
            )

        if (
            self.observation is not None
            and not isinstance(
                self.observation,
                ExecutionObservation,
            )
        ):
            raise TypeError(
                "SystemExecutionStatus.observation must be "
                "an ExecutionObservation or None"
            )

        if not isinstance(
            self.details,
            Mapping,
        ):
            raise TypeError(
                "SystemExecutionStatus.details must be a mapping"
            )

        object.__setattr__(
            self,
            "details",
            dict(self.details),
        )

    def child(
        self,
        name: str,
    ) -> ChildSystemExecutionStatus:
        for child in self.systems:
            if child.name == name:
                return child

        raise KeyError(name)

    @property
    def terminal(self) -> bool:
        return self.state in {
            BackendExecutionState.STOPPED,
            BackendExecutionState.COMPLETED,
            BackendExecutionState.FAILED,
        }

    @property
    def successful(self) -> bool:
        return self.state in {
            BackendExecutionState.STOPPED,
            BackendExecutionState.COMPLETED,
        }


def _aggregate_state(
    statuses: tuple[ScopeExecutionStatus, ...],
    systems: tuple[ChildSystemExecutionStatus, ...] = (),
) -> BackendExecutionState:
    states = (
        tuple(
            item.status.state
            for item in statuses
        )
        + tuple(
            item.status.state
            for item in systems
        )
    )

    if not states:
        return BackendExecutionState.COMPLETED

    if BackendExecutionState.FAILED in states:
        return BackendExecutionState.FAILED

    if all(
        state is BackendExecutionState.COMPLETED
        for state in states
    ):
        return BackendExecutionState.COMPLETED

    if all(
        state in {
            BackendExecutionState.STOPPED,
            BackendExecutionState.COMPLETED,
        }
        for state in states
    ):
        return BackendExecutionState.STOPPED

    if BackendExecutionState.STOPPING in states:
        return BackendExecutionState.STOPPING

    if BackendExecutionState.RUNNING in states:
        return BackendExecutionState.RUNNING

    return BackendExecutionState.PREPARED


def _aggregate_observation(
    statuses: tuple[ScopeExecutionStatus, ...],
    systems: tuple[ChildSystemExecutionStatus, ...],
    *,
    state: BackendExecutionState,
    failure_message: str | None = None,
) -> ExecutionObservation | None:
    """Aggregate readiness and health without hiding missing coverage."""

    entries: tuple[
        tuple[str, ExecutionObservation | None],
        ...,
    ] = (
        tuple(
            (
                f"scopes.{item.scope.id}",
                item.status.observation,
            )
            for item in statuses
        )
        + tuple(
            (
                f"systems.{item.name}",
                item.status.observation,
            )
            for item in systems
        )
    )

    observed = tuple(
        observation
        for _, observation in entries
        if observation is not None
    )
    if not observed:
        return None

    if state in {
        BackendExecutionState.STOPPING,
        BackendExecutionState.STOPPED,
        BackendExecutionState.COMPLETED,
        BackendExecutionState.FAILED,
    }:
        ready: bool | None = False
    elif state is not BackendExecutionState.RUNNING:
        ready = None
    elif any(
        observation is not None
        and observation.ready is False
        for _, observation in entries
    ):
        ready = False
    elif any(
        observation is None
        or observation.ready is None
        for _, observation in entries
    ):
        ready = None
    else:
        ready = True

    if state is BackendExecutionState.FAILED:
        health = ExecutionHealthState.UNHEALTHY
    elif any(
        observation.health
        is ExecutionHealthState.UNHEALTHY
        for observation in observed
    ):
        health = ExecutionHealthState.UNHEALTHY
    elif any(
        observation.health
        is ExecutionHealthState.DEGRADED
        for observation in observed
    ):
        health = ExecutionHealthState.DEGRADED
    elif any(
        observation is None
        or observation.health
        is ExecutionHealthState.UNKNOWN
        for _, observation in entries
    ):
        health = ExecutionHealthState.UNKNOWN
    else:
        health = ExecutionHealthState.HEALTHY

    message: str | None = None
    if (
        state is BackendExecutionState.FAILED
        and failure_message
    ):
        message = failure_message

    if (
        message is None
        and health is ExecutionHealthState.UNHEALTHY
    ):
        for entry_path, observation in entries:
            if (
                observation is not None
                and observation.health
                is ExecutionHealthState.UNHEALTHY
            ):
                reason = (
                    observation.message
                    or "unhealthy"
                )
                message = f"{entry_path}: {reason}"
                break

    if (
        message is None
        and health is ExecutionHealthState.DEGRADED
    ):
        for entry_path, observation in entries:
            if (
                observation is not None
                and observation.health
                is ExecutionHealthState.DEGRADED
            ):
                reason = (
                    observation.message
                    or "degraded"
                )
                message = f"{entry_path}: {reason}"
                break

    if message is None and ready is False:
        for entry_path, observation in entries:
            if (
                observation is not None
                and observation.ready is False
            ):
                reason = (
                    observation.message
                    or "not ready"
                )
                message = f"{entry_path}: {reason}"
                break

    if (
        message is None
        and (
            health is ExecutionHealthState.UNKNOWN
            or ready is None
        )
    ):
        for entry_path, observation in entries:
            if observation is None:
                message = (
                    "observation unavailable: "
                    f"{entry_path}"
                )
                break
            if (
                observation.health
                is ExecutionHealthState.UNKNOWN
                or observation.ready is None
            ):
                reason = (
                    observation.message
                    or "observation is unknown"
                )
                message = f"{entry_path}: {reason}"
                break

    return ExecutionObservation(
        ready=ready,
        health=health,
        message=message,
    )


def _failure_context(
    statuses: tuple[ScopeExecutionStatus, ...],
    systems: tuple[ChildSystemExecutionStatus, ...],
) -> tuple[str | None, dict[str, Any]]:
    for item in statuses:
        if (
            item.status.state
            is BackendExecutionState.FAILED
        ):
            details = dict(
                item.status.details
            )

            details.update(
                {
                    "failure_source": "scope",
                    "scope": item.scope.id,
                    "backend": item.status.backend,
                    "execution_id": (
                        item.status.execution_id
                    ),
                }
            )

            return (
                item.status.message,
                details,
            )

    for item in systems:
        if (
            item.status.state
            is BackendExecutionState.FAILED
        ):
            details = dict(
                item.status.details
            )

            details.update(
                {
                    "failure_source": "system",
                    "system": item.name,
                    "revision": item.revision,
                    "execution_id": (
                        item.status.execution_id
                    ),
                }
            )

            return (
                item.status.message,
                details,
            )

    return None, {}


def _failed_status(
    running: RunningScopeExecution,
    exc: BaseException,
) -> BackendExecutionStatus:
    return BackendExecutionStatus(
        backend=running.scope.backend,
        execution_id=running.handle.execution_id,
        state=BackendExecutionState.FAILED,
        message=str(exc),
        details={"exception_type": type(exc).__name__},
    )


def _failed_system_status(
    handle: SystemExecutionHandle,
    exc: BaseException,
) -> SystemExecutionStatus:
    return SystemExecutionStatus(
        execution_id=handle.execution_id,
        state=BackendExecutionState.FAILED,
        message=str(exc),
        details={
            "exception_type": type(exc).__name__,
        },
    )


def _observation_gap(
    status: SystemExecutionStatus,
    *,
    path: str,
) -> str | None:
    """Return the first execution path without observation support."""

    if not status.scopes and not status.systems:
        return path

    for scope in status.scopes:
        if scope.status.observation is None:
            return f"{path}.scopes.{scope.scope.id}"

    for child in status.systems:
        missing = _observation_gap(
            child.status,
            path=f"{path}.systems.{child.name}",
        )
        if missing is not None:
            return missing

    return None


class SystemOrchestrator:
    """Coordinate multiple target/backend scopes as one System lifecycle.

    Bindings are keyed by ``(target, backend)`` instead of backend id alone.
    This allows two remote targets to use separate instances of the same backend
    implementation and allows backend overrides inside one target.
    """

    def __init__(
        self,
        bindings: Mapping[
            ExecutionScope | tuple[str, str],
            ExecutionBackend,
        ],
        *,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], None] = time.sleep,
        dependency_poll_interval_seconds: float = 0.1,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(wait):
            raise TypeError("wait must be callable")
        if (
            not math.isfinite(dependency_poll_interval_seconds)
            or dependency_poll_interval_seconds <= 0
        ):
            raise ValueError(
                "dependency_poll_interval_seconds must be finite and positive"
            )

        normalized: dict[ExecutionScope, ExecutionBackend] = {}
        for raw_scope, backend in bindings.items():
            if isinstance(raw_scope, ExecutionScope):
                scope = raw_scope
            else:
                if len(raw_scope) != 2:
                    raise ValueError(
                        "orchestrator binding keys must be (target, backend) pairs"
                    )
                scope = ExecutionScope(raw_scope[0], raw_scope[1])
            if scope in normalized:
                raise ValueError(f"duplicate orchestrator binding for {scope.id}")
            normalized[scope] = backend
        self._bindings = normalized
        self._clock = clock
        self._wait = wait
        self._dependency_poll_interval_seconds = (
            dependency_poll_interval_seconds
        )

    @property
    def bindings(self) -> Mapping[ExecutionScope, ExecutionBackend]:
        return dict(self._bindings)

    def scopes(self, plan: SystemExecutionPlan) -> tuple[ExecutionScope, ...]:
        return plan_execution_scopes(plan)

    def validate_plan(
        self,
        plan: SystemExecutionPlan,
        *,
        execution_context: SystemExecutionContext | None = None,
        inherited_resources: tuple[
            PlannedChildSystemResourceBinding,
            ...,
        ] = (),
        _system_link_routes: tuple[_RoutedSystemLink, ...] = (),
    ) -> OrchestrationValidationReport:
        scopes = self.scopes(plan)
        diagnostics: list[OrchestrationDiagnostic] = []
        system_link_routes = (
            *_system_link_routes,
            *_plan_system_link_routes(plan),
        )

        try:
            validate_system_execution_context_binding(
                plan.execution_context_sha256,
                execution_context,
            )
        except SystemExecutionContextBindingError as exc:
            diagnostics.append(
                OrchestrationDiagnostic(
                    level="error",
                    code="ORCH103",
                    path="execution_context",
                    message=str(exc),
                )
            )

            return OrchestrationValidationReport(
                scopes=scopes,
                diagnostics=tuple(diagnostics),
            )

        # Direct execution scopes of this System only.
        for scope in scopes:
            backend = self._bindings.get(scope)

            if backend is None:
                diagnostics.append(
                    OrchestrationDiagnostic(
                        level="error",
                        code="ORCH101",
                        scope=scope,
                        path="bindings",
                        message=(
                            "no execution backend is bound to this "
                            "target/backend scope"
                        ),
                    )
                )
                continue

            if backend.backend_id != scope.backend:
                diagnostics.append(
                    OrchestrationDiagnostic(
                        level="error",
                        code="ORCH102",
                        scope=scope,
                        path="bindings.backend_id",
                        message=(
                            f"bound backend advertises "
                            f"{backend.backend_id!r}; "
                            f"plan requires {scope.backend!r}"
                        ),
                    )
                )
                continue

            context = backend_context_for_scope(
                plan,
                scope,
                execution_context=execution_context,
                inherited_resources=inherited_resources,
                system_inbound_links=tuple(
                    route.binding
                    for route in system_link_routes
                    if (
                        not route.remaining_system_path
                        and route.target == scope.target
                        and route.backend == scope.backend
                        and route.binding.direction == "inbound"
                    )
                ),
                system_outbound_links=tuple(
                    route.binding
                    for route in system_link_routes
                    if (
                        not route.remaining_system_path
                        and route.target == scope.target
                        and route.backend == scope.backend
                        and route.binding.direction == "outbound"
                    )
                ),
            )

            report = backend.validate(
                context
            )

            diagnostics.extend(
                OrchestrationDiagnostic(
                    level=item.level,
                    code=item.code,
                    scope=scope,
                    path=item.path,
                    message=item.message,
                    source="backend",
                )
                for item in report.diagnostics
            )

        # Child Systems retain their execution boundary.
        # They are validated recursively instead of being flattened
        # into the parent scope set.
        for child in plan.systems:
            child_context = child_system_execution_context(
                execution_context,
                child.name,
            )
            child_report = self.validate_plan(
                child.plan,
                execution_context=child_context,
                inherited_resources=child.resource_bindings,
                _system_link_routes=tuple(
                    _RoutedSystemLink(
                        binding=route.binding,
                        remaining_system_path=(
                            route.remaining_system_path[1:]
                        ),
                        target=route.target,
                        backend=route.backend,
                    )
                    for route in system_link_routes
                    if (
                        route.remaining_system_path
                        and route.remaining_system_path[0] == child.name
                    )
                ),
            )

            prefix = f"systems.{child.name}"

            diagnostics.extend(
                OrchestrationDiagnostic(
                    level=item.level,
                    code=item.code,
                    scope=item.scope,
                    path=(
                        prefix
                        if not item.path
                        else f"{prefix}.{item.path}"
                    ),
                    message=item.message,
                    source=item.source,
                )
                for item in child_report.diagnostics
            )

        return OrchestrationValidationReport(
            scopes=scopes,
            diagnostics=tuple(diagnostics),
        )

    def prepare_plan(
        self,
        plan: SystemExecutionPlan,
        *,
        execution_context: SystemExecutionContext | None = None,
        inherited_resources: tuple[
            PlannedChildSystemResourceBinding,
            ...,
        ] = (),
        _system_link_routes: tuple[_RoutedSystemLink, ...] = (),
    ) -> PreparedSystemExecution:
        system_link_routes = (
            *_system_link_routes,
            *_plan_system_link_routes(plan),
        )
        report = self.validate_plan(
            plan,
            execution_context=execution_context,
            inherited_resources=inherited_resources,
            _system_link_routes=_system_link_routes,
        )
        report.raise_for_errors()

        prepared_scopes: list[
            PreparedScopeExecution
        ] = []

        for scope in report.scopes:
            backend = self._bindings[scope]

            context = backend_context_for_scope(
                plan,
                scope,
                execution_context=execution_context,
                inherited_resources=inherited_resources,
                system_inbound_links=tuple(
                    route.binding
                    for route in system_link_routes
                    if (
                        not route.remaining_system_path
                        and route.target == scope.target
                        and route.backend == scope.backend
                        and route.binding.direction == "inbound"
                    )
                ),
                system_outbound_links=tuple(
                    route.binding
                    for route in system_link_routes
                    if (
                        not route.remaining_system_path
                        and route.target == scope.target
                        and route.backend == scope.backend
                        and route.binding.direction == "outbound"
                    )
                ),
            )

            try:
                prepared = backend.prepare(
                    context
                )
            except Exception as exc:
                raise OrchestrationError(
                    "ORCH201",
                    (
                        "prepare failed for scope "
                        f"{scope.id}: {exc}"
                    ),
                    path=scope.id,
                ) from exc

            prepared_scopes.append(
                PreparedScopeExecution(
                    scope=scope,
                    backend=backend,
                    prepared=prepared,
                )
            )

        prepared_systems: list[
            PreparedChildSystemExecution
        ] = []

        for child in plan.systems:
            child_context = child_system_execution_context(
                execution_context,
                child.name,
            )
            try:
                child_execution = self.prepare_plan(
                    child.plan,
                    execution_context=child_context,
                    inherited_resources=child.resource_bindings,
                    _system_link_routes=tuple(
                        _RoutedSystemLink(
                            binding=route.binding,
                            remaining_system_path=(
                                route.remaining_system_path[1:]
                            ),
                            target=route.target,
                            backend=route.backend,
                        )
                        for route in system_link_routes
                        if (
                            route.remaining_system_path
                            and route.remaining_system_path[0] == child.name
                        )
                    ),
                )
            except Exception as exc:
                raise OrchestrationError(
                    "ORCH203",
                    (
                        "prepare failed for child System "
                        f"{child.name!r}: {exc}"
                    ),
                    path=f"systems.{child.name}",
                ) from exc

            prepared_systems.append(
                PreparedChildSystemExecution(
                    instance=child,
                    execution=child_execution,
                )
            )

        return PreparedSystemExecution(
            plan=plan,
            execution_context=execution_context,
            inherited_resources=inherited_resources,
            system_links=tuple(
                route.binding
                for route in system_link_routes
            ),
            scopes=tuple(
                prepared_scopes
            ),
            systems=tuple(
                prepared_systems
            ),
        )

    def _dependency_condition_satisfied(
        self,
        dependency: PlannedSystemDependency,
        status: SystemExecutionStatus,
    ) -> bool:
        path = f"dependencies.{dependency.ordinal}"
        context = (
            f"prerequisite {dependency.requires!r} for child System "
            f"{dependency.system!r}"
        )

        if status.state is BackendExecutionState.FAILED:
            reason = status.message or "execution failed"
            raise OrchestrationError(
                "ORCH302",
                f"{context} failed before satisfying "
                f"{dependency.condition.value!r}: {reason}",
                path=path,
            )

        if dependency.condition is SystemDependencyCondition.STARTED:
            return True

        missing = _observation_gap(
            status,
            path=f"systems.{dependency.requires}",
        )
        if missing is not None:
            raise OrchestrationError(
                "ORCH304",
                f"{context} cannot satisfy {dependency.condition.value!r}: "
                f"observation is unsupported at {missing}",
                path=path,
            )

        observation = status.observation
        if observation is None:
            raise OrchestrationError(
                "ORCH304",
                f"{context} cannot satisfy {dependency.condition.value!r}: "
                "observation is unsupported",
                path=path,
            )

        if observation.health is ExecutionHealthState.UNHEALTHY:
            reason = observation.message or "execution is unhealthy"
            raise OrchestrationError(
                "ORCH303",
                f"{context} became unhealthy before satisfying "
                f"{dependency.condition.value!r}: {reason}",
                path=path,
            )

        if dependency.condition is SystemDependencyCondition.READY:
            satisfied = observation.ready is True
        else:
            satisfied = (
                observation.health
                is ExecutionHealthState.HEALTHY
            )

        if satisfied:
            return True

        if status.terminal:
            raise OrchestrationError(
                "ORCH302",
                f"{context} reached terminal state {status.state.value!r} "
                f"before satisfying {dependency.condition.value!r}",
                path=path,
            )

        return False

    def start(
        self,
        prepared: PreparedSystemExecution,
        *,
        rollback_timeout_seconds: float | None = None,
        startup_event_sink: Callable[[SystemStartupEvent], None] | None = None,
    ) -> SystemExecutionHandle:
        if (
            rollback_timeout_seconds is not None
            and (
                not math.isfinite(
                    rollback_timeout_seconds
                )
                or rollback_timeout_seconds < 0
            )
        ):
            raise ValueError(
                "rollback_timeout_seconds must be finite and non-negative"
            )
        if startup_event_sink is not None and not callable(startup_event_sink):
            raise TypeError("startup_event_sink must be callable or None")

        execution_id = f"system-{uuid4().hex[:12]}"

        startup = prepared.plan.system_startup
        prepared_by_name = {
            child.name: child
            for child in prepared.systems
        }

        if startup is not None:
            order = startup.order
            child_names = set(prepared_by_name)
            if (
                len(order) != len(child_names)
                or len(set(order)) != len(order)
                or set(order) != child_names
            ):
                raise OrchestrationError(
                    "ORCH305",
                    "compiled System startup order does not match prepared children",
                    path="system_startup.order",
                )

            for dependency in startup.dependencies:
                if (
                    dependency.system not in child_names
                    or dependency.requires not in child_names
                    or dependency.system == dependency.requires
                ):
                    raise OrchestrationError(
                        "ORCH305",
                        "compiled System dependency references invalid children",
                        path=f"system_startup.dependencies.{dependency.ordinal}",
                    )

        running_scopes: list[
            RunningScopeExecution
        ] = []

        running_systems: list[
            RunningChildSystemExecution
        ] = []

        def emit_startup_event(
            event: SystemStartupEvent,
        ) -> None:
            if startup_event_sink is not None:
                startup_event_sink(event)

        def rollback() -> list[str]:
            errors: list[str] = []

            # Children started after direct scopes,
            # therefore children stop first.
            for child in reversed(
                running_systems
            ):
                try:
                    self.stop(
                        child.handle,
                        timeout_seconds=(
                            rollback_timeout_seconds
                        ),
                    )
                except Exception as exc:
                    errors.append(
                        f"systems.{child.name}: {exc}"
                    )

            for started in reversed(
                running_scopes
            ):
                try:
                    started.backend.stop(
                        started.handle,
                        timeout_seconds=(
                            rollback_timeout_seconds
                        ),
                    )
                except Exception as exc:
                    errors.append(
                        f"{started.scope.id}: {exc}"
                    )

            return errors

        def start_child(
            child: PreparedChildSystemExecution,
        ) -> None:
            try:
                child_handle = self.start(
                    child.execution,
                    rollback_timeout_seconds=(
                        rollback_timeout_seconds
                    ),
                    startup_event_sink=startup_event_sink,
                )
            except Exception as exc:
                raise OrchestrationError(
                    "ORCH204",
                    (
                        "start failed for child System "
                        f"{child.name!r}: {exc}"
                    ),
                    path=f"systems.{child.name}",
                ) from exc

            running_systems.append(
                RunningChildSystemExecution(
                    instance=child.instance,
                    handle=child_handle,
                )
            )
            emit_startup_event(
                SystemStartupEvent(
                    event=(
                        SystemStartupEventKind.CHILD_STARTED
                    ),
                    execution_id=execution_id,
                    system=prepared.plan.system,
                    child=child.name,
                    child_execution_id=(
                        child_handle.execution_id
                    ),
                )
            )

        # Start direct scopes of this System.
        for item in prepared.scopes:
            try:
                handle = item.backend.start(
                    item.prepared
                )
            except Exception as exc:
                rollback_errors = rollback()

                suffix = (
                    "; rollback errors: "
                    + "; ".join(
                        rollback_errors
                    )
                    if rollback_errors
                    else ""
                )

                raise OrchestrationError(
                    "ORCH202",
                    (
                        "start failed for scope "
                        f"{item.scope.id}: "
                        f"{exc}{suffix}"
                    ),
                    path=item.scope.id,
                ) from exc

            running_scopes.append(
                RunningScopeExecution(
                    scope=item.scope,
                    backend=item.backend,
                    handle=handle,
                )
            )

        try:
            if startup is None:
                # Systems without dependency declarations retain the exact
                # pre-2.20 declaration-order lifecycle.
                for child in prepared.systems:
                    start_child(child)
            else:
                dependencies_by_system: dict[
                    str,
                    tuple[PlannedSystemDependency, ...],
                ] = {
                    name: tuple(
                        dependency
                        for dependency in startup.dependencies
                        if dependency.system == name
                    )
                    for name in startup.order
                }
                pending = list(startup.order)
                running_by_name: dict[
                    str,
                    RunningChildSystemExecution,
                ] = {}
                started_at: dict[str, float] = {}
                waiting_dependencies: set[int] = set()
                satisfied_dependencies: set[int] = set()

                def dependency_elapsed(
                    dependency: PlannedSystemDependency,
                ) -> float:
                    return max(
                        0.0,
                        self._clock()
                        - started_at[dependency.requires],
                    )

                def emit_dependency_event(
                    event: SystemStartupEventKind,
                    dependency: PlannedSystemDependency,
                    *,
                    message: str | None = None,
                ) -> None:
                    emit_startup_event(
                        SystemStartupEvent(
                            event=event,
                            execution_id=execution_id,
                            system=prepared.plan.system,
                            child=dependency.system,
                            dependency_ordinal=(
                                dependency.ordinal
                            ),
                            requires=dependency.requires,
                            condition=dependency.condition,
                            timeout_seconds=(
                                dependency.timeout_seconds
                            ),
                            elapsed_seconds=(
                                dependency_elapsed(
                                    dependency
                                )
                            ),
                            message=message,
                        )
                    )

                def dependency_timeout_error(
                    dependency: PlannedSystemDependency,
                ) -> OrchestrationError:
                    error = OrchestrationError(
                        "ORCH301",
                        (
                            f"timed out after "
                            f"{dependency.timeout_seconds:g}s waiting for "
                            f"prerequisite {dependency.requires!r} to "
                            f"satisfy {dependency.condition.value!r} for "
                            f"child System {dependency.system!r}"
                        ),
                        path=f"dependencies.{dependency.ordinal}",
                    )
                    emit_dependency_event(
                        SystemStartupEventKind.DEPENDENCY_FAILED,
                        dependency,
                        message=error.message,
                    )
                    return error

                while pending:
                    made_progress = False
                    status_cache: dict[
                        str,
                        SystemExecutionStatus,
                    ] = {}
                    unresolved_deadlines: list[float] = []

                    for name in tuple(pending):
                        dependencies = dependencies_by_system[name]
                        eligible = True

                        for dependency in dependencies:
                            if (
                                dependency.ordinal
                                in satisfied_dependencies
                            ):
                                continue

                            prerequisite = running_by_name.get(
                                dependency.requires
                            )
                            if prerequisite is None:
                                eligible = False
                                continue

                            deadline = (
                                started_at[dependency.requires]
                                + dependency.timeout_seconds
                            )

                            if (
                                dependency.condition
                                is SystemDependencyCondition.STARTED
                            ):
                                if self._clock() > deadline:
                                    raise dependency_timeout_error(
                                        dependency
                                    )
                                satisfied_dependencies.add(
                                    dependency.ordinal
                                )
                                emit_dependency_event(
                                    SystemStartupEventKind
                                    .DEPENDENCY_SATISFIED,
                                    dependency,
                                )
                                continue

                            status = status_cache.get(
                                dependency.requires
                            )
                            if status is None:
                                status = self.inspect(
                                    prerequisite.handle
                                )
                                status_cache[
                                    dependency.requires
                                ] = status

                            observed_at = self._clock()
                            if observed_at > deadline:
                                raise dependency_timeout_error(
                                    dependency
                                )

                            try:
                                satisfied = (
                                    self._dependency_condition_satisfied(
                                        dependency,
                                        status,
                                    )
                                )
                            except OrchestrationError as exc:
                                emit_dependency_event(
                                    SystemStartupEventKind
                                    .DEPENDENCY_FAILED,
                                    dependency,
                                    message=exc.message,
                                )
                                raise

                            if satisfied:
                                satisfied_dependencies.add(
                                    dependency.ordinal
                                )
                                emit_dependency_event(
                                    SystemStartupEventKind
                                    .DEPENDENCY_SATISFIED,
                                    dependency,
                                )
                                continue

                            eligible = False
                            if observed_at >= deadline:
                                raise dependency_timeout_error(
                                    dependency
                                )

                            if (
                                dependency.ordinal
                                not in waiting_dependencies
                            ):
                                waiting_dependencies.add(
                                    dependency.ordinal
                                )
                                emit_dependency_event(
                                    SystemStartupEventKind
                                    .DEPENDENCY_WAITING,
                                    dependency,
                                )
                            unresolved_deadlines.append(
                                deadline
                            )

                        if not eligible:
                            continue

                        child = prepared_by_name[name]
                        child_started_at = self._clock()
                        start_child(child)
                        running = running_systems[-1]
                        running_by_name[name] = running
                        started_at[name] = child_started_at
                        pending.remove(name)
                        made_progress = True

                    if not pending or made_progress:
                        continue

                    if not unresolved_deadlines:
                        raise OrchestrationError(
                            "ORCH305",
                            "compiled System startup topology cannot make progress",
                            path="system_startup",
                        )

                    nearest_deadline = min(
                        unresolved_deadlines
                    )
                    delay = min(
                        self._dependency_poll_interval_seconds,
                        nearest_deadline - self._clock(),
                    )
                    if delay > 0:
                        self._wait(delay)

        except Exception as exc:
            rollback_errors = rollback()
            suffix = (
                "; rollback errors: "
                + "; ".join(rollback_errors)
                if rollback_errors
                else ""
            )

            if isinstance(exc, OrchestrationError):
                if not suffix:
                    raise
                raise OrchestrationError(
                    exc.code,
                    f"{exc.message}{suffix}",
                    path=exc.path,
                ) from exc

            raise OrchestrationError(
                "ORCH305",
                f"System startup scheduler failed: {exc}{suffix}",
                path="system_startup",
            ) from exc

        return SystemExecutionHandle(
            execution_id=execution_id,
            prepared=prepared,
            scopes=tuple(
                running_scopes
            ),
            systems=tuple(
                running_systems
            ),
        )

    def inspect(
        self,
        handle: SystemExecutionHandle,
    ) -> SystemExecutionStatus:
        statuses: list[
            ScopeExecutionStatus
        ] = []

        for running in handle.scopes:
            try:
                status = running.backend.inspect(
                    running.handle
                )
            except Exception as exc:
                status = _failed_status(
                    running,
                    exc,
                )

            statuses.append(
                ScopeExecutionStatus(
                    scope=running.scope,
                    status=status,
                )
            )

        system_statuses: list[
            ChildSystemExecutionStatus
        ] = []

        for child in handle.systems:
            try:
                child_status = self.inspect(
                    child.handle
                )
            except Exception as exc:
                child_status = _failed_system_status(
                    child.handle,
                    exc,
                )

            system_statuses.append(
                ChildSystemExecutionStatus(
                    instance=child.instance,
                    status=child_status,
                )
            )

        frozen_scopes = tuple(
            statuses
        )
        frozen_systems = tuple(
            system_statuses
        )

        state = _aggregate_state(
            frozen_scopes,
            frozen_systems,
        )

        message: str | None = None
        details: dict[str, Any] = {}

        if (
            state
            is BackendExecutionState.FAILED
        ):
            message, details = _failure_context(
                frozen_scopes,
                frozen_systems,
            )

        observation = _aggregate_observation(
            frozen_scopes,
            frozen_systems,
            state=state,
            failure_message=message,
        )

        return SystemExecutionStatus(
            execution_id=handle.execution_id,
            state=state,
            scopes=frozen_scopes,
            systems=frozen_systems,
            message=message,
            details=details,
            observation=observation,
        )

    def stop(
        self,
        handle: SystemExecutionHandle,
        *,
        timeout_seconds: float | None = None,
    ) -> SystemExecutionStatus:
        if (
            timeout_seconds is not None
            and timeout_seconds < 0
        ):
            raise ValueError(
                "timeout_seconds cannot be negative"
            )

        # Child Systems were started after direct scopes.
        # Stop them first, in reverse declaration order.
        stopped_systems_reverse: list[
            ChildSystemExecutionStatus
        ] = []

        for child in reversed(
            handle.systems
        ):
            try:
                child_status = self.stop(
                    child.handle,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                # Preserve cleanup of remaining siblings/scopes while
                # retaining the failed child execution reason.
                child_status = _failed_system_status(
                    child.handle,
                    exc,
                )

            stopped_systems_reverse.append(
                ChildSystemExecutionStatus(
                    instance=child.instance,
                    status=child_status,
                )
            )

        systems = tuple(
            reversed(
                stopped_systems_reverse
            )
        )

        by_scope: dict[
            ExecutionScope,
            BackendExecutionStatus,
        ] = {}

        for running in reversed(
            handle.scopes
        ):
            try:
                status = running.backend.stop(
                    running.handle,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                status = _failed_status(
                    running,
                    exc,
                )

            by_scope[
                running.scope
            ] = status

        statuses = tuple(
            ScopeExecutionStatus(
                scope=running.scope,
                status=by_scope[
                    running.scope
                ],
            )
            for running in handle.scopes
        )

        state = _aggregate_state(
            statuses,
            systems,
        )

        message: str | None = None
        details: dict[str, Any] = {}

        if (
            state
            is BackendExecutionState.FAILED
        ):
            message, details = _failure_context(
                statuses,
                systems,
            )

        observation = _aggregate_observation(
            statuses,
            systems,
            state=state,
            failure_message=message,
        )

        return SystemExecutionStatus(
            execution_id=handle.execution_id,
            state=state,
            scopes=statuses,
            systems=systems,
            message=message,
            details=details,
            observation=observation,
        )
