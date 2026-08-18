"""Semantic validation for backend-neutral SystemModel objects."""

from __future__ import annotations

from dataclasses import dataclass
from types import UnionType
from typing import (
    Annotated,
    Any,
    Callable,
    Iterable,
    Literal,
    Mapping,
    Union,
    get_args,
    get_origin,
)

from ..model import RevisionRef
from ..sdk.definitions import (
    DependencyDefinition,
    NodeDefinition,
    ParameterDefinition,
    ResourceDefinition,
)
from .catalog import DefinitionCatalog
from .contracts import (
    SystemParameter,
    SystemParameterTargetKind,
    SystemParameterType,
    parse_system_parameter_target,
)
from .graph import (
    SystemEndpointKind,
    parse_system_endpoint,
    split_local_endpoint,
)
from .instances import NodeInstance, ResourceInstance
from .model import SystemModel


SystemValidationResolver = Callable[
    [RevisionRef],
    SystemModel | None,
]


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
    bound: set[str] | frozenset[str] = frozenset(),
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
        if (
            definition.required
            and name not in values
            and name not in bound
        ):
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS122",
                    f"{path}.parameters.{name}",
                    "required parameter is not configured",
                )
            )


def _node_resource_dependencies(
    definition: NodeDefinition,
) -> dict[str, DependencyDefinition]:
    return {
        item.name: item
        for item in definition.dependencies
        if item.kind == "resource"
    }


def _type_name(annotation: Any) -> str:
    if annotation is Any:
        return "Any"
    name = getattr(annotation, "__qualname__", None) or getattr(annotation, "__name__", None)
    if name:
        module = getattr(annotation, "__module__", "")
        return f"{module}.{name}" if module not in {"", "builtins"} else str(name)
    return str(annotation)


def _resource_type_compatible(required: Any, provided: Any) -> bool:
    """Return whether a resource exposing ``provided`` can satisfy ``required``."""

    if required in (Any, object) or provided is Any:
        return True
    if required == provided:
        return True

    required_origin = get_origin(required)
    provided_origin = get_origin(provided)

    if required_origin in (Union, UnionType):
        return any(
            _resource_type_compatible(option, provided)
            for option in get_args(required)
            if option is not type(None)
        )

    required_runtime = required_origin or required
    provided_runtime = provided_origin or provided

    try:
        if isinstance(required_runtime, type) and isinstance(provided_runtime, type):
            return issubclass(provided_runtime, required_runtime)
    except TypeError:
        pass

    return required_runtime == provided_runtime


def _annotation_accepts_runtime_type(
    annotation: Any,
    runtime_type: type[Any],
) -> bool | None:
    """Return whether an SDK annotation accepts a portable runtime category."""

    if annotation in (Any, object):
        return True
    origin = get_origin(annotation)
    if origin is Annotated:
        arguments = get_args(annotation)
        return (
            _annotation_accepts_runtime_type(arguments[0], runtime_type)
            if arguments
            else None
        )
    if origin in (Union, UnionType):
        results = tuple(
            _annotation_accepts_runtime_type(option, runtime_type)
            for option in get_args(annotation)
        )
        if True in results:
            return True
        return None if None in results else False
    if origin is Literal:
        return False

    target = origin or annotation
    if target is float and runtime_type is int:
        return True
    if runtime_type is bool and target is int:
        return False
    try:
        if isinstance(target, type):
            return issubclass(runtime_type, target)
    except TypeError:
        return None
    return None


