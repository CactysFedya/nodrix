"""Local execution backend for Nodrix 2.6.

The backend intentionally reuses the existing 2.x HybridPipelineRuntime.
It lowers one resolved local BackendContext into a compatibility
PipelineManifest, then delegates execution to the proven runtime.
"""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import TYPE_CHECKING, Any, Callable, Mapping
from uuid import uuid4

from ..metric_publisher import MetricSink
from ..environment_materialization import materialize_environment
from ..manifest import PipelineManifest, dump_manifest
from ..storage_layout import StorageLayout
from .backend import (
    BackendCapabilities,
    BackendContext,
    BackendDiagnostic,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    ExecutionHealthState,
    ExecutionObservation,
    PreparedExecution,
)
from .execution_context import SystemExecutionContext
from .graph import split_system_endpoint


if TYPE_CHECKING:
    from ..local_dev import LocalProject


@dataclass(frozen=True, slots=True)
class LocalLoweringResult:
    manifest: PipelineManifest
    node_aliases: Mapping[str, str]
    generated_from_legacy_snapshot: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_aliases", dict(self.node_aliases))


@dataclass(frozen=True, slots=True)
class LocalPreparedPayload:
    lowering: LocalLoweringResult
    manifest_path: Path
    runtime: Any
    project: LocalProject | None = None


@dataclass(slots=True)
class _LocalExecution:
    runtime: Any
    project: LocalProject | None
    thread: threading.Thread | None = None
    report: dict[str, Any] | None = None
    error: BaseException | None = None
    state: BackendExecutionState = BackendExecutionState.PREPARED
    lock: threading.Lock = field(default_factory=threading.Lock)


def _default_runtime_factory(
    manifest: PipelineManifest,
    manifest_path: Path,
    run_root: Path | None,
) -> Any:
    """Create the existing runtime lazily.

    HybridPipelineRuntime must not be imported while nodrix.__init__
    is still importing the public System API.
    """
    from ..hybrid_runtime import HybridPipelineRuntime

    return HybridPipelineRuntime(
        manifest,
        manifest_path,
        run_root=run_root,
    )


def _compile_local_project(path: Path):
    from ..local_dev import compile_local_project, reset_local_development_modules

    # The reserved ``local`` namespace intentionally represents one active
    # development project. Drop stale implicit-project modules before compiling
    # another project in the same Python process.
    reset_local_development_modules()
    return compile_local_project(path)


def _activate_local_project(project):
    from ..local_dev import activate_local_project

    return activate_local_project(project)


def _legacy_snapshot(plan) -> PipelineManifest | None:
    legacy = plan.extensions.get("legacy_pipeline")
    if not isinstance(legacy, Mapping):
        return None

    payload = legacy.get("source_manifest_json")
    expected = legacy.get("source_manifest_sha256")
    if not isinstance(payload, str) or not payload:
        return None
    if not isinstance(expected, str) or not expected:
        return None

    actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if actual != expected:
        raise ValueError(
            "legacy Pipeline snapshot digest mismatch while preparing LocalBackend"
        )

    raw = json.loads(payload)
    return PipelineManifest.model_validate(raw)


def _endpoint_alias(
    value: str,
    *,
    aliases: Mapping[str, str],
) -> str:
    graph, instance, port = split_system_endpoint(value)
    if graph is None:
        return f"{instance}.{port}"
    key = f"{graph}/{instance}"
    try:
        name = aliases[key]
    except KeyError as exc:
        raise ValueError(f"unknown planned node endpoint {key!r}") from exc
    return f"{name}.{port}"


def _external_endpoint_label(
    value: str,
    *,
    system_path: tuple[str, ...],
    local_owner: str,
) -> str:
    """Return a local placeholder carrying stable remote endpoint identity."""

    graph, instance, port = split_system_endpoint(value)
    owner = instance if graph is None else f"{graph}__{instance}"
    remote = "__".join((*system_path, owner, port))
    token = re.sub(r"[^A-Za-z0-9_]+", "_", remote)
    return f"{local_owner}.__nodrix_remote__{token}"


