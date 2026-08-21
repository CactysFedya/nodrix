"""Backend contract for Nodrix 2.6 system execution.

This module is intentionally runtime-agnostic.  A backend receives only a
resolved :class:`SystemExecutionPlan` scope.  Pipeline manifests, SDK
inspection, provider discovery, and scheduler/runtime implementation details
belong outside this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
from enum import Enum, StrEnum
from typing import Any, Iterable, Literal, Mapping

from ..metric_publisher import MetricSink
from ..errors import NodrixError
from .execution_context import (
    SystemExecutionContext,
    SystemExecutionContextBindingError,
    validate_system_execution_context_binding,
)
from .planning import (
    PlannedChildSystemResourceBinding,
    PlannedApplication,
    PlannedArtifact,
    PlannedConnection,
    PlannedLink,
    PlannedNode,
    PlannedResource,
    PlannedTarget,
    SystemExecutionPlan,
)


class BackendContractError(NodrixError):
    """A backend implementation violated the common execution contract."""

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
class BackendCapabilities:
    """Static capabilities advertised by one execution backend.

    Empty ``target_kinds`` or ``transport_uses`` means that the backend does
    not impose a generic restriction at this layer; backend-specific validation
    may still reject a context.
    """

    target_kinds: frozenset[str] = field(default_factory=frozenset)
    transport_uses: frozenset[str] = field(default_factory=frozenset)
    features: frozenset[str] = field(default_factory=frozenset)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_kinds", frozenset(self.target_kinds))
        object.__setattr__(self, "transport_uses", frozenset(self.transport_uses))
        object.__setattr__(self, "features", frozenset(self.features))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def supports_target_kind(self, kind: str) -> bool:
        return not self.target_kinds or kind in self.target_kinds

    def supports_transport(self, uses: str | None) -> bool:
        if uses is None:
            return True
        return not self.transport_uses or uses in self.transport_uses

    def supports_feature(self, feature: str) -> bool:
        return feature in self.features


@dataclass(frozen=True, slots=True)
class BackendSystemLink:
    """One resolved side of a link crossing a child System boundary."""

    link: PlannedLink
    direction: Literal["inbound", "outbound"]
    local_endpoint: str
    remote_endpoint: str
    owner_system_path: tuple[str, ...] = ()
    local_system_path: tuple[str, ...] = ()
    remote_system_path: tuple[str, ...] = ()

    @property
    def ordinal(self) -> int:
        return self.link.ordinal

    @property
    def transport_required(self) -> bool:
        return self.link.transport_required

    @property
    def transport_uses(self) -> str | None:
        return self.link.transport_uses


@dataclass(frozen=True, slots=True)
class BackendContext:
    """The part of one SystemExecutionPlan owned by a backend.

    Nodes are flattened across Graphs while preserving Graph/node declaration
    order.  Connections are already guaranteed by the Planner to remain within
    one backend.  SystemLinks are classified as internal, inbound, or outbound
    from this backend's point of view.
    """

    plan: SystemExecutionPlan
    backend: str
    execution_context: SystemExecutionContext | None = field(
        default=None,
        repr=False,
    )
    metric_sink: MetricSink | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    targets: tuple[PlannedTarget, ...] = ()
    system_parameters: Mapping[str, Any] = field(
        default_factory=dict
    )
    inherited_resources: tuple[
        PlannedChildSystemResourceBinding,
        ...,
    ] = ()
    resources: tuple[PlannedResource, ...] = ()
    resource_order: tuple[str, ...] = ()
    applications: tuple[PlannedApplication, ...] = ()
    nodes: tuple[PlannedNode, ...] = ()
    connections: tuple[PlannedConnection, ...] = ()
    internal_links: tuple[PlannedLink, ...] = ()
    inbound_links: tuple[PlannedLink, ...] = ()
    outbound_links: tuple[PlannedLink, ...] = ()
    system_inbound_links: tuple[BackendSystemLink, ...] = ()
    system_outbound_links: tuple[BackendSystemLink, ...] = ()
    artifacts: tuple[PlannedArtifact, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "system_parameters",
            dict(self.system_parameters),
        )
        try:
            validate_system_execution_context_binding(
                self.plan.execution_context_sha256,
                self.execution_context,
            )
        except SystemExecutionContextBindingError as exc:
            raise BackendContractError(
                "BACKEND208",
                str(exc),
                path="plan.execution_context_sha256",
            ) from exc

    @classmethod
    def from_plan(
        cls,
        plan: SystemExecutionPlan,
        backend: str,
        *,
        execution_context: SystemExecutionContext | None = None,
        inherited_resources: tuple[
            PlannedChildSystemResourceBinding,
            ...,
        ] = (),
        system_inbound_links: tuple[BackendSystemLink, ...] = (),
        system_outbound_links: tuple[BackendSystemLink, ...] = (),
    ) -> "BackendContext":
        backend = backend.strip()
        if not backend:
            raise BackendContractError(
                "BACKEND001",
                "backend identifier must be a non-empty string",
            )

        resources = tuple(
            item for item in plan.resources
            if item.backend == backend
        )
        applications = tuple(
            item for item in plan.applications
            if item.backend == backend
        )
        nodes = tuple(
            node
            for graph in plan.graphs
            for node in graph.nodes
            if node.backend == backend
        )
        connections = tuple(
            connection
            for graph in plan.graphs
            for connection in graph.connections
            if connection.backend == backend
        )
        internal_links = tuple(
            link
            for link in plan.links
            if link.source_backend == backend and link.target_backend == backend
        )
        inbound_links = tuple(
            link
            for link in plan.links
            if link.target_backend == backend and link.source_backend != backend
        )
        outbound_links = tuple(
            link
            for link in plan.links
            if link.source_backend == backend and link.target_backend != backend
        )
        artifacts = tuple(
            item for item in plan.artifacts
            if item.backend == backend
        )

        referenced_targets = {
            item.target for item in resources
        }
        referenced_targets.update(item.target for item in applications)
        referenced_targets.update(item.target for item in nodes)
        referenced_targets.update(
            item.target for item in artifacts
            if item.target is not None
        )
        referenced_targets.update(
            link.source_target
            for link in (*internal_links, *outbound_links)
        )
        referenced_targets.update(
            link.target_target
            for link in (*internal_links, *inbound_links)
        )
        referenced_targets.update(
            target.name
            for target in plan.targets
            if target.backend == backend
        )

        targets = tuple(
            target for target in plan.targets
            if target.name in referenced_targets
        )
        resource_names = {item.name for item in resources}
        resource_order = tuple(
            name for name in plan.resource_order
            if name in resource_names
        )

        return cls(
            plan=plan,
            backend=backend,
            execution_context=execution_context,
            system_parameters={
                parameter.name: parameter.value
                for parameter in plan.parameters
                if (
                    parameter.configured
                    or parameter.has_default
                )
            },
            inherited_resources=tuple(
                inherited_resources
            ),
            targets=targets,
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

    @property
    def graph_names(self) -> tuple[str, ...]:
        owned = {node.graph for node in self.nodes}
        owned.update(connection.graph for connection in self.connections)
        return tuple(
            graph.name for graph in self.plan.graphs
            if graph.name in owned
        )

    @property
    def links(self) -> tuple[PlannedLink, ...]:
        owned = {
            link.ordinal: link
            for link in (
                *self.internal_links,
                *self.inbound_links,
                *self.outbound_links,
            )
        }
        return tuple(owned[key] for key in sorted(owned))

    @property
    def system_links(self) -> tuple[BackendSystemLink, ...]:
        owned: dict[
            tuple[int, str, str],
            BackendSystemLink,
        ] = {}
        for item in (
            *self.system_inbound_links,
            *self.system_outbound_links,
        ):
            key = (
                item.ordinal,
                item.local_endpoint,
                item.remote_endpoint,
            )
            owned.setdefault(key, item)
        return tuple(owned.values())

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.targets,
                self.system_parameters,
                self.inherited_resources,
                self.resources,
                self.applications,
                self.nodes,
                self.connections,
                self.links,
                self.system_links,
                self.artifacts,
            )
        )

    @property
    def summary(self) -> dict[str, int]:
        return {
            "targets": len(self.targets),
            "resources": len(self.resources),
            "applications": len(self.applications),
            "graphs": len(self.graph_names),
            "nodes": len(self.nodes),
            "connections": len(self.connections),
            "internal_links": len(self.internal_links),
            "inbound_links": len(self.inbound_links),
            "outbound_links": len(self.outbound_links),
            **(
                {
                    "system_inbound_links": len(
                        self.system_inbound_links
                    ),
                    "system_outbound_links": len(
                        self.system_outbound_links
                    ),
                }
                if self.system_links
                else {}
            ),
            "artifacts": len(self.artifacts),
            **(
                {
                    "system_parameters": len(
                        self.system_parameters
                    )
                }
                if self.system_parameters
                else {}
            ),
            **(
                {
                    "inherited_resources": len(
                        self.inherited_resources
                    )
                }
                if self.inherited_resources
                else {}
            ),
        }

    def nodes_for_graph(self, graph: str) -> tuple[PlannedNode, ...]:
        return tuple(node for node in self.nodes if node.graph == graph)

    def connections_for_graph(
        self,
        graph: str,
    ) -> tuple[PlannedConnection, ...]:
        return tuple(
            connection
            for connection in self.connections
            if connection.graph == graph
        )


@dataclass(frozen=True, slots=True)
class BackendDiagnostic:
    level: str
    code: str
    message: str
    path: str = ""

    def __post_init__(self) -> None:
        if self.level not in {"error", "warning"}:
            raise ValueError("BackendDiagnostic.level must be 'error' or 'warning'")


@dataclass(frozen=True, slots=True)
class BackendValidationReport:
    backend: str
    diagnostics: tuple[BackendDiagnostic, ...] = ()

    @property
    def errors(self) -> tuple[BackendDiagnostic, ...]:
        return tuple(
            item for item in self.diagnostics
            if item.level == "error"
        )

    @property
    def warnings(self) -> tuple[BackendDiagnostic, ...]:
        return tuple(
            item for item in self.diagnostics
            if item.level == "warning"
        )

    @property
    def valid(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise BackendValidationError(self)


class BackendValidationError(BackendContractError):
    def __init__(self, report: BackendValidationReport) -> None:
        self.report = report
        detail = "; ".join(
            f"{item.code} {item.path}: {item.message}"
            for item in report.errors
        )
        super().__init__(
            "BACKEND100",
            detail or f"backend {report.backend!r} validation failed",
        )


class BackendExecutionState(str, Enum):
    PREPARED = "prepared"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    """Opaque backend preparation result.

    ``payload`` is intentionally backend-owned.  Common orchestration code must
    not depend on its shape.
    """

    backend: str
    context: BackendContext
    payload: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.backend.strip():
            raise ValueError("PreparedExecution.backend must be non-empty")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class BackendExecutionHandle:
    """Opaque handle returned by a non-blocking backend start operation."""

    backend: str
    execution_id: str
    prepared: PreparedExecution
    payload: Any = None

    def __post_init__(self) -> None:
        if not self.backend.strip():
            raise ValueError("BackendExecutionHandle.backend must be non-empty")
        if not self.execution_id.strip():
            raise ValueError(
                "BackendExecutionHandle.execution_id must be non-empty"
            )


class ExecutionHealthState(StrEnum):
    """Backend-neutral health classification for one execution."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class ExecutionObservation:
    """Backend-neutral readiness and health observation.

    ``None`` readiness means that readiness is currently unknown. Absence of
    the observation itself means that the backend does not expose this
    capability.
    """

    ready: bool | None = None
    health: ExecutionHealthState = ExecutionHealthState.UNKNOWN
    message: str | None = None

    def __post_init__(self) -> None:
        if (
            self.ready is not None
            and not isinstance(
                self.ready,
                bool,
            )
        ):
            raise TypeError(
                "ExecutionObservation.ready must be a bool or None"
            )

        if not isinstance(
            self.health,
            ExecutionHealthState,
        ):
            raise TypeError(
                "ExecutionObservation.health must be an ExecutionHealthState"
            )

        if (
            self.message is not None
            and not isinstance(
                self.message,
                str,
            )
        ):
            raise TypeError(
                "ExecutionObservation.message must be a string or None"
            )