def _system_parameter_type_compatible(
    contract: SystemParameter,
    annotation: Any,
) -> bool | None:
    """Check that every value allowed by a System contract fits an SDK target."""

    if contract.value_type is SystemParameterType.ANY:
        return True if annotation in (Any, object) else False

    runtime_types: dict[
        SystemParameterType,
        tuple[type[Any], ...],
    ] = {
        SystemParameterType.STRING: (str,),
        SystemParameterType.INTEGER: (int,),
        SystemParameterType.NUMBER: (int, float),
        SystemParameterType.BOOLEAN: (bool,),
        SystemParameterType.OBJECT: (dict,),
        SystemParameterType.ARRAY: (list,),
    }
    results = tuple(
        _annotation_accepts_runtime_type(annotation, runtime_type)
        for runtime_type in runtime_types[contract.value_type]
    )
    if False in results:
        return False
    if None in results:
        return None

    if contract.nullable:
        nullable = _annotation_accepts_runtime_type(
            annotation,
            type(None),
        )
        if nullable is not True:
            return nullable
    return True


def _system_parameter_contract_compatible(
    source: SystemParameter,
    target: SystemParameter,
) -> bool:
    """Return whether every portable source value is accepted by a child."""

    if source.nullable and not target.nullable:
        return False
    if target.value_type is SystemParameterType.ANY:
        return True
    if source.value_type is SystemParameterType.ANY:
        return False
    if source.value_type is target.value_type:
        return True
    return (
        source.value_type is SystemParameterType.INTEGER
        and target.value_type is SystemParameterType.NUMBER
    )


def _message_contract_version(type_id: str) -> tuple[str, int] | None:
    stem, marker, version = type_id.rpartition("/v")
    if not marker or not stem:
        return None
    try:
        return stem, int(version)
    except ValueError:
        return None


def _message_contracts_compatible(
    source_type: str,
    target_type: str,
    *,
    catalog: DefinitionCatalog | None,
) -> bool:
    if source_type == target_type:
        return True
    if catalog is None:
        return False

    source_version = _message_contract_version(source_type)
    target_version = _message_contract_version(target_type)
    if source_version is None or target_version is None:
        return False
    source_stem, source_number = source_version
    target_stem, _ = target_version
    if source_stem != target_stem:
        return False

    target_definition = catalog.messages.get(target_type)
    if target_definition is None:
        return False
    return source_number in target_definition.compatible_versions


def _validate_node_definition(
    *,
    node: NodeInstance,
    path: str,
    definition: NodeDefinition,
    resources: Mapping[str, ResourceInstance],
    catalog: DefinitionCatalog,
    diagnostics: list[SystemDiagnostic],
    bound_parameters: set[str] | frozenset[str] = frozenset(),
) -> None:
    _validate_parameters(
        path=path,
        values=node.parameters,
        definitions=definition.parameters,
        diagnostics=diagnostics,
        bound=bound_parameters,
    )

    dependencies = _node_resource_dependencies(definition)
    slots = set(dependencies)
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
        resource_instance = resources.get(resource_name)
        if resource_instance is None:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS125",
                    f"{path}.resources.{slot}",
                    f"unknown ResourceInstance {resource_name!r}",
                )
            )
            continue

        dependency = dependencies.get(slot)
        if dependency is None:
            continue

        resource_definition = catalog.resources.get(resource_instance.uses)
        if resource_definition is None:
            # SYS101 is reported at the ResourceInstance itself.
            continue

        provided_type = resource_definition.provided_type
        if provided_type is None:
            diagnostics.append(
                SystemDiagnostic(
                    "warning",
                    "SYS126",
                    f"{path}.resources.{slot}",
                    f"ResourceDefinition {resource_instance.uses!r} does not declare "
                    "its provided Python type; use a return annotation or "
                    "@resource(provides=...) to enable type validation",
                )
            )
            continue

        if not _resource_type_compatible(dependency.annotation, provided_type):
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS127",
                    f"{path}.resources.{slot}",
                    "resource type mismatch: "
                    f"node requires {_type_name(dependency.annotation)}, "
                    f"{resource_instance.uses!r} provides {_type_name(provided_type)}",
                )
            )


