"""Semantic validation for backend-neutral SystemModel objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from ..sdk.definitions import NodeDefinition, ParameterDefinition, ResourceDefinition
from .catalog import DefinitionCatalog
from .graph import Graph, split_local_endpoint, split_system_endpoint
from .instances import NodeInstance, ResourceInstance
from .model import SystemModel


@dataclass(frozen=True, slots=True)
class SystemDiagnostic:
    level: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class SystemValidationReport:
    diagnostics: tuple[SystemDiagnostic, ...] = ()

    @property
    def errors(self) -> tuple[SystemDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.level == "error")

    @property
    def warnings(self) -> tuple[SystemDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.level == "warning")

    @property
    def valid(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise SystemValidationError(self)


class SystemValidationError(ValueError):
    def __init__(self, report: SystemValidationReport):
        self.report = report
        summary = "; ".join(
            f"{item.code} {item.path}: {item.message}" for item in report.errors
        )
        super().__init__(summary or "System validation failed")


def _duplicate_names(items: Iterable[object]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        name = str(getattr(item, "name"))
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    return duplicates


def _validate_parameters(
    *,
    path: str,
    values: Mapping[str, object],
    definitions: tuple[ParameterDefinition, ...],
    diagnostics: list[SystemDiagnostic],
) -> None:
    known = {item.name: item for item in definitions}
    for name in sorted(set(values) - set(known)):
        diagnostics.append(
            SystemDiagnostic(
                "error",
                "SYS121",
                f"{path}.parameters.{name}",
                "parameter is not declared by the referenced definition",
            )
        )
    for name, definition in known.items():
        if definition.required and name not in values:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS122",
                    f"{path}.parameters.{name}",
                    "required parameter is not configured",
                )
            )


def _node_resource_slots(definition: NodeDefinition) -> set[str]:
    return {
        item.name
        for item in definition.dependencies
        if item.kind == "resource"
    }


def _validate_node_definition(
    *,
    node: NodeInstance,
    path: str,
    definition: NodeDefinition,
    known_resources: set[str],
    diagnostics: list[SystemDiagnostic],
) -> None:
    _validate_parameters(
        path=path,
        values=node.parameters,
        definitions=definition.parameters,
        diagnostics=diagnostics,
    )

    slots = _node_resource_slots(definition)
    unknown_slots = sorted(set(node.resources) - slots)
    for slot in unknown_slots:
        diagnostics.append(
            SystemDiagnostic(
                "error",
                "SYS123",
                f"{path}.resources.{slot}",
                "resource slot is not declared by the referenced NodeDefinition",
            )
        )

    for slot in sorted(slots - set(node.resources)):
        diagnostics.append(
            SystemDiagnostic(
                "error",
                "SYS124",
                f"{path}.resources.{slot}",
                "required Resource[T] slot is not bound",
            )
        )

    for slot, resource_name in node.resources.items():
        if resource_name not in known_resources:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS125",
                    f"{path}.resources.{slot}",
                    f"unknown ResourceInstance {resource_name!r}",
                )
            )


def _validate_resource_definition(
    *,
    resource: ResourceInstance,
    path: str,
    definition: ResourceDefinition,
    diagnostics: list[SystemDiagnostic],
) -> None:
    _validate_parameters(
        path=path,
        values=resource.parameters,
        definitions=definition.parameters,
        diagnostics=diagnostics,
    )


def _definition_port(
    definition: NodeDefinition,
    name: str,
    *,
    output: bool,
):
    collection = definition.outputs if output else definition.inputs
    return next((item for item in collection if item.name == name), None)


def validate_system(
    system: SystemModel,
    *,
    catalog: DefinitionCatalog | None = None,
) -> SystemValidationReport:
    diagnostics: list[SystemDiagnostic] = []

    categories = {
        "resources": system.resources,
        "applications": system.applications,
        "graphs": system.graphs,
        "targets": system.targets,
        "artifacts": system.artifacts,
    }
    for category, items in categories.items():
        for duplicate in sorted(_duplicate_names(items)):
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS001",
                    f"{category}.{duplicate}",
                    f"duplicate {category[:-1]} name",
                )
            )

    target_names = {item.name for item in system.targets}
    resource_names = {item.name for item in system.resources}
    application_names = {item.name for item in system.applications}
    graph_names = {item.name for item in system.graphs}

    def validate_target(path: str, target: str | None) -> None:
        if target is not None and target not in target_names:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS011",
                    f"{path}.target",
                    f"unknown Target {target!r}",
                )
            )

    for index, resource in enumerate(system.resources):
        path = f"resources[{index}]"
        validate_target(path, resource.target)
        for slot, bound in resource.bindings.items():
            if bound not in resource_names:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS012",
                        f"{path}.bindings.{slot}",
                        f"unknown ResourceInstance {bound!r}",
                    )
                )
        if catalog is not None:
            definition = catalog.resources.get(resource.uses)
            if definition is None:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS101",
                        f"{path}.uses",
                        f"unknown ResourceDefinition {resource.uses!r}",
                    )
                )
            else:
                _validate_resource_definition(
                    resource=resource,
                    path=path,
                    definition=definition,
                    diagnostics=diagnostics,
                )

    for index, application in enumerate(system.applications):
        path = f"applications[{index}]"
        validate_target(path, application.target)
        for slot, bound in application.resources.items():
            if bound not in resource_names:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS013",
                        f"{path}.resources.{slot}",
                        f"unknown ResourceInstance {bound!r}",
                    )
                )

    graph_node_maps: dict[str, dict[str, NodeInstance]] = {}
    for graph_index, graph in enumerate(system.graphs):
        graph_path = f"graphs[{graph_index}]"
        duplicates = _duplicate_names(graph.nodes)
        for duplicate in sorted(duplicates):
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS021",
                    f"{graph_path}.nodes.{duplicate}",
                    "duplicate NodeInstance name inside Graph",
                )
            )
        node_map = {node.name: node for node in graph.nodes}
        graph_node_maps[graph.name] = node_map

        for node_index, node in enumerate(graph.nodes):
            path = f"{graph_path}.nodes[{node_index}]"
            validate_target(path, node.target)
            for slot, bound in node.resources.items():
                if bound not in resource_names:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS022",
                            f"{path}.resources.{slot}",
                            f"unknown ResourceInstance {bound!r}",
                        )
                    )

            if catalog is not None:
                definition = catalog.nodes.get(node.uses)
                if definition is None:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS102",
                            f"{path}.uses",
                            f"unknown NodeDefinition {node.uses!r}",
                        )
                    )
                else:
                    _validate_node_definition(
                        node=node,
                        path=path,
                        definition=definition,
                        known_resources=resource_names,
                        diagnostics=diagnostics,
                    )

        for connection_index, connection in enumerate(graph.connections):
            path = f"{graph_path}.connections[{connection_index}]"
            source_name, source_port = split_local_endpoint(connection.source)
            target_name, target_port = split_local_endpoint(connection.target)
            source_node = node_map.get(source_name)
            target_node = node_map.get(target_name)

            if source_node is None:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS031",
                        f"{path}.from",
                        f"unknown source NodeInstance {source_name!r}",
                    )
                )
            if target_node is None:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS032",
                        f"{path}.to",
                        f"unknown target NodeInstance {target_name!r}",
                    )
                )

            if (
                catalog is not None
                and source_node is not None
                and target_node is not None
            ):
                source_definition = catalog.nodes.get(source_node.uses)
                target_definition = catalog.nodes.get(target_node.uses)
                if source_definition is None or target_definition is None:
                    continue

                source_contract = _definition_port(
                    source_definition, source_port, output=True
                )
                target_contract = _definition_port(
                    target_definition, target_port, output=False
                )

                if source_contract is None:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS131",
                            f"{path}.from",
                            f"NodeDefinition has no output port {source_port!r}",
                        )
                    )
                    continue
                if target_contract is None:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS132",
                            f"{path}.to",
                            f"NodeDefinition has no input port {target_port!r}",
                        )
                    )
                    continue

                if source_contract.type_id != target_contract.type_id:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS133",
                            path,
                            "message contract mismatch: "
                            f"{source_contract.type_id!r} -> {target_contract.type_id!r}",
                        )
                    )
                if (
                    connection.type_id is not None
                    and connection.type_id != source_contract.type_id
                ):
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS134",
                            f"{path}.type_id",
                            "explicit connection type does not match source definition",
                        )
                    )

    def resolve_system_endpoint(path: str, value: str) -> None:
        graph_name, instance_name, _ = split_system_endpoint(value)
        if graph_name is None:
            if instance_name not in application_names:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS041",
                        path,
                        f"unknown ApplicationInstance {instance_name!r}",
                    )
                )
            return

        if graph_name not in graph_names:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS042",
                    path,
                    f"unknown Graph {graph_name!r}",
                )
            )
            return
        if instance_name not in graph_node_maps.get(graph_name, {}):
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS043",
                    path,
                    f"unknown NodeInstance {instance_name!r} in Graph {graph_name!r}",
                )
            )

    for index, link in enumerate(system.links):
        resolve_system_endpoint(f"links[{index}].from", link.source)
        resolve_system_endpoint(f"links[{index}].to", link.target)

    for index, artifact in enumerate(system.artifacts):
        if artifact.producer is not None:
            resolve_system_endpoint(f"artifacts[{index}].producer", artifact.producer)

    return SystemValidationReport(tuple(diagnostics))


__all__ = [
    "SystemDiagnostic",
    "SystemValidationError",
    "SystemValidationReport",
    "validate_system",
]
