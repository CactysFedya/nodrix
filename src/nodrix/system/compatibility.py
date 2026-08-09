"""Compatibility lowering from the 2.x PipelineManifest to SystemModel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..manifest import PipelineManifest
from .graph import Connection, Graph, SystemLink
from .instances import ApplicationInstance, ResourceInstance, Target
from .model import SystemModel


@dataclass(frozen=True, slots=True)
class CompatibilityWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    system: SystemModel
    warnings: tuple[CompatibilityWarning, ...] = ()


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True, mode="json")
    return value


def _legacy_endpoint(
    value: str,
    *,
    node_names: set[str],
    graph_name: str,
) -> str:
    instance, separator, port = value.partition(".")
    if not separator:
        return value
    if instance in node_names:
        return f"{graph_name}/{instance}.{port}"
    return value


def pipeline_manifest_to_system(
    manifest: PipelineManifest,
    *,
    graph_name: str = "main",
) -> CompatibilityResult:
    """Convert one legacy PipelineManifest into a SystemModel.

    The conversion is intentionally structural rather than executable. Runtime,
    memory, queue, failure, stream and security details are retained in
    ``extensions`` for the future planner compatibility layer.
    """

    warnings: list[CompatibilityWarning] = []

    resources: list[ResourceInstance] = []
    for name, session in manifest.sessions.items():
        resources.append(
            ResourceInstance(
                name=name,
                uses=session.uses,
                parameters=dict(session.parameters),
                extensions={"legacy_role": "session"},
            )
        )
    for name, resource in manifest.resources.items():
        resources.append(
            ResourceInstance(
                name=name,
                uses=resource.uses,
                parameters=dict(resource.parameters),
                bindings=dict(resource.bindings),
                extensions={"legacy_role": "resource"},
            )
        )

    target_names = {
        manifest.placement.default,
        *manifest.placement.nodes.values(),
        *(
            node.placement
            for node in manifest.nodes.values()
            if node.placement is not None
        ),
    }
    targets = tuple(
        Target(
            name=name,
            kind="placement",
            properties={"legacy": True},
        )
        for name in sorted(name for name in target_names if name)
    )

    nodes = []
    for name, node in manifest.nodes.items():
        target = (
            node.placement
            or manifest.placement.nodes.get(name)
            or manifest.placement.default
        )
        nodes.append(
            {
                "name": name,
                "uses": node.uses,
                "parameters": dict(node.parameters),
                "resources": dict(node.bindings),
                "target": target,
                "extensions": {
                    "legacy": {
                        "inputs": dict(node.inputs),
                        "outputs": dict(node.outputs),
                        "synchronization": _dump(node.synchronization),
                        "execution": _dump(node.execution),
                        "failure": _dump(node.failure),
                        "health": _dump(node.health),
                        "resource_limits": _dump(node.resources),
                        "memory": _dump(node.memory),
                    }
                },
            }
        )

    node_names = set(manifest.nodes)
    local_connections: list[Connection] = []
    links: list[SystemLink] = []

    for edge in manifest.edges:
        if edge.transport is None:
            local_connections.append(
                Connection(
                    **{
                        "from": edge.source,
                        "to": edge.target,
                        "extensions": {
                            "legacy": {
                                "queue": _dump(edge.queue),
                                "memory": _dump(edge.memory),
                            }
                        },
                    }
                )
            )
            continue

        links.append(
            SystemLink(
                **{
                    "from": _legacy_endpoint(
                        edge.source,
                        node_names=node_names,
                        graph_name=graph_name,
                    ),
                    "to": _legacy_endpoint(
                        edge.target,
                        node_names=node_names,
                        graph_name=graph_name,
                    ),
                    "uses": edge.transport.uses,
                    "parameters": dict(edge.transport.parameters),
                    "extensions": {
                        "legacy": {
                            "queue": _dump(edge.queue),
                            "memory": _dump(edge.memory),
                            "source": "transport_edge",
                        }
                    },
                }
            )
        )

    for link in manifest.links:
        links.append(
            SystemLink(
                **{
                    "from": _legacy_endpoint(
                        link.source,
                        node_names=node_names,
                        graph_name=graph_name,
                    ),
                    "to": _legacy_endpoint(
                        link.target,
                        node_names=node_names,
                        graph_name=graph_name,
                    ),
                    "uses": link.uses,
                    "parameters": dict(link.parameters),
                    "extensions": {"legacy": {"source": "external_link"}},
                }
            )
        )

    applications = tuple(
        ApplicationInstance(
            name=name,
            uses=application.uses,
            parameters=dict(application.parameters),
            resources=dict(application.bindings),
            target=manifest.placement.default,
        )
        for name, application in manifest.applications.items()
    )

    if manifest.fragments:
        warnings.append(
            CompatibilityWarning(
                "COMPAT201",
                "legacy fragments are retained in SystemModel.extensions and are "
                "not yet promoted to reusable Graph definitions",
            )
        )
    if manifest.streams.exports:
        warnings.append(
            CompatibilityWarning(
                "COMPAT202",
                "legacy stream exports are retained in SystemModel.extensions and "
                "are not yet canonical System links/artifacts",
            )
        )
    if manifest.recording.enabled:
        warnings.append(
            CompatibilityWarning(
                "COMPAT203",
                "legacy recording policy is retained in SystemModel.extensions; "
                "first-class recording policy belongs to a later operations layer",
            )
        )

    system = SystemModel(
        name=manifest.metadata.name,
        description=manifest.metadata.description,
        resources=tuple(resources),
        applications=applications,
        graphs=(
            Graph(
                name=graph_name,
                nodes=tuple(nodes),
                connections=tuple(local_connections),
            ),
        ),
        links=tuple(links),
        targets=targets,
        extensions={
            "legacy_pipeline": {
                "apiVersion": manifest.api_version,
                "runtime": _dump(manifest.runtime),
                "streams": _dump(manifest.streams),
                "fragments": {
                    name: _dump(fragment)
                    for name, fragment in manifest.fragments.items()
                },
                "recording": _dump(manifest.recording),
                "security": _dump(manifest.security),
                "placement": _dump(manifest.placement),
            }
        },
    )
    return CompatibilityResult(system=system, warnings=tuple(warnings))


__all__ = [
    "CompatibilityResult",
    "CompatibilityWarning",
    "pipeline_manifest_to_system",
]