def _validate_resource_definition(
    *,
    resource: ResourceInstance,
    path: str,
    definition: ResourceDefinition,
    diagnostics: list[SystemDiagnostic],
    bound_parameters: set[str] | frozenset[str] = frozenset(),
) -> None:
    _validate_parameters(
        path=path,
        values=resource.parameters,
        definitions=definition.parameters,
        diagnostics=diagnostics,
        bound=bound_parameters,
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
    system_resolver: SystemValidationResolver | None = None,
) -> SystemValidationReport:
    diagnostics: list[SystemDiagnostic] = []

    categories = {
        "inputs": system.inputs,
        "outputs": system.outputs,
        "parameters": system.parameters,
        "resourceRequirements": (
            system.resource_requirements
        ),
        "systems": system.systems,
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
    system_names = {item.name for item in system.systems}
    resource_names = {item.name for item in system.resources}
    resource_map = {item.name: item for item in system.resources}
    application_names = {item.name for item in system.applications}
    graph_names = {item.name for item in system.graphs}
    input_ports = {
        item.name: item
        for item in system.inputs
    }
    output_ports = {
        item.name: item
        for item in system.outputs
    }
    resource_requirements = {
        item.name: item
        for item in system.resource_requirements
    }
    system_parameters = {
        item.name: item
        for item in system.parameters
    }
    system_parameter_names = set(system_parameters)
    parameter_target_bindings: dict[
        tuple[str, str | None, str],
        set[str],
    ] = {}
    seen_parameter_bindings: set[str] = set()
    seen_parameter_targets: set[str] = set()

    for index, binding in enumerate(
        system.bindings.parameters
    ):
        path = f"bindings.parameters[{index}]"
        if binding.parameter in seen_parameter_bindings:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS058",
                    f"{path}.parameter",
                    f"duplicate binding for System parameter "
                    f"{binding.parameter!r}",
                )
            )
        seen_parameter_bindings.add(binding.parameter)

        if binding.parameter not in system_parameter_names:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS059",
                    f"{path}.parameter",
                    f"unknown System parameter {binding.parameter!r}",
                )
            )

        for target_index, raw_target in enumerate(binding.targets):
            if raw_target in seen_parameter_targets:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS060",
                        f"{path}.targets[{target_index}]",
                        "internal parameter target is bound more than once: "
                        f"{raw_target!r}",
                    )
                )
            seen_parameter_targets.add(raw_target)
            target = parse_system_parameter_target(raw_target)
            key = (
                target.kind.value,
                target.scope,
                target.instance,
            )
            parameter_target_bindings.setdefault(
                key,
                set(),
            ).add(target.parameter)

    child_definitions: dict[str, SystemModel] = {}

    for index, instance in enumerate(system.systems):
        path = f"systems[{index}]"

        for slot, resource_name in instance.resources.items():
            if resource_name not in resource_names:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS065",
                        f"{path}.resources.{slot}",
                        f"unknown parent ResourceInstance {resource_name!r}",
                    )
                )

        if system_resolver is None:
            continue

        child = system_resolver(instance.revision)
        if child is None or not isinstance(child, SystemModel):
            continue

        child_definitions[instance.name] = child
        child_parameters = {
            item.name: item
            for item in child.parameters
        }
        child_resources = {
            item.name: item
            for item in child.resource_requirements
        }
        bound_child_parameters = parameter_target_bindings.get(
            (
                SystemParameterTargetKind.SYSTEM.value,
                None,
                instance.name,
            ),
            set(),
        )

        for name in sorted(
            set(instance.parameters) - set(child_parameters)
        ):
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS171",
                    f"{path}.parameters.{name}",
                    "parameter is not declared by the child System Definition",
                )
            )

        for name, contract in child_parameters.items():
            if (
                contract.required
                and name not in instance.parameters
                and name not in bound_child_parameters
            ):
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS172",
                        f"{path}.parameters.{name}",
                        "required child System parameter is not configured",
                    )
                )
            if (
                name in instance.parameters
                and not contract.accepts(
                    instance.parameters[name]
                )
            ):
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS173",
                        f"{path}.parameters.{name}",
                        "child System parameter does not match declared type "
                        f"{contract.value_type.value!r}",
                    )
                )

        for name in sorted(
            set(instance.resources) - set(child_resources)
        ):
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS174",
                    f"{path}.resources.{name}",
                    "resource slot is not declared by the child System Definition",
                )
            )

        for name, requirement in child_resources.items():
            if not requirement.optional and name not in instance.resources:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS175",
                        f"{path}.resources.{name}",
                        "required child System resource is not bound",
                    )
                )
                continue

            parent_name = instance.resources.get(name)
            parent_resource = resource_map.get(parent_name or "")
            if (
                parent_resource is not None
                and parent_resource.uses != requirement.uses
            ):
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS176",
                        f"{path}.resources.{name}",
                        "bound parent ResourceInstance has incompatible "
                        f"definition {parent_resource.uses!r}; expected "
                        f"{requirement.uses!r}",
                    )
                )

    dependency_edges: set[tuple[str, str]] = set()

    for index, dependency in enumerate(
        system.dependencies
    ):
        path = f"dependencies[{index}]"
        edge = (
            dependency.system,
            dependency.requires,
        )

        if dependency.system not in system_names:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS061",
                    f"{path}.system",
                    "dependency target must name a sibling SystemInstance: "
                    f"unknown SystemInstance {dependency.system!r}",
                )
            )

        if dependency.requires not in system_names:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS062",
                    f"{path}.requires",
                    "dependency prerequisite must name a sibling "
                    f"SystemInstance: unknown SystemInstance "
                    f"{dependency.requires!r}",
                )
            )

        if dependency.system == dependency.requires:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS063",
                    path,
                    "SystemInstance cannot depend on itself",
                )
            )

        if edge in dependency_edges:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS064",
                    path,
                    "duplicate System dependency edge: "
                    f"{dependency.system!r} requires "
                    f"{dependency.requires!r}",
                )
            )

        dependency_edges.add(edge)
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
                    bound_parameters=(
                        parameter_target_bindings.get(
                            (
                                SystemParameterTargetKind.RESOURCE.value,
                                None,
                                resource.name,
                            ),
                            set(),
                        )
                    ),
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
                        resources=resource_map,
                        catalog=catalog,
                        diagnostics=diagnostics,
                        bound_parameters=(
                            parameter_target_bindings.get(
                                (
                                    SystemParameterTargetKind.NODE.value,
                                    graph.name,
                                    node.name,
                                ),
                                set(),
                            )
                        ),
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

                if not _message_contracts_compatible(
                    source_contract.type_id,
                    target_contract.type_id,
                    catalog=catalog,
                ):
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

    for binding_index, binding in enumerate(
        system.bindings.parameters
    ):
        for target_index, raw_target in enumerate(binding.targets):
            path = (
                f"bindings.parameters[{binding_index}]"
                f".targets[{target_index}]"
            )
            target = parse_system_parameter_target(raw_target)

            if target.kind is SystemParameterTargetKind.SYSTEM:
                child_instance = next(
                    (
                        item
                        for item in system.systems
                        if item.name == target.instance
                    ),
                    None,
                )
                if child_instance is None:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS075",
                            path,
                            f"unknown SystemInstance {target.instance!r}",
                        )
                    )
                    continue
                if target.parameter in child_instance.parameters:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS178",
                            path,
                            "bound parameter target also has an explicit "
                            "instance value",
                        )
                    )
                child_definition = child_definitions.get(
                    target.instance
                )
                if child_definition is None:
                    continue
                child_parameter = next(
                    (
                        item
                        for item in child_definition.parameters
                        if item.name == target.parameter
                    ),
                    None,
                )
                if child_parameter is None:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS177",
                            path,
                            "child System Definition has no parameter "
                            f"{target.parameter!r}",
                        )
                    )
                    continue
                system_parameter = system_parameters.get(
                    binding.parameter
                )
                if (
                    system_parameter is not None
                    and not _system_parameter_contract_compatible(
                        system_parameter,
                        child_parameter,
                    )
                ):
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS179",
                            path,
                            "System parameter type "
                            f"{system_parameter.value_type.value!r} is not "
                            "accepted by child System parameter type "
                            f"{child_parameter.value_type.value!r}",
                        )
                    )
                continue

            if target.kind is SystemParameterTargetKind.APPLICATION:
                application = next(
                    (
                        item
                        for item in system.applications
                        if item.name == target.instance
                    ),
                    None,
                )
                if application is None:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS071",
                            path,
                            f"unknown ApplicationInstance {target.instance!r}",
                        )
                    )
                elif target.parameter in application.parameters:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS178",
                            path,
                            "bound parameter target also has an explicit "
                            "instance value",
                        )
                    )
                continue

            if target.kind is SystemParameterTargetKind.RESOURCE:
                resource = resource_map.get(target.instance)
                if resource is None:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS072",
                            path,
                            f"unknown ResourceInstance {target.instance!r}",
                        )
                    )
                    continue
                if target.parameter in resource.parameters:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS178",
                            path,
                            "bound parameter target also has an explicit "
                            "instance value",
                        )
                    )
                definition = (
                    catalog.resources.get(resource.uses)
                    if catalog is not None
                    else None
                )
            else:
                graph_name = target.scope
                if graph_name not in graph_names:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS073",
                            path,
                            f"unknown Graph {graph_name!r}",
                        )
                    )
                    continue
                node = graph_node_maps.get(
                    graph_name or "",
                    {},
                ).get(target.instance)
                if node is None:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS074",
                            path,
                            f"unknown NodeInstance {target.instance!r} "
                            f"in Graph {graph_name!r}",
                        )
                    )
                    continue
                if target.parameter in node.parameters:
                    diagnostics.append(
                        SystemDiagnostic(
                            "error",
                            "SYS178",
                            path,
                            "bound parameter target also has an explicit "
                            "instance value",
                        )
                    )
                definition = (
                    catalog.nodes.get(node.uses)
                    if catalog is not None
                    else None
                )

            if definition is None:
                continue
            definition_parameter = next(
                (
                    item
                    for item in definition.parameters
                    if item.name == target.parameter
                ),
                None,
            )
            if definition_parameter is None:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS177",
                        path,
                        f"referenced definition has no parameter "
                        f"{target.parameter!r}",
                    )
                )
                continue

            system_parameter = system_parameters.get(
                binding.parameter
            )
            if system_parameter is None:
                continue
            compatible = _system_parameter_type_compatible(
                system_parameter,
                definition_parameter.annotation,
            )
            if compatible is False:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS179",
                        path,
                        "System parameter type "
                        f"{system_parameter.value_type.value!r} is not "
                        "accepted by SDK parameter annotation "
                        f"{_type_name(definition_parameter.annotation)}",
                    )
                )
            elif compatible is None:
                diagnostics.append(
                    SystemDiagnostic(
                        "warning",
                        "SYS180",
                        path,
                        "SDK parameter annotation could not be verified "
                        "against the portable System parameter type",
                    )
                )

    def resolve_system_endpoint(
        path: str,
        value: str,
        *,
        direction: str,
        missing_port_code: str,
    ) -> tuple[str, str | None]:
        endpoint = parse_system_endpoint(value)
        instance_name = endpoint.instance
        port_name = endpoint.port

        if endpoint.kind is SystemEndpointKind.APPLICATION:
            if instance_name not in application_names:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS041",
                        path,
                        f"unknown ApplicationInstance {instance_name!r}",
                    )
                )
                return "invalid", None
            return "application", None

        if endpoint.kind is SystemEndpointKind.SYSTEM:
            if instance_name not in system_names:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS044",
                        path,
                        f"unknown child SystemInstance {instance_name!r}",
                    )
                )
                return "invalid", None

            child = child_definitions.get(instance_name)
            if child is None:
                return "system", None

            is_source = direction == "source"
            ports = child.outputs if is_source else child.inputs
            port = next(
                (
                    item
                    for item in ports
                    if item.name == port_name
                ),
                None,
            )
            if port is None:
                expected = "output" if is_source else "input"
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        missing_port_code,
                        path,
                        f"child System Definition {child.name!r} has no "
                        f"{expected} port {port_name!r}",
                    )
                )
                return "system", None

            return "system", port.type_id

        graph_name = endpoint.scope
        assert graph_name is not None

        if graph_name not in graph_names:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS042",
                    path,
                    f"unknown Graph {graph_name!r}",
                )
            )
            return "invalid", None

        node = graph_node_maps.get(graph_name, {}).get(instance_name)
        if node is None:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS043",
                    path,
                    f"unknown NodeInstance {instance_name!r} in Graph {graph_name!r}",
                )
            )
            return "invalid", None

        if catalog is None:
            return "graph", None

        definition = catalog.nodes.get(node.uses)
        if definition is None:
            # SYS102 is reported at the NodeInstance itself.
            return "graph", None

        is_source = direction == "source"
        port = _definition_port(
            definition,
            port_name,
            output=is_source,
        )
        if port is None:
            expected = "output" if is_source else "input"
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    missing_port_code,
                    path,
                    f"NodeDefinition {node.uses!r} has no {expected} port {port_name!r}",
                )
            )
            return "graph", None

        return "graph", port.type_id

    seen_input_bindings: set[str] = set()

    for index, binding in enumerate(
        system.bindings.inputs
    ):
        path = f"bindings.inputs[{index}]"

        if binding.port in seen_input_bindings:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS051",
                    f"{path}.port",
                    f"duplicate binding for System input "
                    f"{binding.port!r}",
                )
            )

        seen_input_bindings.add(
            binding.port
        )

        if binding.port not in input_ports:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS053",
                    f"{path}.port",
                    f"unknown System input port "
                    f"{binding.port!r}",
                )
            )

        # External System input feeds an internal consumer, therefore the
        # internal endpoint must resolve as a target/input endpoint.
        endpoint_kind, endpoint_type = resolve_system_endpoint(
            f"{path}.endpoint",
            binding.endpoint,
            direction="target",
            missing_port_code="SYS151",
        )

        system_port = input_ports.get(
            binding.port
        )

        if system_port is not None:
            if (
                endpoint_type is not None
                and not _message_contracts_compatible(
                    system_port.type_id,
                    endpoint_type,
                    catalog=catalog,
                )
            ):
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS153",
                        path,
                        "System input contract is not accepted by the "
                        "bound internal input: "
                        f"{system_port.type_id!r} -> {endpoint_type!r}",
                    )
                )
            elif endpoint_kind == "application":
                diagnostics.append(
                    SystemDiagnostic(
                        "warning",
                        "SYS155",
                        f"{path}.endpoint",
                        "System input is bound to an ApplicationInstance "
                        "whose input contract is not first-class yet; "
                        "type compatibility cannot be verified",
                    )
                )

    seen_output_bindings: set[str] = set()

    for index, binding in enumerate(
        system.bindings.outputs
    ):
        path = f"bindings.outputs[{index}]"

        if binding.port in seen_output_bindings:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS052",
                    f"{path}.port",
                    f"duplicate binding for System output "
                    f"{binding.port!r}",
                )
            )

        seen_output_bindings.add(
            binding.port
        )

        if binding.port not in output_ports:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS054",
                    f"{path}.port",
                    f"unknown System output port "
                    f"{binding.port!r}",
                )
            )

        # Internal producer feeds the external System output, therefore the
        # internal endpoint must resolve as a source/output endpoint.
        endpoint_kind, endpoint_type = resolve_system_endpoint(
            f"{path}.endpoint",
            binding.endpoint,
            direction="source",
            missing_port_code="SYS152",
        )

        system_port = output_ports.get(
            binding.port
        )

        if system_port is not None:
            if (
                endpoint_type is not None
                and not _message_contracts_compatible(
                    endpoint_type,
                    system_port.type_id,
                    catalog=catalog,
                )
            ):
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS154",
                        path,
                        "bound internal output is not compatible with the "
                        "System output contract: "
                        f"{endpoint_type!r} -> {system_port.type_id!r}",
                    )
                )
            elif endpoint_kind == "application":
                diagnostics.append(
                    SystemDiagnostic(
                        "warning",
                        "SYS156",
                        f"{path}.endpoint",
                        "System output is bound to an ApplicationInstance "
                        "whose output contract is not first-class yet; "
                        "type compatibility cannot be verified",
                    )
                )

    seen_resource_bindings: set[str] = set()

    for index, binding in enumerate(
        system.bindings.resources
    ):
        path = f"bindings.resources[{index}]"

        if binding.resource in seen_resource_bindings:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS055",
                    f"{path}.resource",
                    "duplicate binding for System resource requirement "
                    f"{binding.resource!r}",
                )
            )
        seen_resource_bindings.add(binding.resource)

        requirement = resource_requirements.get(
            binding.resource
        )
        if requirement is None:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS056",
                    f"{path}.resource",
                    "unknown System resource requirement "
                    f"{binding.resource!r}",
                )
            )

        resource = resource_map.get(binding.instance)
        if resource is None:
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS057",
                    f"{path}.instance",
                    f"unknown internal ResourceInstance {binding.instance!r}",
                )
            )
        elif (
            requirement is not None
            and resource.uses != requirement.uses
        ):
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS157",
                    path,
                    "internal ResourceInstance has incompatible definition "
                    f"{resource.uses!r}; expected {requirement.uses!r}",
                )
            )

    for index, link in enumerate(system.links):
        path = f"links[{index}]"
        source_kind, source_type = resolve_system_endpoint(
            f"{path}.from",
            link.source,
            direction="source",
            missing_port_code="SYS141",
        )
        target_kind, target_type = resolve_system_endpoint(
            f"{path}.to",
            link.target,
            direction="target",
            missing_port_code="SYS142",
        )

        if (
            source_type is not None
            and target_type is not None
            and not _message_contracts_compatible(
                source_type,
                target_type,
                catalog=catalog,
            )
        ):
            diagnostics.append(
                SystemDiagnostic(
                    "error",
                    "SYS143",
                    path,
                    "system link message contract mismatch: "
                    f"{source_type!r} -> {target_type!r}",
                )
            )

        if link.type_id is not None:
            if source_type is not None and source_type != link.type_id:
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS144",
                        f"{path}.type_id",
                        "explicit SystemLink type does not match the source output: "
                        f"{link.type_id!r} != {source_type!r}",
                    )
                )
            if (
                target_type is not None
                and not _message_contracts_compatible(
                    link.type_id,
                    target_type,
                    catalog=catalog,
                )
            ):
                diagnostics.append(
                    SystemDiagnostic(
                        "error",
                        "SYS146",
                        f"{path}.type_id",
                        "explicit SystemLink type is not accepted by the target input: "
                        f"{link.type_id!r} -> {target_type!r}",
                    )
                )
        elif "application" in {source_kind, target_kind}:
            diagnostics.append(
                SystemDiagnostic(
                    "warning",
                    "SYS145",
                    path,
                    "application boundary has no explicit type_id; graph-side ports "
                    "are validated, but the application contract cannot be checked "
                    "until application definitions become first-class",
                )
            )

    for index, artifact in enumerate(system.artifacts):
        if artifact.producer is None:
            continue

        path = f"artifacts[{index}].producer"
        producer_kind, _ = resolve_system_endpoint(
            path,
            artifact.producer,
            direction="source",
            missing_port_code="SYS161",
        )
        if producer_kind == "application":
            diagnostics.append(
                SystemDiagnostic(
                    "warning",
                    "SYS162",
                    path,
                    "artifact is produced by an ApplicationInstance whose output "
                    "contract is not yet represented by a first-class definition",
                )
            )

    return SystemValidationReport(tuple(diagnostics))


__all__ = [
    "SystemDiagnostic",
    "SystemValidationError",
    "SystemValidationReport",
    "validate_system",
]