def _node_aliases(context: BackendContext) -> dict[str, str]:
    applications = {item.name for item in context.applications}
    by_name: dict[str, list[str]] = {}
    for node in context.nodes:
        by_name.setdefault(node.name, []).append(node.id)

    result: dict[str, str] = {}
    used = set(applications)
    for node in context.nodes:
        if len(by_name[node.name]) == 1 and node.name not in used:
            candidate = node.name
        else:
            candidate = f"{node.graph}__{node.name}"

        candidate = candidate.replace(".", "_").replace("/", "__")
        base = candidate
        suffix = 2
        while candidate in used:
            candidate = f"{base}__{suffix}"
            suffix += 1

        used.add(candidate)
        result[node.id] = candidate

    return result


def _legacy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _session_resource_names(context: BackendContext) -> frozenset[str]:
    """Infer resources that must lower to the legacy runtime session namespace.

    The public System model intentionally exposes one ResourceInstance concept.
    The existing 2.x runtime still has a separate ``sessions`` namespace.
    Preserve converted legacy roles, and infer the compatibility namespace from
    explicit consumer binding slots named ``session`` for newly-authored Systems.
    """

    declared = {item.name for item in context.resources}
    names = {
        item.name
        for item in context.resources
        if item.extensions.get("legacy_role") == "session"
    }

    for resource in context.resources:
        bound = resource.bindings.get("session")
        if bound in declared:
            names.add(bound)

    for application in context.applications:
        bound = application.resources.get("session")
        if bound in declared:
            names.add(bound)

    for node in context.nodes:
        bound = node.resources.get("session")
        if bound in declared:
            names.add(bound)

    return frozenset(names)


def _scope_file_token(value: str) -> str:
    """Return a portable file token for an orchestration scope label."""

    token = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return token or "scope"


def _materialize_local_execution_environment(
    context: BackendContext,
    *,
    cwd: Path,
) -> dict[str, str] | None:
    execution_context = context.execution_context

    if execution_context is None:
        return None

    if (
        not execution_context.variables
        and not execution_context.sources
    ):
        return None

    return materialize_environment(
        base=os.environ,
        variables=execution_context.variables,
        sources=execution_context.sources,
        cwd=cwd,
        activation_label="System execution environment",
    )


def _bind_runtime_execution_environment(
    runtime: Any,
    environment: Mapping[str, str] | None,
) -> None:
    if environment is None:
        return

    setter = getattr(
        runtime,
        "set_execution_environment",
        None,
    )

    if not callable(setter):
        raise RuntimeError(
            "Local runtime does not support the explicit "
            "System execution environment required by this Plan"
        )

    setter(
        environment
    )



def _bind_runtime_metric_sink(
    runtime: Any,
    sink: MetricSink | None,
) -> None:
    """Bind canonical Metrics capability into a compatibility runtime."""

    if sink is None:
        return

    if not isinstance(
        sink,
        MetricSink,
    ):
        raise TypeError(
            "metric sink must implement MetricSink"
        )

    setter = getattr(
        runtime,
        "set_metric_sink",
        None,
    )

    if not callable(
        setter
    ):
        raise TypeError(
            "runtime does not expose the canonical "
            "MetricSink binding contract"
        )

    setter(
        sink
    )


