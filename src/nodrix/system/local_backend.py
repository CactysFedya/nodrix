"""Local execution backend for Nodrix 2.6.

The backend intentionally reuses the existing 2.x HybridPipelineRuntime.
It lowers one resolved local BackendContext into a compatibility
PipelineManifest, then delegates execution to the proven runtime.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import threading
from typing import TYPE_CHECKING, Any, Callable, Mapping
from uuid import uuid4

from ..manifest import PipelineManifest, dump_manifest
from .backend import (
    BackendCapabilities,
    BackendContext,
    BackendDiagnostic,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    PreparedExecution,
)
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
    from ..local_dev import compile_local_project

    return compile_local_project(path)


def __activate_local_project(project):
    from ..local_dev import activate_local_project

    return _activate_local_project(project)


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
        if owned_backends <= {context.backend}:
            return LocalLoweringResult(
                manifest=legacy_manifest,
                node_aliases={
                    node.id: node.name
                    for node in context.nodes
                },
                generated_from_legacy_snapshot=True,
            )

    aliases = _node_aliases(context)

    sessions: dict[str, Any] = {}
    resources: dict[str, Any] = {}
    for resource in context.resources:
        legacy = _legacy_mapping(resource.extensions.get("legacy"))
        legacy_role = resource.extensions.get("legacy_role")
        if legacy_role == "session":
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

    manifest = PipelineManifest.model_validate(
        {
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
    )

    return LocalLoweringResult(
        manifest=manifest,
        node_aliases=aliases,
        generated_from_legacy_snapshot=False,
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

        session_names = {
            item.name
            for item in context.resources
            if item.extensions.get("legacy_role") == "session"
        }
        for resource in context.resources:
            if resource.extensions.get("legacy_role") == "session":
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
        lowering = lower_local_context(context)

        project: LocalProject | None = None
        if self.project_path is not None:
            project = _compile_local_project(self.project_path)
            project_root = project.root
        else:
            project_root = self.working_directory

        generated_dir = project_root / ".nodrix" / "system-generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = generated_dir / (
            f"{context.plan.system}-{context.plan.system_sha256[:12]}-local.yaml"
        )
        dump_manifest(lowering.manifest, manifest_path)

        runtime = self.runtime_factory(
            lowering.manifest,
            manifest_path,
            self.run_root,
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
            return BackendExecutionStatus(
                backend=self.backend_id,
                execution_id=handle.execution_id,
                state=BackendExecutionState.STOPPING,
                message="local runtime is still stopping",
                details={"thread_alive": True},
            )

        return self._inspect(handle)


__all__ = [
    "LocalBackend",
    "LocalLoweringResult",
    "LocalPreparedPayload",
    "lower_local_context",
]