@dataclass(frozen=True, slots=True)
class ExecutionTiming:
    """Backend-neutral measured execution timing evidence.

    ``duration_seconds`` is supplied by the execution backend from its own
    execution measurement.  It is distinct from orchestration observation
    timestamps such as CanonicalSystemExecution.finished_at.
    """

    duration_seconds: float

    def __post_init__(self) -> None:
        if (
            isinstance(
                self.duration_seconds,
                bool,
            )
            or not isinstance(
                self.duration_seconds,
                (
                    int,
                    float,
                ),
            )
        ):
            raise TypeError(
                "ExecutionTiming.duration_seconds "
                "must be a real number"
            )

        value = float(
            self.duration_seconds
        )

        if (
            not math.isfinite(
                value
            )
            or value < 0.0
        ):
            raise ValueError(
                "ExecutionTiming.duration_seconds "
                "must be finite and non-negative"
            )

        object.__setattr__(
            self,
            "duration_seconds",
            value,
        )


@dataclass(frozen=True, slots=True)
class BackendExecutionStatus:
    backend: str
    execution_id: str
    state: BackendExecutionState
    message: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    observation: ExecutionObservation | None = None
    timing: ExecutionTiming | None = None

    def __post_init__(self) -> None:
        if (
            self.timing is not None
            and not isinstance(
                self.timing,
                ExecutionTiming,
            )
        ):
            raise TypeError(
                "BackendExecutionStatus.timing must be "
                "an ExecutionTiming or None"
            )

        if (
            self.observation is not None
            and not isinstance(
                self.observation,
                ExecutionObservation,
            )
        ):
            raise TypeError(
                "BackendExecutionStatus.observation must be "
                "an ExecutionObservation or None"
            )

        object.__setattr__(self, "details", dict(self.details))

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


