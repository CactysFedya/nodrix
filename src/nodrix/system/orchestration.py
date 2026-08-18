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
from typing import Any, Mapping
from uuid import uuid4

from ..errors import NodrixError
from .backend import (
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionObservation,
    ExecutionBackend,
    PreparedExecution,
)
from .execution_context import (
    SystemExecutionContext,
    SystemExecutionContextBindingError,
    validate_system_execution_context_binding,
)
from .planning import (
    PlannedSystemInstance,
    PlannedTarget,
    SystemExecutionPlan,
)


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
        link for link in plan.links if is_source(link) and is_target(link)
    )
    inbound_links = tuple(
        link for link in plan.links if is_target(link) and not is_source(link)
    )
    outbound_links = tuple(
        link for link in plan.links if is_source(link) and not is_target(link)
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
        targets=(target,),
        resources=resources,
        resource_order=resource_order,
        applications=applications,
        nodes=nodes,
        connections=connections,
        internal_links=internal_links,
        inbound_links=inbound_links,
        outbound_links=outbound_links,
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
    ) -> None:
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
    ) -> OrchestrationValidationReport:
        scopes = self.scopes(plan)
        diagnostics: list[OrchestrationDiagnostic] = []

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
            child_report = self.validate_plan(
                child.plan,
                execution_context=execution_context,
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
    ) -> PreparedSystemExecution:
        report = self.validate_plan(
            plan,
            execution_context=execution_context,
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
            try:
                child_execution = self.prepare_plan(
                    child.plan,
                    execution_context=execution_context,
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
            scopes=tuple(
                prepared_scopes
            ),
            systems=tuple(
                prepared_systems
            ),
        )

    def start(
        self,
        prepared: PreparedSystemExecution,
        *,
        rollback_timeout_seconds: float | None = None,
    ) -> SystemExecutionHandle:
        if (
            rollback_timeout_seconds is not None
            and rollback_timeout_seconds < 0
        ):
            raise ValueError(
                "rollback_timeout_seconds cannot be negative"
            )

        running_scopes: list[
            RunningScopeExecution
        ] = []

        running_systems: list[
            RunningChildSystemExecution
        ] = []

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

        # Then start nested child Systems in declaration order.
        for child in prepared.systems:
            try:
                child_handle = self.start(
                    child.execution,
                    rollback_timeout_seconds=(
                        rollback_timeout_seconds
                    ),
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
                    "ORCH204",
                    (
                        "start failed for child System "
                        f"{child.name!r}: "
                        f"{exc}{suffix}"
                    ),
                    path=f"systems.{child.name}",
                ) from exc

            running_systems.append(
                RunningChildSystemExecution(
                    instance=child.instance,
                    handle=child_handle,
                )
            )

        return SystemExecutionHandle(
            execution_id=(
                f"system-{uuid4().hex[:12]}"
            ),
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

        return SystemExecutionStatus(
            execution_id=handle.execution_id,
            state=state,
            scopes=frozen_scopes,
            systems=frozen_systems,
            message=message,
            details=details,
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

        return SystemExecutionStatus(
            execution_id=handle.execution_id,
            state=state,
            scopes=statuses,
            systems=systems,
            message=message,
            details=details,
        )
