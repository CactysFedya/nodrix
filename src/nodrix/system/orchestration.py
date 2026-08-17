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
from typing import Mapping
from uuid import uuid4

from ..errors import NodrixError
from .backend import (
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    PreparedExecution,
)
from .execution_context import (
    SystemExecutionContext,
    SystemExecutionContextBindingError,
    validate_system_execution_context_binding,
)
from .planning import PlannedTarget, SystemExecutionPlan


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
class PreparedSystemExecution:
    plan: SystemExecutionPlan
    execution_context: SystemExecutionContext | None = field(
        default=None,
        repr=False,
    )
    scopes: tuple[PreparedScopeExecution, ...] = ()


@dataclass(frozen=True, slots=True)
class RunningScopeExecution:
    scope: ExecutionScope
    backend: ExecutionBackend = field(repr=False, compare=False)
    handle: BackendExecutionHandle


@dataclass(frozen=True, slots=True)
class SystemExecutionHandle:
    execution_id: str
    prepared: PreparedSystemExecution
    scopes: tuple[RunningScopeExecution, ...] = ()


@dataclass(frozen=True, slots=True)
class ScopeExecutionStatus:
    scope: ExecutionScope
    status: BackendExecutionStatus


@dataclass(frozen=True, slots=True)
class SystemExecutionStatus:
    execution_id: str
    state: BackendExecutionState
    scopes: tuple[ScopeExecutionStatus, ...] = ()

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
) -> BackendExecutionState:
    if not statuses:
        return BackendExecutionState.COMPLETED

    states = tuple(item.status.state for item in statuses)
    if BackendExecutionState.FAILED in states:
        return BackendExecutionState.FAILED
    if all(state is BackendExecutionState.COMPLETED for state in states):
        return BackendExecutionState.COMPLETED
    if all(
        state in {BackendExecutionState.STOPPED, BackendExecutionState.COMPLETED}
        for state in states
    ):
        return BackendExecutionState.STOPPED
    if BackendExecutionState.STOPPING in states:
        return BackendExecutionState.STOPPING
    if BackendExecutionState.RUNNING in states:
        return BackendExecutionState.RUNNING
    return BackendExecutionState.PREPARED


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
                            "no execution backend is bound to this target/backend "
                            "scope"
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
                            f"bound backend advertises {backend.backend_id!r}; "
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
            report = backend.validate(context)
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

        prepared_scopes: list[PreparedScopeExecution] = []
        for scope in report.scopes:
            backend = self._bindings[scope]
            context = backend_context_for_scope(
                plan,
                scope,
                execution_context=execution_context,
            )
            try:
                prepared = backend.prepare(context)
            except Exception as exc:
                raise OrchestrationError(
                    "ORCH201",
                    f"prepare failed for scope {scope.id}: {exc}",
                    path=scope.id,
                ) from exc
            prepared_scopes.append(
                PreparedScopeExecution(
                    scope=scope,
                    backend=backend,
                    prepared=prepared,
                )
            )

        return PreparedSystemExecution(
            plan=plan,
            execution_context=execution_context,
            scopes=tuple(prepared_scopes),
        )

    def start(
        self,
        prepared: PreparedSystemExecution,
        *,
        rollback_timeout_seconds: float | None = None,
    ) -> SystemExecutionHandle:
        if rollback_timeout_seconds is not None and rollback_timeout_seconds < 0:
            raise ValueError("rollback_timeout_seconds cannot be negative")

        running: list[RunningScopeExecution] = []
        for item in prepared.scopes:
            try:
                handle = item.backend.start(item.prepared)
            except Exception as exc:
                rollback_errors: list[str] = []
                for started in reversed(running):
                    try:
                        started.backend.stop(
                            started.handle,
                            timeout_seconds=rollback_timeout_seconds,
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(
                            f"{started.scope.id}: {rollback_exc}"
                        )
                suffix = (
                    "; rollback errors: " + "; ".join(rollback_errors)
                    if rollback_errors
                    else ""
                )
                raise OrchestrationError(
                    "ORCH202",
                    f"start failed for scope {item.scope.id}: {exc}{suffix}",
                    path=item.scope.id,
                ) from exc

            running.append(
                RunningScopeExecution(
                    scope=item.scope,
                    backend=item.backend,
                    handle=handle,
                )
            )

        return SystemExecutionHandle(
            execution_id=f"system-{uuid4().hex[:12]}",
            prepared=prepared,
            scopes=tuple(running),
        )

    def inspect(self, handle: SystemExecutionHandle) -> SystemExecutionStatus:
        statuses: list[ScopeExecutionStatus] = []
        for running in handle.scopes:
            try:
                status = running.backend.inspect(running.handle)
            except Exception as exc:
                status = _failed_status(running, exc)
            statuses.append(
                ScopeExecutionStatus(scope=running.scope, status=status)
            )

        frozen = tuple(statuses)
        return SystemExecutionStatus(
            execution_id=handle.execution_id,
            state=_aggregate_state(frozen),
            scopes=frozen,
        )

    def stop(
        self,
        handle: SystemExecutionHandle,
        *,
        timeout_seconds: float | None = None,
    ) -> SystemExecutionStatus:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")

        by_scope: dict[ExecutionScope, BackendExecutionStatus] = {}
        for running in reversed(handle.scopes):
            try:
                status = running.backend.stop(
                    running.handle,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                status = _failed_status(running, exc)
            by_scope[running.scope] = status

        statuses = tuple(
            ScopeExecutionStatus(
                scope=running.scope,
                status=by_scope[running.scope],
            )
            for running in handle.scopes
        )
        return SystemExecutionStatus(
            execution_id=handle.execution_id,
            state=_aggregate_state(statuses),
            scopes=statuses,
        )