def _deep_merge_defaults(
    defaults: Mapping[str, Any],
    explicit: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge execution defaults under explicit resolved semantics."""

    result = deepcopy(
        dict(defaults)
    )

    for key, value in explicit.items():
        current = result.get(key)

        if (
            isinstance(current, Mapping)
            and isinstance(value, Mapping)
        ):
            result[key] = _deep_merge_defaults(
                current,
                value,
            )
        else:
            result[key] = deepcopy(
                value
            )

    return result


def _apply_execution_defaults(
    document: Mapping[str, Any],
    execution_context: SystemExecutionContext | None,
) -> dict[str, Any]:
    """Apply verified execution defaults to a raw local manifest document."""

    result = deepcopy(
        dict(document)
    )

    if execution_context is None:
        return result

    # RuntimePreset values are defaults. Explicit runtime values win.
    result["runtime"] = _deep_merge_defaults(
        execution_context.runtime,
        _legacy_mapping(
            result.get("runtime")
        ),
    )

    # Node defaults are selected by node provider/use identifier.
    nodes = _legacy_mapping(
        result.get("nodes")
    )

    for name, raw_node in tuple(
        nodes.items()
    ):
        if not isinstance(
            raw_node,
            Mapping,
        ):
            continue

        uses = str(
            raw_node.get("uses")
            or ""
        )

        defaults = (
            execution_context
            .node_defaults
            .get(uses)
        )

        if isinstance(
            defaults,
            Mapping,
        ):
            nodes[name] = _deep_merge_defaults(
                defaults,
                raw_node,
            )

    result["nodes"] = nodes

    # Edge defaults apply below every explicit edge declaration.
    result["edges"] = [
        (
            _deep_merge_defaults(
                execution_context.edge_defaults,
                edge,
            )
            if isinstance(
                edge,
                Mapping,
            )
            else deepcopy(edge)
        )
        for edge in list(
            result.get("edges")
            or ()
        )
    ]

    # Stream defaults apply to the stream container. Legacy RuntimePreset
    # queue semantics apply separately to every exported stream.
    stream_defaults = deepcopy(
        dict(
            execution_context.stream_defaults
        )
    )

    export_queue = stream_defaults.pop(
        "queue",
        None,
    )

    streams = _deep_merge_defaults(
        stream_defaults,
        _legacy_mapping(
            result.get("streams")
        ),
    )

    if export_queue is not None:
        exports = list(
            streams.get("exports")
            or ()
        )

        streams["exports"] = [
            (
                _deep_merge_defaults(
                    {
                        "queue": export_queue,
                    },
                    export,
                )
                if isinstance(
                    export,
                    Mapping,
                )
                else deepcopy(export)
            )
            for export in exports
        ]

    result["streams"] = streams

    return result


def lower_local_context(context: BackendContext) -> LocalLoweringResult:
    """Lower one local BackendContext to the existing 2.x PipelineManifest.

    Converted 2.x Systems use their integrity-protected original manifest when
    the complete System is owned by the local backend. New Systems are lowered
    structurally.
    """

    legacy_manifest = _legacy_snapshot(context.plan)
    if legacy_manifest is not None:
        owned_backends = {
            target.backend for target in context.plan.targets
        } | {
            node.backend
            for graph in context.plan.graphs
            for node in graph.nodes
        } | {
            app.backend for app in context.plan.applications
        } | {
            resource.backend for resource in context.plan.resources
        }
        if (
            owned_backends <= {context.backend}
            and not context.system_links
        ):
            return LocalLoweringResult(
                manifest=legacy_manifest,
                node_aliases={
                    node.id: node.name
                    for node in context.nodes
                },
                generated_from_legacy_snapshot=True,
            )

    aliases = _node_aliases(context)
    session_names = _session_resource_names(context)

    sessions: dict[str, Any] = {}
    resources: dict[str, Any] = {}
    for resource in context.resources:
        legacy = _legacy_mapping(resource.extensions.get("legacy"))
        if resource.name in session_names:
            sessions[resource.name] = {
                "uses": resource.uses,
                "parameters": dict(resource.parameters),
            }
            continue

        resources[resource.name] = {
            "uses": resource.uses,
            "parameters": dict(resource.parameters),
            "bindings": dict(resource.bindings),
        }

    applications = {
        application.name: {
            "uses": application.uses,
            "parameters": dict(application.parameters),
            "bindings": dict(application.resources),
        }
        for application in context.applications
    }

    nodes: dict[str, Any] = {}
    for node in context.nodes:
        legacy = _legacy_mapping(node.extensions.get("legacy"))
        nodes[aliases[node.id]] = {
            "uses": node.uses,
            "parameters": dict(node.parameters),
            "inputs": dict(legacy.get("inputs") or node.inputs),
            "outputs": dict(legacy.get("outputs") or node.outputs),
            "synchronization": dict(legacy.get("synchronization") or {}),
            "execution": dict(legacy.get("execution") or {}),
            "failure": dict(legacy.get("failure") or {}),
            "health": dict(legacy.get("health") or {}),
            "resources": dict(legacy.get("resource_limits") or {}),
            "memory": dict(legacy.get("memory") or {}),
            "bindings": dict(node.resources),
            "placement": node.target,
        }

    edges: list[dict[str, Any]] = []
    for connection in context.connections:
        legacy = _legacy_mapping(connection.extensions.get("legacy"))
        source_node, source_port = connection.source.split(".", 1)
        target_node, target_port = connection.target.split(".", 1)
        source = aliases[f"{connection.graph}/{source_node}"] + "." + source_port
        target = aliases[f"{connection.graph}/{target_node}"] + "." + target_port
        edges.append(
            {
                "from": source,
                "to": target,
                "queue": dict(legacy.get("queue") or {}),
                "memory": dict(legacy.get("memory") or {}),
            }
        )

    links: list[dict[str, Any]] = []
    for link in context.internal_links:
        source = _endpoint_alias(link.source, aliases=aliases)
        target = _endpoint_alias(link.target, aliases=aliases)

        if link.boundary == "cross_graph" and not link.transport_required:
            edges.append({"from": source, "to": target})
            continue

        if link.boundary == "application":
            links.append(
                {
                    "from": source,
                    "to": target,
                    "uses": link.transport_uses,
                    "parameters": dict(link.parameters),
                }
            )
            continue

        # A transport-backed graph-to-graph link is represented by the existing
        # 2.x transport edge. Runtime/provider validation remains authoritative.
        edges.append(
            {
                "from": source,
                "to": target,
                "transport": {
                    "uses": link.transport_uses,
                    "parameters": dict(link.parameters),
                },
            }
        )

    system_links_by_identity: dict[
        tuple[tuple[str, ...], int],
        list[Any],
    ] = {}

    for system_link in context.system_links:
        identity = (
            system_link.owner_system_path,
            system_link.ordinal,
        )
        system_links_by_identity.setdefault(
            identity,
            [],
        ).append(system_link)

    for identity in sorted(system_links_by_identity):
        sides = system_links_by_identity[identity]
        outbound = next(
            (item for item in sides if item.direction == "outbound"),
            None,
        )
        inbound = next(
            (item for item in sides if item.direction == "inbound"),
            None,
        )
        representative = outbound or inbound
        assert representative is not None
        if representative.transport_uses is None:
            raise ValueError(
                "LocalBackend cannot lower an in-memory link across "
                "independent child System runtimes"
            )

        if outbound is not None and inbound is not None:
            source = _endpoint_alias(
                outbound.local_endpoint,
                aliases=aliases,
            )
            target = _endpoint_alias(
                inbound.local_endpoint,
                aliases=aliases,
            )
        elif outbound is not None:
            source = _endpoint_alias(
                outbound.local_endpoint,
                aliases=aliases,
            )
            target = _external_endpoint_label(
                outbound.remote_endpoint,
                system_path=outbound.remote_system_path,
                local_owner=source.split(".", 1)[0],
            )
        else:
            assert inbound is not None
            target = _endpoint_alias(
                inbound.local_endpoint,
                aliases=aliases,
            )
            source = _external_endpoint_label(
                inbound.remote_endpoint,
                system_path=inbound.remote_system_path,
                local_owner=target.split(".", 1)[0],
            )

        links.append(
            {
                "from": source,
                "to": target,
                "uses": representative.transport_uses,
                "parameters": dict(representative.link.parameters),
            }
        )

    legacy_pipeline = context.plan.extensions.get("legacy_pipeline")
    legacy_pipeline = (
        dict(legacy_pipeline)
        if isinstance(legacy_pipeline, Mapping)
        else {}
    )

    runtime = dict(legacy_pipeline.get("runtime") or {})
    runtime["engine"] = "unified"

    placement_nodes = {
        aliases[node.id]: node.target
        for node in context.nodes
    }
    default_target = (
        context.targets[0].name
        if len(context.targets) == 1
        else "local"
    )

    document: dict[str, Any] = {
            "metadata": {
                "name": context.plan.system,
                "description": (
                    f"Generated from {context.plan.schema_id} for LocalBackend"
                ),
            },
            "runtime": runtime,
            "sessions": sessions,
            "resources": resources,
            "applications": applications,
            "nodes": nodes,
            "edges": edges,
            "links": links,
            "streams": dict(legacy_pipeline.get("streams") or {}),
            "recording": dict(legacy_pipeline.get("recording") or {}),
            "security": dict(legacy_pipeline.get("security") or {}),
            "placement": {
                "default": default_target,
                "nodes": placement_nodes,
            },
        }

    document = _apply_execution_defaults(
        document,
        context.execution_context,
    )

    manifest = PipelineManifest.model_validate(
        document
    )

    return LocalLoweringResult(
        manifest=manifest,
        node_aliases=aliases,
        generated_from_legacy_snapshot=False,
    )


def _health_token(value: Any) -> str:
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return str(raw).strip().lower().rsplit(".", 1)[-1]


def _local_runtime_observation(
    snapshot: Mapping[str, Any],
    *,
    state: BackendExecutionState,
    error: BaseException | None,
) -> ExecutionObservation:
    if error is not None or state is BackendExecutionState.FAILED:
        message = (
            f"{type(error).__name__}: {error}"
            if error is not None
            else "local execution failed"
        )
        return ExecutionObservation(
            ready=False,
            health=ExecutionHealthState.UNHEALTHY,
            message=message,
        )

    unhealthy_states = {
        "error",
        "failed",
        "failure",
        "unhealthy",
        "crashed",
        "dead",
    }
    degraded_states = {
        "degraded",
        "warning",
        "warn",
        "stale",
    }
    healthy_states = {
        "ok",
        "healthy",
        "ready",
        "running",
        "active",
        "open",
        "completed",
        "stopped",
        "closed",
        "idle",
        "created",
        "configured",
    }
    not_ready_states = {
        "completed",
        "stopped",
        "closed",
        "idle",
        "created",
        "configured",
    }
    ranks = {
        ExecutionHealthState.UNKNOWN: 0,
        ExecutionHealthState.HEALTHY: 1,
        ExecutionHealthState.DEGRADED: 2,
        ExecutionHealthState.UNHEALTHY: 3,
    }

    health = ExecutionHealthState.UNKNOWN
    readiness: list[bool | None] = []
    problems: list[str] = []
    not_ready: list[str] = []

    def merge(candidate: ExecutionHealthState) -> None:
        nonlocal health
        if ranks[candidate] > ranks[health]:
            health = candidate

    runtime_status = _health_token(snapshot.get("status"))
    if runtime_status in unhealthy_states:
        merge(ExecutionHealthState.UNHEALTHY)
        readiness.append(False)
        problems.append(f"runtime: {runtime_status}")
    elif runtime_status in degraded_states:
        merge(ExecutionHealthState.DEGRADED)
        readiness.append(None)
        problems.append(f"runtime: {runtime_status}")
    elif runtime_status in healthy_states:
        merge(ExecutionHealthState.HEALTHY)
        runtime_ready = runtime_status not in not_ready_states
        readiness.append(runtime_ready)
        if not runtime_ready:
            not_ready.append("runtime")
    else:
        readiness.append(None)

    for group_name in ("nodes", "applications", "resources", "sessions"):
        group = snapshot.get(group_name)
        if not isinstance(group, Mapping):
            continue

        for name, value in group.items():
            label = f"{group_name.rstrip('s')} {name}"
            if not isinstance(value, Mapping):
                readiness.append(None)
                continue

            nested = value.get("health")
            record = nested if isinstance(nested, Mapping) else value
            token = _health_token(
                record.get("status", record.get("state"))
            )

            ready: bool | None = None
            explicit_ready = record.get("ready")
            if isinstance(explicit_ready, bool):
                ready = explicit_ready
            else:
                for key in ("running", "open"):
                    candidate = record.get(key)
                    if isinstance(candidate, bool):
                        ready = candidate
                        break

            if ready is None:
                if token in unhealthy_states or token in not_ready_states:
                    ready = False
                elif token in healthy_states:
                    ready = True

            readiness.append(ready)
            if ready is False:
                not_ready.append(label)

            explicitly_healthy = record.get("healthy")
            if explicitly_healthy is False or token in unhealthy_states:
                component_health = ExecutionHealthState.UNHEALTHY
            elif token in degraded_states:
                component_health = ExecutionHealthState.DEGRADED
            elif explicitly_healthy is True or token in healthy_states:
                component_health = ExecutionHealthState.HEALTHY
            else:
                component_health = ExecutionHealthState.UNKNOWN

            merge(component_health)

            if component_health in {
                ExecutionHealthState.DEGRADED,
                ExecutionHealthState.UNHEALTHY,
            }:
                reason = (
                    record.get("message")
                    or record.get("error")
                    or token
                    or component_health.value
                )
                problems.append(f"{label}: {reason}")

    if state is BackendExecutionState.RUNNING:
        if any(value is False for value in readiness):
            ready = False
        elif any(value is None for value in readiness):
            ready = None
        else:
            ready = True
    elif state in {
        BackendExecutionState.STOPPING,
        BackendExecutionState.STOPPED,
        BackendExecutionState.COMPLETED,
        BackendExecutionState.FAILED,
    }:
        ready = False
    else:
        ready = None

    if (
        state in {
            BackendExecutionState.STOPPED,
            BackendExecutionState.COMPLETED,
        }
        and health is ExecutionHealthState.UNKNOWN
    ):
        health = ExecutionHealthState.HEALTHY

    if problems:
        message = "; ".join(problems[:3])
    elif state is BackendExecutionState.RUNNING and ready is False:
        message = "not ready: " + ", ".join(not_ready[:3])
    elif state is BackendExecutionState.RUNNING and ready is None:
        message = "local runtime readiness is unknown"
    else:
        message = None

    return ExecutionObservation(
        ready=ready,
        health=health,
        message=message,
    )


class LocalBackend(ExecutionBackend):
    """Execute a local System scope through the existing HybridPipelineRuntime."""

    def __init__(
        self,
        *,
        project: str | Path | None = None,
        working_directory: str | Path | None = None,
        run_root: str | Path | None = None,
        stop_timeout_seconds: float = 10.0,
        runtime_factory: Callable[[PipelineManifest, Path, Path | None], Any] | None = None,
        scope_name: str | None = None,
    ) -> None:
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds=frozenset({"local", "host"}),
                features=frozenset(
                    {
                        "legacy_runtime",
                        "graphs",
                        "resources",
                        "applications",
                        "system_links",
                        "system_interfaces",
                        "readiness",
                        "health",
                    }
                ),
            ),
        )
        self.project_path = (
            Path(project).expanduser().resolve()
            if project is not None
            else None
        )
        self.working_directory = (
            Path(working_directory).expanduser().resolve()
            if working_directory is not None
            else (
                self.project_path
                if self.project_path is not None
                else Path.cwd().resolve()
            )
        )
        self.run_root = (
            Path(run_root).expanduser().resolve()
            if run_root is not None
            else None
        )
        if stop_timeout_seconds < 0:
            raise ValueError("stop_timeout_seconds cannot be negative")
        self.stop_timeout_seconds = float(stop_timeout_seconds)
        self.runtime_factory = runtime_factory or _default_runtime_factory
        self.scope_name = (
            _scope_file_token(scope_name)
            if scope_name is not None
            else None
        )

    def _validate(self, context: BackendContext):
        diagnostics: list[BackendDiagnostic] = []

        if context.inbound_links or context.outbound_links:
            diagnostics.append(
                BackendDiagnostic(
                    level="error",
                    code="LOCAL101",
                    path="links",
                    message=(
                        "LocalBackend M3 does not orchestrate another backend yet; "
                        "cross-backend inbound/outbound links require the future "
                        "multi-backend system runner"
                    ),
                )
            )

        for system_link in context.system_links:
            if system_link.transport_uses is None:
                diagnostics.append(
                    BackendDiagnostic(
                        level="error",
                        code="LOCAL103",
                        path=f"system_links[{system_link.ordinal}].uses",
                        message=(
                            "LocalBackend keeps child Systems in independent "
                            "runtime boundaries; their link requires an explicit "
                            "transport provider"
                        ),
                    )
                )

        session_names = _session_resource_names(context)
        for resource in context.resources:
            if resource.name in session_names:
                continue
            unsupported = sorted(
                set(resource.bindings.values()) - session_names
            )
            if unsupported:
                diagnostics.append(
                    BackendDiagnostic(
                        level="error",
                        code="LOCAL102",
                        path=f"resources.{resource.name}.bindings",
                        message=(
                            "the existing 2.x runtime can lower Resource bindings "
                            "only to legacy session-style resources; unsupported "
                            "dependencies: " + ", ".join(unsupported)
                        ),
                    )
                )

        return diagnostics

    def _prepare(self, context: BackendContext) -> PreparedExecution:
        project: LocalProject | None = None
        if self.project_path is not None:
            project = _compile_local_project(self.project_path)
            project_root = project.root
        else:
            project_root = self.working_directory

        execution_environment = (
            _materialize_local_execution_environment(
                context,
                cwd=project_root,
            )
        )

        lowering = lower_local_context(context)

        generated_dir = StorageLayout(
            project_root
        ).system_generated_root
        generated_dir.mkdir(parents=True, exist_ok=True)
        scope_suffix = f"-{self.scope_name}" if self.scope_name else ""
        manifest_path = generated_dir / (
            f"{context.plan.system}-{context.plan.system_sha256[:12]}"
            f"{scope_suffix}-local.yaml"
        )
        dump_manifest(lowering.manifest, manifest_path)

        runtime = self.runtime_factory(
            lowering.manifest,
            manifest_path,
            self.run_root,
        )
        _bind_runtime_execution_environment(
            runtime,
            execution_environment,
        )
        _bind_runtime_metric_sink(
            runtime,
            context.metric_sink,
        )


        activation = (
            _activate_local_project(project)
            if project is not None
            else nullcontext()
        )
        with activation:
            build = getattr(runtime, "build", None)
            if callable(build):
                build()

        return PreparedExecution(
            backend=self.backend_id,
            context=context,
            payload=LocalPreparedPayload(
                lowering=lowering,
                manifest_path=manifest_path,
                runtime=runtime,
                project=project,
            ),
            metadata={
                "manifest_path": str(manifest_path),
                "legacy_snapshot": lowering.generated_from_legacy_snapshot,
                "node_aliases": dict(lowering.node_aliases),
            },
        )

    def _start(self, prepared: PreparedExecution) -> BackendExecutionHandle:
        payload = prepared.payload
        if not isinstance(payload, LocalPreparedPayload):
            raise TypeError("LocalBackend requires LocalPreparedPayload")

        execution = _LocalExecution(
            runtime=payload.runtime,
            project=payload.project,
        )

        execution_id = f"local-{uuid4().hex[:12]}"

        def worker() -> None:
            activation = (
                _activate_local_project(execution.project)
                if execution.project is not None
                else nullcontext()
            )
            try:
                with execution.lock:
                    execution.state = BackendExecutionState.RUNNING
                with activation:
                    report = execution.runtime.run_sync()
                with execution.lock:
                    execution.report = dict(report or {})
                    status = str(execution.report.get("status", "completed")).lower()
                    execution.state = (
                        BackendExecutionState.STOPPED
                        if status == "stopped"
                        else BackendExecutionState.FAILED
                        if status == "failed"
                        else BackendExecutionState.COMPLETED
                    )
            except BaseException as exc:
                with execution.lock:
                    execution.error = exc
                    execution.state = BackendExecutionState.FAILED

        thread = threading.Thread(
            target=worker,
            name=f"nodrix-system:{execution_id}",
            daemon=False,
        )
        execution.thread = thread
        thread.start()

        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id=execution_id,
            prepared=prepared,
            payload=execution,
        )

    def _execution(
        self,
        handle: BackendExecutionHandle,
    ) -> _LocalExecution:
        execution = handle.payload
        if not isinstance(execution, _LocalExecution):
            raise TypeError("LocalBackend handle contains an invalid payload")
        return execution

    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        execution = self._execution(handle)
        with execution.lock:
            state = execution.state
            report = dict(execution.report or {})
            error = execution.error

        details: dict[str, Any] = {
            "thread_alive": bool(
                execution.thread is not None
                and execution.thread.is_alive()
            ),
        }
        if report:
            details["report"] = report
        if error is not None:
            details["error"] = f"{type(error).__name__}: {error}"

        observation: ExecutionObservation | None = None
        snapshotter = getattr(execution.runtime, "snapshot", None)
        if callable(snapshotter):
            try:
                snapshot_value = snapshotter()
                if not isinstance(snapshot_value, Mapping):
                    raise TypeError(
                        "runtime snapshot must return a mapping"
                    )
                snapshot = dict(snapshot_value)
                details["snapshot"] = snapshot
                observation = _local_runtime_observation(
                    snapshot,
                    state=state,
                    error=error,
                )
            except Exception as exc:
                observation_error = f"{type(exc).__name__}: {exc}"
                details["observation_error"] = observation_error
                observation = ExecutionObservation(
                    ready=(
                        False
                        if state is BackendExecutionState.FAILED
                        else None
                    ),
                    health=(
                        ExecutionHealthState.UNHEALTHY
                        if state is BackendExecutionState.FAILED
                        else ExecutionHealthState.UNKNOWN
                    ),
                    message=(
                        f"local runtime observation failed: "
                        f"{observation_error}"
                    ),
                )

        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=state,
            message=(
                None
                if error is None
                else f"{type(error).__name__}: {error}"
            ),
            details=details,
            observation=observation,
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        execution = self._execution(handle)

        requester = getattr(execution.runtime, "request_stop", None)
        if callable(requester):
            requester()

        with execution.lock:
            if execution.state is BackendExecutionState.RUNNING:
                execution.state = BackendExecutionState.STOPPING

        timeout = (
            self.stop_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if execution.thread is not None:
            execution.thread.join(timeout=timeout)

        if (
            execution.thread is not None
            and execution.thread.is_alive()
        ):
            status = self._inspect(handle)
            return BackendExecutionStatus(
                backend=self.backend_id,
                execution_id=handle.execution_id,
                state=BackendExecutionState.STOPPING,
                message="local runtime is still stopping",
                details=status.details,
                observation=status.observation,
            )

        return self._inspect(handle)


__all__ = [
    "LocalBackend",
    "LocalLoweringResult",
    "LocalPreparedPayload",
    "lower_local_context",
]
