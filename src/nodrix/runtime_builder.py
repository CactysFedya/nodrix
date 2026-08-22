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
from .process_host import ProcessNodeProxy, ProcessSourceProxy
from .runtime_node_loading import load_runtime_node
from .runtime_node_materialization import (
    validate_runtime_node_materialization,
    validate_runtime_node_parameters,
)
from .providers import (
    load_provider_session,
    provider_for_session,
    provider_for_transport,
)
from .provider_validation import validate_provider_parameters
from .memory import MemoryRequirement, plan_memory, requirement_for_port
from .validation import configured_security_issues

try:
    from ._native_queue import BoundedQueue as _NativeBoundedQueue
except Exception:  # pragma: no cover
    _NativeBoundedQueue = None


from .runtime_components import (
    runtime_application_binding_from_config,
    runtime_node_binding_from_config,
    runtime_resource_binding_from_config,
)
from .runtime_components import (
    EdgeQueue,
    LoadedNode,
    LoadedSession,
    NodeStats,
)
from .runtime_provider_materialization import (
    materialize_runtime_application,
    materialize_runtime_resource,
)


class RuntimeBuildMixin:
    def _load_node(
        self,
        uses: str,
        parameters: dict[str, Any],
    ) -> Node:
        """Compatibility wrapper around backend-neutral node loading."""

        return load_runtime_node(
            uses,
            parameters,
            base_dir=self.base_dir,
        )

    def build(self) -> None:
        self._lock_execution_environment()
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
            binding = runtime_resource_binding_from_config(
                config
            )
            self.resources[name] = materialize_runtime_resource(
                name,
                binding,
            )
        for name, config in self.manifest.applications.items():
            binding = runtime_application_binding_from_config(
                config
            )
            self.applications[name] = materialize_runtime_application(
                name,
                binding,
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
            binding = (
                runtime_node_binding_from_config(
                    config
                )
            )

            validate_runtime_node_parameters(
                binding
            )

            node = self._load_node(
                binding.uses,
                dict(
                    binding.parameters
                ),
            )

            validate_runtime_node_materialization(
                name=name,
                node=node,
                binding=binding,
                declared_inputs=config.inputs,
                declared_outputs=config.outputs,
                base_dir=self.base_dir,
            )

            if binding.isolation == "process":
                original_is_source = isinstance(node, SourceNode)
                shared = self.manifest.runtime.memory.shared_pool
                output_shared = self.manifest.runtime.memory.process_output_pool
                proxy_cls = ProcessSourceProxy if original_is_source else ProcessNodeProxy
                node = proxy_cls(
                    name=name,
                    uses=binding.uses,
                    base_dir=self.base_dir,
                    parameters=dict(
                        binding.parameters
                    ),
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
                    failure_policy=binding.failure_policy,
                    max_restarts=binding.failure_max_restarts,
                    backoff_ms=binding.failure_backoff_ms,
                    cpu_affinity=list(
                        binding.cpu_affinity
                    ),
                    device=binding.device,
                    max_message_bytes=binding.max_message_bytes,
                    memory_limit_mb=binding.memory_limit_mb,
                    cpu_limit=binding.cpu_limit,
                )
            self.nodes[name] = LoadedNode(
                name=name,
                node=node,
                binding=binding,
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
            source_memory_map = {**dict(getattr(source, "output_memory", {})), **dict(self.nodes[src_name].binding.memory_outputs)}
            target_memory_map = {**dict(getattr(target, "input_memory", {})), **dict(self.nodes[dst_name].binding.memory_inputs)}
            source_requirement = requirement_for_port(source_memory_map, src_port)
            target_requirement = requirement_for_port(target_memory_map, dst_port)
            if self.nodes[src_name].binding.isolation == "process":
                source_requirement = MemoryRequirement(("shared",), preferred="shared")
            if self.nodes[dst_name].binding.isolation == "process":
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
                and self.nodes[dst_name].binding.isolation != "process"
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
                    "isolation": loaded.binding.isolation,
                    "failure": {
                        "policy": loaded.binding.failure_policy,
                        "max_restarts": loaded.binding.failure_max_restarts,
                        "backoff_ms": loaded.binding.failure_backoff_ms,
                        "fallback_uses": loaded.binding.fallback_uses,
                    },
                    "health": {
                        "timeout_ms": (
                            loaded.binding.health_timeout_ns
                            // 1_000_000
                        ),
                        "on_timeout": loaded.binding.health_on_timeout,
                    },
                    "resources": {
                        "memory_limit_mb": loaded.binding.memory_limit_mb,
                        "cpu_limit": loaded.binding.cpu_limit,
                        "max_message_bytes": loaded.binding.max_message_bytes,
                    },
                    "lifecycle": loaded.node.lifecycle_state,
                    "inputs": loaded.node.input_types,
                    "optional_inputs": sorted(getattr(loaded.node, "optional_inputs", ())),
                    "outputs": loaded.node.output_types,
                    "input_memory": {**dict(getattr(loaded.node, "input_memory", {})), **dict(loaded.binding.memory_inputs)},
                    "output_memory": {**dict(getattr(loaded.node, "output_memory", {})), **dict(loaded.binding.memory_outputs)},
                    "device": loaded.binding.device,
                    "synchronization": {
                        "policy": loaded.binding.synchronization_policy,
                        "tolerance_ms": (
                            loaded.binding.synchronization_tolerance_ns
                            / 1_000_000.0
                        ),
                        "trigger_port": (
                            loaded.binding.synchronization_trigger_port
                        ),
                        "optional_inputs": list(
                            loaded.binding.synchronization_optional_inputs
                        ),
                    },
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