class ExecutionBackend(ABC):
    """Synchronous control-plane contract implemented by execution backends.

    ``start`` must return a handle without blocking for the whole System run.
    Long-running work belongs behind the handle and is observed through
    ``inspect`` / ``stop``.
    """

    def __init__(
        self,
        backend_id: str,
        *,
        capabilities: BackendCapabilities | None = None,
    ) -> None:
        backend_id = backend_id.strip()
        if not backend_id:
            raise ValueError("backend_id must be a non-empty string")
        self._backend_id = backend_id
        self._capabilities = capabilities or BackendCapabilities()

    @property
    def backend_id(self) -> str:
        return self._backend_id

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    def context(
        self,
        plan: SystemExecutionPlan,
        *,
        execution_context: SystemExecutionContext | None = None,
        inherited_resources: tuple[
            PlannedChildSystemResourceBinding,
            ...,
        ] = (),
        system_inbound_links: tuple[BackendSystemLink, ...] = (),
        system_outbound_links: tuple[BackendSystemLink, ...] = (),
    ) -> BackendContext:
        return BackendContext.from_plan(
            plan,
            self.backend_id,
            execution_context=execution_context,
            inherited_resources=inherited_resources,
            system_inbound_links=system_inbound_links,
            system_outbound_links=system_outbound_links,
        )

    def validate_plan(
        self,
        plan: SystemExecutionPlan,
        *,
        execution_context: SystemExecutionContext | None = None,
        inherited_resources: tuple[
            PlannedChildSystemResourceBinding,
            ...,
        ] = (),
        system_inbound_links: tuple[BackendSystemLink, ...] = (),
        system_outbound_links: tuple[BackendSystemLink, ...] = (),
    ) -> BackendValidationReport:
        return self.validate(
            self.context(
                plan,
                execution_context=execution_context,
                inherited_resources=inherited_resources,
                system_inbound_links=system_inbound_links,
                system_outbound_links=system_outbound_links,
            )
        )

    def validate(
        self,
        context: BackendContext,
    ) -> BackendValidationReport:
        diagnostics: list[BackendDiagnostic] = []

        if context.backend != self.backend_id:
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="BACKEND101",
                    path="context.backend",
                    message=(
                        f"context belongs to backend {context.backend!r}, "
                        f"not {self.backend_id!r}"
                    ),
                )
            )

        for target in context.targets:
            if not self.capabilities.supports_target_kind(target.kind):
                diagnostics.append(
                    BackendDiagnostic(
                        level="error",
                        code="BACKEND102",
                        path=f"targets.{target.name}.kind",
                        message=(
                            f"backend {self.backend_id!r} does not support "
                            f"target kind {target.kind!r}"
                        ),
                    )
                )

        for link in context.links:
            if (
                link.transport_required
                and not self.capabilities.supports_transport(
                    link.transport_uses
                )
            ):
                diagnostics.append(
                    BackendDiagnostic(
                        level="error",
                        code="BACKEND103",
                        path=f"links[{link.ordinal}].uses",
                        message=(
                            f"backend {self.backend_id!r} does not support "
                            f"transport {link.transport_uses!r}"
                        ),
                    )
                )

        if (
            context.inherited_resources
            and not self.capabilities.supports_feature(
                "system_resources"
            )
        ):
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="BACKEND104",
                    path="inherited_resources",
                    message=(
                        f"backend {self.backend_id!r} does not support "
                        "inherited child System resources"
                    ),
                )
            )

        if (
            context.system_links
            and not self.capabilities.supports_feature(
                "system_interfaces"
            )
        ):
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="BACKEND105",
                    path="system_links",
                    message=(
                        f"backend {self.backend_id!r} does not support "
                        "links across child System interfaces"
                    ),
                )
            )

        for system_link in context.system_links:
            if (
                system_link.transport_required
                and not self.capabilities.supports_transport(
                    system_link.transport_uses
                )
            ):
                diagnostics.append(
                    BackendDiagnostic(
                        level="error",
                        code="BACKEND103",
                        path=(
                            f"system_links[{system_link.ordinal}].uses"
                        ),
                        message=(
                            f"backend {self.backend_id!r} does not support "
                            f"transport {system_link.transport_uses!r}"
                        ),
                    )
                )

        diagnostics.extend(self._validate(context))
        return BackendValidationReport(
            backend=self.backend_id,
            diagnostics=tuple(diagnostics),
        )

    def prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        report = self.validate(context)
        report.raise_for_errors()
        prepared = self._prepare(context)
        self._validate_prepared(prepared, context=context)
        return prepared

    def prepare_plan(
        self,
        plan: SystemExecutionPlan,
        *,
        execution_context: SystemExecutionContext | None = None,
        inherited_resources: tuple[
            PlannedChildSystemResourceBinding,
            ...,
        ] = (),
        system_inbound_links: tuple[BackendSystemLink, ...] = (),
        system_outbound_links: tuple[BackendSystemLink, ...] = (),
    ) -> PreparedExecution:
        return self.prepare(
            self.context(
                plan,
                execution_context=execution_context,
                inherited_resources=inherited_resources,
                system_inbound_links=system_inbound_links,
                system_outbound_links=system_outbound_links,
            )
        )

    def start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        self._validate_prepared(prepared)
        handle = self._start(prepared)
        self._validate_handle(handle, prepared=prepared)
        return handle

    def inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        self._validate_handle(handle)
        status = self._inspect(handle)
        self._validate_status(status, handle=handle)
        return status

    def stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None = None,
    ) -> BackendExecutionStatus:
        self._validate_handle(handle)
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
        status = self._stop(
            handle,
            timeout_seconds=timeout_seconds,
        )
        self._validate_status(status, handle=handle)
        return status

    def _validate_prepared(
        self,
        prepared: PreparedExecution,
        *,
        context: BackendContext | None = None,
    ) -> None:
        if prepared.backend != self.backend_id:
            raise BackendContractError(
                "BACKEND201",
                "PreparedExecution belongs to a different backend",
                path="prepared.backend",
            )
        if prepared.context.backend != self.backend_id:
            raise BackendContractError(
                "BACKEND202",
                "PreparedExecution context belongs to a different backend",
                path="prepared.context.backend",
            )
        if (
            context is not None
            and prepared.context.plan.system_sha256
            != context.plan.system_sha256
        ):
            raise BackendContractError(
                "BACKEND203",
                "PreparedExecution was created for a different System plan",
                path="prepared.context.plan.system_sha256",
            )

    def _validate_handle(
        self,
        handle: BackendExecutionHandle,
        *,
        prepared: PreparedExecution | None = None,
    ) -> None:
        if handle.backend != self.backend_id:
            raise BackendContractError(
                "BACKEND204",
                "execution handle belongs to a different backend",
                path="handle.backend",
            )
        self._validate_prepared(handle.prepared)
        if (
            prepared is not None
            and handle.prepared.context.plan.system_sha256
            != prepared.context.plan.system_sha256
        ):
            raise BackendContractError(
                "BACKEND205",
                "execution handle belongs to a different prepared plan",
                path="handle.prepared",
            )

    def _validate_status(
        self,
        status: BackendExecutionStatus,
        *,
        handle: BackendExecutionHandle,
    ) -> None:
        if status.backend != self.backend_id:
            raise BackendContractError(
                "BACKEND206",
                "status belongs to a different backend",
                path="status.backend",
            )
        if status.execution_id != handle.execution_id:
            raise BackendContractError(
                "BACKEND207",
                "status execution_id does not match the handle",
                path="status.execution_id",
            )

    def _validate(
        self,
        context: BackendContext,
    ) -> Iterable[BackendDiagnostic]:
        return ()

    @abstractmethod
    def _prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        raise NotImplementedError

    @abstractmethod
    def _start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        raise NotImplementedError

    @abstractmethod
    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        raise NotImplementedError

    @abstractmethod
    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        raise NotImplementedError


__all__ = [
    "BackendCapabilities",
    "BackendContext",
    "BackendContractError",
    "BackendDiagnostic",
    "BackendExecutionHandle",
    "BackendExecutionState",
    "BackendExecutionStatus",
    "BackendSystemLink",
    "ExecutionHealthState",
    "ExecutionObservation",
    "ExecutionTiming",
    "BackendValidationError",
    "BackendValidationReport",
    "ExecutionBackend",
    "PreparedExecution",
]
