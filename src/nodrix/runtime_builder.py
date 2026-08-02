from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path
from typing import Any

from .errors import RuntimeGraphError
from .manifest import (
    external_transport_bindings,
)
from .native_plugin import NativePluginNode
from .node import Node, SourceNode
from .node_docs import validate_parameters
from .process_host import ProcessNodeProxy, ProcessSourceProxy
from .registry import load_node_class
from .providers import (
    load_provider_application,
    load_provider_resource,
    load_provider_session,
    provider_for_application,
    provider_for_resource,
    provider_for_session,
    provider_for_transport,
)
from .provider_validation import validate_provider_parameters
from .memory import MemoryRequirement, plan_memory, requirement_for_port
from .packages import resolve_package_node
from .validation import configured_security_issues

try:
    from ._native_queue import BoundedQueue as _NativeBoundedQueue
except Exception:  # pragma: no cover
    _NativeBoundedQueue = None


from .runtime_components import (
    EdgeQueue,
    LoadedApplication,
    LoadedNode,
    LoadedResource,
    LoadedSession,
    NodeStats,
)


class RuntimeBuildMixin:
    def _load_node(self, uses: str, parameters: dict[str, Any]) -> Node:
        uses = resolve_package_node(uses)
        if uses.startswith("native:"):
            body = uses.removeprefix("native:")
            if "#" not in body:
                raise RuntimeGraphError("Native plugin must use native:/path/library#node-type")
            library, node_type = body.rsplit("#", 1)
            path = Path(library).expanduser()
            if not path.is_absolute():
                path = (self.base_dir / path).resolve()
            if not path.exists():
                raise RuntimeGraphError(f"Native plugin library does not exist: {path}")
            return NativePluginNode(path, node_type, parameters)
        if uses.startswith("native."):
            raise RuntimeGraphError(
                "Built-in native.* nodes run in engine: native. Use a native:/path/plugin#type reference inside a unified Python/C++ graph."
            )
        cls = load_node_class(uses, base_dir=self.base_dir)
        return cls(parameters)

    def build(self) -> None:
        self._built = False
        security_issues = configured_security_issues(self.manifest)
        if security_issues:
            raise RuntimeGraphError(
                "; ".join(
                    f"{issue.code} {issue.location}: {issue.message}"
                    for issue in security_issues
                )
            )
        self.nodes.clear()
        self.sessions.clear()
        self.resources.clear()
        self.applications.clear()
        self.edges.clear()
        self._stream_exports.clear()
        self._memory_plans.clear()
        for name, config in self.manifest.sessions.items():
            resolved_session = provider_for_session(
                config.uses,
                include_legacy=False,
            )
            if resolved_session is None:
                raise RuntimeGraphError(
                    f"Unknown provider session {config.uses!r}"
                )
            _candidate, session_descriptor = resolved_session
            validate_provider_parameters(
                session_descriptor.parameters_schema,
                config.parameters,
                location=f"sessions.{name}.parameters",
            )
            session_class = load_provider_session(config.uses)
            if session_class is None:
                raise RuntimeGraphError(
                    f"Unknown provider session {config.uses!r}"
                )
            try:
                instance = session_class(config.parameters)
            except TypeError:
                instance = session_class(parameters=config.parameters)
            self.sessions[name] = LoadedSession(
                name=name,
                uses=config.uses,
                instance=instance,
            )
        for name, config in self.manifest.resources.items():
            resolved_resource = provider_for_resource(
                config.uses,
                include_legacy=False,
            )
            if resolved_resource is None:
                raise RuntimeGraphError(
                    f"Unknown provider resource {config.uses!r}"
                )
            _candidate, resource_descriptor = resolved_resource
            validate_provider_parameters(
                resource_descriptor.parameters_schema,
                config.parameters,
                location=f"resources.{name}.parameters",
            )
            resource_class = load_provider_resource(config.uses)
            if resource_class is None:
                raise RuntimeGraphError(
                    f"Unknown provider resource {config.uses!r}"
                )
            try:
                instance = resource_class(config.parameters)
            except TypeError:
                instance = resource_class(parameters=config.parameters)
            self.resources[name] = LoadedResource(
                name=name,
                uses=config.uses,
                instance=instance,
                config=config,
            )
        for name, config in self.manifest.applications.items():
            resolved_application = provider_for_application(
                config.uses,
                include_legacy=False,
            )
            if resolved_application is None:
                raise RuntimeGraphError(
                    f"Unknown provider application {config.uses!r}"
                )
            _candidate, application_descriptor = resolved_application
            validate_provider_parameters(
                application_descriptor.parameters_schema,
                config.parameters,
                location=f"applications.{name}.parameters",
            )
            application_class = load_provider_application(config.uses)
            if application_class is None:
                raise RuntimeGraphError(
                    f"Unknown provider application {config.uses!r}"
                )
            try:
                instance = application_class(config.parameters)
            except TypeError:
                instance = application_class(parameters=config.parameters)
            for method_name in ("configure", "start", "stop", "health"):
                if not callable(getattr(instance, method_name, None)):
                    raise RuntimeGraphError(
                        f"Provider application {config.uses!r} has no "
                        f"callable {method_name}()"
                    )
            self.applications[name] = LoadedApplication(
                name=name,
                uses=config.uses,
                instance=instance,
                config=config,
            )
        for index, link in enumerate(self.manifest.links):
            resolved_link = provider_for_transport(
                link.uses,
                include_legacy=False,
            )
            if resolved_link is None:
                raise RuntimeGraphError(
                    f"Unknown provider link {link.uses!r}"
                )
            _candidate, link_descriptor = resolved_link
            validate_provider_parameters(
                link_descriptor.parameters_schema,
                link.parameters,
                location=f"links[{index}].parameters",
            )
        for index, edge in enumerate(self.manifest.edges):
            if edge.transport is None:
                continue
            resolved_transport = provider_for_transport(
                edge.transport.uses,
                include_legacy=False,
            )
            if resolved_transport is None:
                raise RuntimeGraphError(
                    f"Unknown provider transport {edge.transport.uses!r}"
                )
            _candidate, transport_descriptor = resolved_transport
            validate_provider_parameters(
                transport_descriptor.parameters_schema,
                edge.transport.parameters,
                location=f"edges[{index}].transport.parameters",
            )
        sample_capacity = self.manifest.runtime.telemetry_samples
        for name, config in self.manifest.nodes.items():
            validate_parameters(config.uses, config.parameters)
            node = self._load_node(config.uses, config.parameters)
            if config.failure.policy == "fallback_node":
                if config.execution.isolation != "in_process":
                    raise RuntimeGraphError(
                        f"Node {name!r}: fallback_node currently requires in_process isolation"
                    )
                assert config.failure.fallback_uses is not None
                validate_parameters(
                    config.failure.fallback_uses,
                    config.parameters,
                )
                fallback = self._load_node(
                    config.failure.fallback_uses,
                    config.parameters,
                )
                if (
                    dict(fallback.input_types) != dict(node.input_types)
                    or dict(fallback.output_types) != dict(node.output_types)
                ):
                    raise RuntimeGraphError(
                        f"Node {name!r}: fallback node ports must exactly match the primary node"
                    )
            if config.execution.isolation == "process":
                original_is_source = isinstance(node, SourceNode)
                shared = self.manifest.runtime.memory.shared_pool
                output_shared = self.manifest.runtime.memory.process_output_pool
                proxy_cls = ProcessSourceProxy if original_is_source else ProcessNodeProxy
                node = proxy_cls(
                    name=name,
                    uses=config.uses,
                    base_dir=self.base_dir,
                    parameters=config.parameters,
                    input_types=dict(node.input_types),
                    output_types=dict(node.output_types),
                    input_memory=dict(getattr(node, "input_memory", {})),
                    output_memory=dict(getattr(node, "output_memory", {})),
                    optional_inputs=set(getattr(node, "optional_inputs", frozenset())),
                    block_size=shared.block_size,
                    capacity=shared.capacity,
                    output_block_size=output_shared.block_size,
                    output_capacity=output_shared.capacity,
                    threshold=shared.threshold,
                    failure_policy=config.failure.policy,
                    max_restarts=config.failure.max_restarts,
                    backoff_ms=config.failure.backoff_ms,
                    cpu_affinity=config.execution.cpu_affinity,
                    device=config.execution.device,
                    max_message_bytes=config.resources.max_message_bytes,
                    memory_limit_mb=config.resources.memory_limit_mb,
                    cpu_limit=config.resources.cpu_limit,
                )
            if config.inputs and dict(config.inputs) != dict(node.input_types):
                raise RuntimeGraphError(
                    f"Node {name!r} declared inputs {config.inputs}, but {config.uses!r} provides {node.input_types}"
                )
            if config.outputs and dict(config.outputs) != dict(node.output_types):
                raise RuntimeGraphError(
                    f"Node {name!r} declared outputs {config.outputs}, but {config.uses!r} provides {node.output_types}"
                )
            if config.synchronization.trigger_port and config.synchronization.trigger_port not in node.input_types:
                raise RuntimeGraphError(
                    f"Node {name!r} synchronization trigger_port {config.synchronization.trigger_port!r} is not an input"
                )
            implementation_optional = set(getattr(node, "optional_inputs", ()))
            configured_optional = set(config.synchronization.optional_inputs)
            unknown_optional = sorted(implementation_optional - set(node.input_types))
            if unknown_optional:
                raise RuntimeGraphError(
                    f"Node {name!r} declares unknown optional inputs: {unknown_optional}"
                )
            unknown_configured = sorted(configured_optional - set(node.input_types))
            if unknown_configured:
                raise RuntimeGraphError(
                    f"Node {name!r} configures unknown optional inputs: {unknown_configured}"
                )
            unsupported_optional = sorted(configured_optional - implementation_optional)
            if unsupported_optional:
                raise RuntimeGraphError(
                    f"Node {name!r} cannot make required inputs optional: {unsupported_optional}"
                )
            self.nodes[name] = LoadedNode(
                name=name,
                node=node,
                config=config,
                stats=NodeStats(sample_capacity),
            )

        for edge_config in self.manifest.edges:
            if edge_config.transport is not None:
                continue
            src_name, src_port = edge_config.source.split(".", 1)
            dst_name, dst_port = edge_config.target.split(".", 1)
            if src_name not in self.nodes or dst_name not in self.nodes:
                raise RuntimeGraphError(f"Edge references unknown node: {edge_config.source} -> {edge_config.target}")
            source = self.nodes[src_name].node
            target = self.nodes[dst_name].node
            if src_port not in source.output_types:
                raise RuntimeGraphError(f"Unknown output port: {edge_config.source}")
            if dst_port not in target.input_types:
                raise RuntimeGraphError(f"Unknown input port: {edge_config.target}")
            source_type = source.output_types[src_port]
            target_type = target.input_types[dst_port]
            if not self._types_compatible(source_type, target_type):
                raise RuntimeGraphError(
                    f"Type mismatch {edge_config.source} ({source_type}) -> {edge_config.target} ({target_type})"
                )
            if dst_port in self.nodes[dst_name].inputs:
                raise RuntimeGraphError(f"Input port already connected: {edge_config.target}")
            source_memory_map = {**dict(getattr(source, "output_memory", {})), **dict(self.nodes[src_name].config.memory.outputs)}
            target_memory_map = {**dict(getattr(target, "input_memory", {})), **dict(self.nodes[dst_name].config.memory.inputs)}
            source_requirement = requirement_for_port(source_memory_map, src_port)
            target_requirement = requirement_for_port(target_memory_map, dst_port)
            if self.nodes[src_name].config.execution.isolation == "process":
                source_requirement = MemoryRequirement(("shared",), preferred="shared")
            if self.nodes[dst_name].config.execution.isolation == "process":
                target_requirement = MemoryRequirement(("shared",), preferred="shared")
            allow_copy = edge_config.memory.allow_copy and not self.manifest.runtime.memory.forbid_implicit_copies
            forced_memory = edge_config.memory.domain
            if forced_memory == "auto" and self.manifest.runtime.memory.default_domain != "auto":
                forced_memory = self.manifest.runtime.memory.default_domain
            memory_plan = plan_memory(
                source_requirement, target_requirement, forced=forced_memory, allow_copy=allow_copy
            )
            if (
                memory_plan.adapter == "host_copy_to_shared"
                and self.nodes[dst_name].config.execution.isolation != "process"
            ):
                memory_plan = replace(
                    memory_plan,
                    runtime_supported=False,
                    reason="in-process CPU-to-shared conversion needs an explicit adapter node",
                )
            if not memory_plan.runtime_supported and (not allow_copy or memory_plan.copies):
                raise RuntimeGraphError(
                    f"Unsupported memory path {edge_config.source} -> {edge_config.target}: "
                    f"{memory_plan.reason} ({memory_plan.source} -> {memory_plan.target})"
                )
            self._memory_plans[(edge_config.source, edge_config.target)] = memory_plan
            edge = EdgeQueue(edge_config, memory_plan)
            self.edges.append(edge)
            self.nodes[src_name].outputs[src_port].append(edge)
            self.nodes[dst_name].inputs[dst_port] = edge

        for export in self.manifest.streams.exports:
            src_name, src_port = export.source.split(".", 1)
            if src_name not in self.nodes:
                raise RuntimeGraphError(f"Stream {export.name!r} references unknown node: {src_name!r}")
            source_node = self.nodes[src_name].node
            if src_port not in source_node.output_types:
                raise RuntimeGraphError(f"Stream {export.name!r} references unknown output: {export.source}")
            self._stream_exports.append({
                "name": export.name,
                "source": export.source,
                "type": source_node.output_types[src_port],
                "capacity": export.queue.capacity,
                "policy": export.queue.policy,
                "access_mode": export.access.mode,
                "token": export.access.token,
                "token_env": export.access.token_env,
                "allow_ips": list(export.access.allow_ips),
            })
        for reference in self._recording_streams:
            source_name, separator, source_port = reference.partition(".")
            if (
                not separator
                or source_name not in self.nodes
                or source_port not in self.nodes[source_name].node.output_types
            ):
                raise RuntimeGraphError(
                    f"Recording references unknown output: {reference!r}"
                )

        for name, loaded in self.nodes.items():
            optional = set(getattr(loaded.node, "optional_inputs", ()))
            missing = sorted(set(loaded.node.input_types) - optional - set(loaded.inputs))
            if missing:
                raise RuntimeGraphError(f"Node {name!r} has unconnected inputs: {missing}")
        if self.nodes and not any(
            isinstance(item.node, SourceNode) for item in self.nodes.values()
        ):
            raise RuntimeGraphError("Unified pipeline requires at least one Python SourceNode")
        self._built = True

    @staticmethod
    def _types_compatible(source: str, target: str) -> bool:
        return source == target or source == "core.any" or target == "core.any"

    def describe(self) -> dict[str, Any]:
        if not self._built:
            self.build()
        return {
            "name": self.manifest.metadata.name,
            "mode": self.manifest.runtime.mode,
            "profile": self.manifest.runtime.profile,
            "engine": "unified",
            "native_queue": self.native_queue_enabled,
            "type_validation": self.manifest.runtime.type_validation,
            "sessions": {
                name: {
                    "uses": loaded.uses,
                    "opened": loaded.opened,
                    "health": self._session_health(loaded),
                }
                for name, loaded in self.sessions.items()
            },
            "resources": {
                name: {
                    "uses": loaded.uses,
                    "opened": loaded.opened,
                    "health": self._managed_resource_health(loaded),
                }
                for name, loaded in self.resources.items()
            },
            "applications": {
                name: {
                    "uses": loaded.uses,
                    "started": loaded.started,
                    "completed": loaded.completed,
                    "health": self._application_health(loaded),
                }
                for name, loaded in self.applications.items()
            },
            "nodes": {
                name: {
                    "class": f"{loaded.node.__class__.__module__}.{loaded.node.__class__.__name__}",
                    "implementation": (
                        "process" if isinstance(loaded.node, ProcessNodeProxy)
                        else "native" if isinstance(loaded.node, NativePluginNode) else "python"
                    ),
                    "isolation": loaded.config.execution.isolation,
                    "failure": loaded.config.failure.model_dump(),
                    "health": loaded.config.health.model_dump(),
                    "resources": loaded.config.resources.model_dump(),
                    "lifecycle": loaded.node.lifecycle_state,
                    "inputs": loaded.node.input_types,
                    "optional_inputs": sorted(getattr(loaded.node, "optional_inputs", ())),
                    "outputs": loaded.node.output_types,
                    "input_memory": {**dict(getattr(loaded.node, "input_memory", {})), **dict(loaded.config.memory.inputs)},
                    "output_memory": {**dict(getattr(loaded.node, "output_memory", {})), **dict(loaded.config.memory.outputs)},
                    "device": loaded.config.execution.device,
                    "synchronization": loaded.config.synchronization.model_dump(),
                    "async_process": inspect.iscoroutinefunction(loaded.node.process),
                }
                for name, loaded in self.nodes.items()
            },
            "edges": [
                {
                    "from": edge.edge.source,
                    "to": edge.edge.target,
                    "type": self._edge_type(edge.edge.source),
                    "queue": edge.edge.queue.model_dump(),
                    "memory": None if edge.memory_plan is None else edge.memory_plan.as_dict(),
                }
                for edge in self.edges
            ],
            "links": [
                link.model_dump(by_alias=True, mode="json")
                for link in self.manifest.links
            ],
            "transports": list(external_transport_bindings(self.manifest)),
            "streams": [
                {key: value for key, value in item.items() if key != "token"}
                for item in self._stream_exports
            ],
        }

    def _edge_type(self, source: str) -> str:
        node, port = source.split(".", 1)
        return self.nodes[node].node.output_types[port]
