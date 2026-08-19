"""System-level planning for Nodrix 2.6.

This module deliberately sits above the legacy pipeline ExecutionPlan.  It
resolves the placement and logical execution topology of a whole SystemModel;
backend-specific lowering is a later layer.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Callable, Literal, Mapping

from pydantic import Field

from ..model import RevisionRef

from ._base import SystemBaseModel
from .catalog import DefinitionCatalog
from .contracts import (
    SystemParameterTargetKind,
    parse_system_parameter_target,
)
from .dependencies import (
    SystemDependencyCondition,
)
from .definition import system_definition_digest
from .graph import (
    SystemEndpointKind,
    parse_system_endpoint,
    split_local_endpoint,
)
from .model import SystemModel
from .validation import SystemValidationReport, validate_system
from .execution_context import (
    SystemExecutionContext,
    child_system_execution_context,
    system_execution_context_digest,
)


SYSTEM_EXECUTION_PLAN_SCHEMA = "nodrix.system-execution-plan/v1"


SystemDefinitionResolver = Callable[
    [RevisionRef],
    SystemModel | None,
]


class SystemPlanningError(ValueError):
    """The declarative System is valid, but cannot be resolved into one plan."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        prefix = code if not path else f"{code} {path}"
        super().__init__(f"{prefix}: {message}")


class PlanningDiagnostic(SystemBaseModel):
    level: Literal["warning"] = "warning"
    code: str
    path: str = ""
    message: str
    source: Literal["planner", "system_validation"] = "planner"


class PlannedTarget(SystemBaseModel):
    name: str
    kind: str
    backend: str
    properties: Mapping[str, Any] = Field(default_factory=dict)
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    implicit: bool = False


class PlannedSystemPort(SystemBaseModel):
    """One external typed port copied into an exact execution plan."""

    ordinal: int
    name: str
    type_id: str
    optional: bool
    description: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedSystemParameter(SystemBaseModel):
    """One public System parameter contract and its effective value."""

    ordinal: int
    name: str
    type: str
    required: bool
    nullable: bool
    default: Any = None
    has_default: bool = False
    value: Any = None
    configured: bool = False
    description: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedSystemResourceRequirement(SystemBaseModel):
    """One external resource contract copied into an execution plan."""

    ordinal: int
    name: str
    uses: str
    optional: bool
    description: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedSystemPortBinding(SystemBaseModel):
    """Resolved realization of a public System port."""

    ordinal: int
    port: str
    endpoint: str
    type_id: str
    endpoint_kind: Literal["application", "graph", "system"]
    target: str
    backend: str
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedSystemParameterBinding(SystemBaseModel):
    """Resolved fan-out of one public System parameter."""

    ordinal: int
    parameter: str
    targets: tuple[str, ...]
    value: Any = None
    configured: bool = False
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedSystemResourceBinding(SystemBaseModel):
    """Resolved internal realization of a System resource requirement."""

    ordinal: int
    resource: str
    instance: str
    uses: str
    target: str
    backend: str
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedSystemBoundaryBindings(SystemBaseModel):
    """Resolved input/output boundaries kept outside child implementation."""

    inputs: tuple[PlannedSystemPortBinding, ...] = ()
    outputs: tuple[PlannedSystemPortBinding, ...] = ()
    parameters: tuple[PlannedSystemParameterBinding, ...] = ()
    resources: tuple[PlannedSystemResourceBinding, ...] = ()

    def input(self, name: str) -> PlannedSystemPortBinding:
        for item in self.inputs:
            if item.port == name:
                return item
        raise KeyError(name)

    def output(self, name: str) -> PlannedSystemPortBinding:
        for item in self.outputs:
            if item.port == name:
                return item
        raise KeyError(name)

    def resource(self, name: str) -> PlannedSystemResourceBinding:
        for item in self.resources:
            if item.resource == name:
                return item
        raise KeyError(name)

    def parameter(self, name: str) -> PlannedSystemParameterBinding:
        for item in self.parameters:
            if item.parameter == name:
                return item
        raise KeyError(name)


class PlannedResource(SystemBaseModel):
    ordinal: int
    name: str
    uses: str
    target: str
    backend: str
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    bindings: Mapping[str, str] = Field(default_factory=dict)
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedApplication(SystemBaseModel):
    ordinal: int
    name: str
    uses: str
    target: str
    backend: str
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    resources: Mapping[str, str] = Field(default_factory=dict)
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedNode(SystemBaseModel):
    ordinal: int
    id: str
    graph: str
    name: str
    uses: str
    target: str
    backend: str
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    resources: Mapping[str, str] = Field(default_factory=dict)
    inputs: Mapping[str, str] = Field(default_factory=dict)
    outputs: Mapping[str, str] = Field(default_factory=dict)
    optional_inputs: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedConnection(SystemBaseModel):
    ordinal: int
    graph: str
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    type_id: str | None = None
    placement_target: str
    backend: str
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedGraph(SystemBaseModel):
    name: str
    nodes: tuple[PlannedNode, ...] = ()
    connections: tuple[PlannedConnection, ...] = ()
    topological_order: tuple[str, ...] = ()
    acyclic: bool = True
    targets: tuple[str, ...] = ()
    backends: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    def node(self, name: str) -> PlannedNode:
        for item in self.nodes:
            if item.name == name:
                return item
        raise KeyError(name)


class PlannedLink(SystemBaseModel):
    ordinal: int
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    type_id: str | None = None
    source_target: str
    target_target: str
    source_backend: str
    target_backend: str
    boundary: Literal[
        "cross_graph",
        "cross_target",
        "cross_backend",
        "application",
        "system",
    ]
    transport_required: bool
    transport_uses: str | None = None
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedArtifact(SystemBaseModel):
    name: str
    kind: str
    producer: str | None = None
    target: str | None = None
    backend: str | None = None
    path: str | None = None
    media_type: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedSystemInstance(SystemBaseModel):
    """One child System instance with its exact recursively resolved plan."""

    ordinal: int
    name: str
    revision: str
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    resources: Mapping[str, str] = Field(default_factory=dict)
    resource_bindings: tuple["PlannedChildSystemResourceBinding", ...] = ()
    plan: "SystemExecutionPlan"


class PlannedChildSystemResourceBinding(SystemBaseModel):
    """One parent ResourceInstance injected through a child resource boundary."""

    ordinal: int
    requirement: str
    parent_resource: str
    child_resource: str
    uses: str
    target: str
    backend: str
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    bindings: Mapping[str, str] = Field(default_factory=dict)
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)


class PlannedSystemDependency(SystemBaseModel):
    """One validated sibling startup edge copied into the execution plan."""

    ordinal: int
    system: str
    requires: str
    condition: SystemDependencyCondition
    timeout_seconds: float


class PlannedSystemStartup(SystemBaseModel):
    """Deterministic startup topology compiled once by the planner."""

    dependencies: tuple[PlannedSystemDependency, ...]
    order: tuple[str, ...]
    roots: tuple[str, ...]


class SystemExecutionPlan(SystemBaseModel):
    """Resolved system topology consumed by future execution backends."""

    schema_id: Literal["nodrix.system-execution-plan/v1"] = Field(
        default=SYSTEM_EXECUTION_PLAN_SCHEMA,
        alias="schema",
    )
    system: str
    system_sha256: str
    execution_context_sha256: str | None = None
    inputs: tuple[PlannedSystemPort, ...] = ()
    outputs: tuple[PlannedSystemPort, ...] = ()
    parameters: tuple[PlannedSystemParameter, ...] = ()
    resource_requirements: tuple[
        PlannedSystemResourceRequirement,
        ...,
    ] = ()
    bindings: PlannedSystemBoundaryBindings = Field(
        default_factory=PlannedSystemBoundaryBindings
    )
    systems: tuple[PlannedSystemInstance, ...] = ()
    system_startup: PlannedSystemStartup | None = None
    targets: tuple[PlannedTarget, ...] = ()
    resources: tuple[PlannedResource, ...] = ()
    resource_order: tuple[str, ...] = ()
    applications: tuple[PlannedApplication, ...] = ()
    graphs: tuple[PlannedGraph, ...] = ()
    links: tuple[PlannedLink, ...] = ()
    artifacts: tuple[PlannedArtifact, ...] = ()
    diagnostics: tuple[PlanningDiagnostic, ...] = ()
    policies: Mapping[str, Any] = Field(default_factory=dict)
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    extensions: Mapping[str, Any] = Field(default_factory=dict)
    summary: Mapping[str, int] = Field(default_factory=dict)

    def graph(self, name: str) -> PlannedGraph:
        for item in self.graphs:
            if item.name == name:
                return item
        raise KeyError(name)

    def target(self, name: str) -> PlannedTarget:
        for item in self.targets:
            if item.name == name:
                return item
        raise KeyError(name)

    def child(self, name: str) -> PlannedSystemInstance:
        for item in self.systems:
            if item.name == name:
                return item
        raise KeyError(name)

    def input(self, name: str) -> PlannedSystemPort:
        for item in self.inputs:
            if item.name == name:
                return item
        raise KeyError(name)

    def output(self, name: str) -> PlannedSystemPort:
        for item in self.outputs:
            if item.name == name:
                return item
        raise KeyError(name)

    def resource_requirement(
        self,
        name: str,
    ) -> PlannedSystemResourceRequirement:
        for item in self.resource_requirements:
            if item.name == name:
                return item
        raise KeyError(name)


PlannedSystemInstance.model_rebuild()


class _EndpointResolution:
    __slots__ = ("kind", "target", "backend", "type_id")

    def __init__(
        self,
        *,
        kind: str,
        target: str,
        backend: str,
        type_id: str | None,
    ) -> None:
        self.kind = kind
        self.target = target
        self.backend = backend
        self.type_id = type_id


def _target_backend(properties: Mapping[str, Any], *, path: str) -> str:
    raw = properties.get("backend", "local")
    if not isinstance(raw, str) or not raw.strip():
        raise SystemPlanningError(
            "PLAN202",
            path,
            "Target property 'backend' must be a non-empty string",
        )
    return raw.strip()


def _validation_diagnostics(
    report: SystemValidationReport,
) -> list[PlanningDiagnostic]:
    return [
        PlanningDiagnostic(
            code=item.code,
            path=item.path,
            message=item.message,
            source="system_validation",
        )
        for item in report.warnings
    ]


def _raise_validation_errors(report: SystemValidationReport) -> None:
    if not report.errors:
        return
    detail = "; ".join(
        f"{item.code} {item.path}: {item.message}"
        for item in report.errors
    )
    raise SystemPlanningError(
        "PLAN100",
        "system",
        f"System validation failed before planning: {detail}",
    )


def _topological_order(
    node_names: list[str],
    edges: list[tuple[str, str]],
) -> tuple[tuple[str, ...], bool]:
    indegree = {name: 0 for name in node_names}
    outgoing: dict[str, list[str]] = defaultdict(list)

    for source, target in edges:
        if source == target:
            continue
        outgoing[source].append(target)
        indegree[target] += 1

    ready = deque(name for name in node_names if indegree[name] == 0)
    ordered: list[str] = []
    while ready:
        name = ready.popleft()
        ordered.append(name)
        for target in outgoing[name]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    acyclic = len(ordered) == len(node_names)
    ordered.extend(name for name in node_names if name not in ordered)
    return tuple(ordered), acyclic


def _definition_contracts(
    uses: str,
    *,
    catalog: DefinitionCatalog | None,
) -> tuple[dict[str, str], dict[str, str], tuple[str, ...]]:
    if catalog is None:
        return {}, {}, ()
    definition = catalog.nodes.get(uses)
    if definition is None:
        return {}, {}, ()
    inputs = {port.name: port.type_id for port in definition.inputs}
    outputs = {port.name: port.type_id for port in definition.outputs}
    optional_inputs = tuple(port.name for port in definition.inputs if port.optional)
    return inputs, outputs, optional_inputs


def _ensure_resource_locality(
    *,
    owner_path: str,
    binding_field: str,
    owner_target: str,
    owner_backend: str,
    bindings: Mapping[str, str],
    resources: Mapping[str, PlannedResource],
) -> None:
    for slot, resource_name in bindings.items():
        resource = resources[resource_name]
        if resource.target != owner_target:
            raise SystemPlanningError(
                "PLAN301",
                f"{owner_path}.{binding_field}.{slot}",
                "direct Resource binding crosses execution targets: "
                f"{owner_target!r} -> {resource.target!r}; use an explicit "
                "application/link boundary for remote services",
            )
        if resource.backend != owner_backend:
            raise SystemPlanningError(
                "PLAN302",
                f"{owner_path}.{binding_field}.{slot}",
                "direct Resource binding crosses execution backends: "
                f"{owner_backend!r} -> {resource.backend!r}",
            )


def plan_system(
    system: SystemModel,
    *,
    catalog: DefinitionCatalog | None = None,
    execution_context: SystemExecutionContext | None = None,
    system_resolver: SystemDefinitionResolver | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> SystemExecutionPlan:
    """Resolve a validated SystemModel into a deterministic system plan.

    M1 resolves identity, placement, backend ownership, graph order, resource
    locality, SystemLink boundary requirements, and artifact placement.  It does
    not lower work into backend/runtime-specific queues or processes.
    """

    validation = validate_system(
        system,
        catalog=catalog,
        system_resolver=system_resolver,
    )
    _raise_validation_errors(validation)

    diagnostics = _validation_diagnostics(validation)
    parameter_values = dict(parameters or {})
    parameter_contracts = {
        item.name: item
        for item in system.parameters
    }

    unknown_parameters = sorted(
        set(parameter_values) - set(parameter_contracts)
    )
    if unknown_parameters:
        name = unknown_parameters[0]
        raise SystemPlanningError(
            "PLAN407",
            f"parameters.{name}",
            "parameter is not declared by the System Definition",
        )

    for name, contract in parameter_contracts.items():
        if contract.required and name not in parameter_values:
            raise SystemPlanningError(
                "PLAN408",
                f"parameters.{name}",
                "required System parameter is not configured",
            )
        if (
            name in parameter_values
            and not contract.accepts(parameter_values[name])
        ):
            raise SystemPlanningError(
                "PLAN409",
                f"parameters.{name}",
                "System parameter does not match declared type "
                f"{contract.value_type.value!r}",
            )

    planned_inputs = tuple(
        PlannedSystemPort(
            ordinal=index,
            name=port.name,
            type_id=port.type_id,
            optional=port.optional,
            description=port.description,
            metadata=dict(port.metadata),
            extensions=dict(port.extensions),
        )
        for index, port in enumerate(system.inputs)
    )
    planned_outputs = tuple(
        PlannedSystemPort(
            ordinal=index,
            name=port.name,
            type_id=port.type_id,
            optional=port.optional,
            description=port.description,
            metadata=dict(port.metadata),
            extensions=dict(port.extensions),
        )
        for index, port in enumerate(system.outputs)
    )
    planned_parameters = tuple(
        PlannedSystemParameter(
            ordinal=index,
            name=contract.name,
            type=contract.value_type.value,
            required=contract.required,
            nullable=contract.nullable,
            default=contract.default,
            has_default=contract.has_default,
            value=(
                parameter_values[contract.name]
                if contract.name in parameter_values
                else contract.default
            ),
            configured=(
                contract.name in parameter_values
            ),
            description=contract.description,
            metadata=dict(contract.metadata),
            extensions=dict(contract.extensions),
        )
        for index, contract in enumerate(system.parameters)
    )
    planned_resource_requirements = tuple(
        PlannedSystemResourceRequirement(
            ordinal=index,
            name=requirement.name,
            uses=requirement.uses,
            optional=requirement.optional,
            description=requirement.description,
            metadata=dict(requirement.metadata),
            extensions=dict(requirement.extensions),
        )
        for index, requirement in enumerate(
            system.resource_requirements
        )
    )
    effective_parameter_values = {
        item.name: item.value
        for item in planned_parameters
        if item.configured or item.has_default
    }
    parameter_overrides: dict[
        tuple[str, str | None, str],
        dict[str, Any],
    ] = {}
    for binding in system.bindings.parameters:
        if binding.parameter not in effective_parameter_values:
            continue
        value = effective_parameter_values[binding.parameter]
        for raw_target in binding.targets:
            target = parse_system_parameter_target(
                raw_target
            )
            key = (
                target.kind.value,
                target.scope,
                target.instance,
            )
            parameter_overrides.setdefault(
                key,
                {},
            )[target.parameter] = value

    planned_system_startup: PlannedSystemStartup | None = None

    if system.dependencies:
        dependency_edges = [
            (
                dependency.requires,
                dependency.system,
            )
            for dependency in system.dependencies
        ]
        system_order, systems_acyclic = _topological_order(
            [
                instance.name
                for instance in system.systems
            ],
            dependency_edges,
        )

        if not systems_acyclic:
            raise SystemPlanningError(
                "PLAN406",
                "dependencies",
                "System dependency graph contains a cycle",
            )

        dependent_names = {
            dependency.system
            for dependency in system.dependencies
        }

        planned_system_startup = PlannedSystemStartup(
            dependencies=tuple(
                PlannedSystemDependency(
                    ordinal=index,
                    system=dependency.system,
                    requires=dependency.requires,
                    condition=dependency.condition,
                    timeout_seconds=(
                        dependency.timeout_seconds
                    ),
                )
                for index, dependency in enumerate(
                    system.dependencies
                )
            ),
            order=system_order,
            roots=tuple(
                instance.name
                for instance in system.systems
                if instance.name not in dependent_names
            ),
        )

    planned_systems_list: list[
        PlannedSystemInstance
    ] = []

    for index, instance in enumerate(
        system.systems
    ):
        path = f"systems[{index}]"

        if system_resolver is None:
            raise SystemPlanningError(
                "PLAN404",
                f"{path}.uses",
                "child System Definition is required for hierarchical "
                "planning, but no SystemDefinitionResolver was provided",
            )

        child = system_resolver(
            instance.revision
        )

        if child is None:
            raise SystemPlanningError(
                "PLAN404",
                f"{path}.uses",
                "cannot resolve exact child System Definition "
                f"{instance.revision.canonical!r}",
            )

        if not isinstance(
            child,
            SystemModel,
        ):
            raise SystemPlanningError(
                "PLAN405",
                f"{path}.uses",
                "SystemDefinitionResolver returned a value that is not "
                "a SystemModel",
            )

        actual_revision = RevisionRef.from_sha256(
            instance.revision.entity,
            system_definition_digest(
                child
            ),
        )

        if (
            child.name
            != instance.revision.entity.name
            or actual_revision.canonical
            != instance.revision.canonical
        ):
            raise SystemPlanningError(
                "PLAN405",
                f"{path}.uses",
                "resolved child System Definition does not match the "
                "exact pinned RevisionRef",
            )

        try:
            child_parameters = dict(
                instance.parameters
            )
            child_parameters.update(
                parameter_overrides.get(
                    (
                        SystemParameterTargetKind.SYSTEM.value,
                        None,
                        instance.name,
                    ),
                    {},
                )
            )
            child_context = child_system_execution_context(
                execution_context,
                instance.name,
            )
            child_plan = plan_system(
                child,
                catalog=catalog,
                execution_context=child_context,
                system_resolver=system_resolver,
                parameters=child_parameters,
            )
        except SystemPlanningError as exc:
            nested_path = (
                f"{path}.{exc.path}"
                if exc.path
                else path
            )

            raise SystemPlanningError(
                exc.code,
                nested_path,
                f"child System {instance.name!r}: "
                f"{exc.message}",
            ) from exc

        planned_systems_list.append(
            PlannedSystemInstance(
                ordinal=index,
                name=instance.name,
                revision=(
                    instance.revision.canonical
                ),
                parameters=child_parameters,
                resources=dict(instance.resources),
                plan=child_plan,
            )
        )

    planned_systems = tuple(
        planned_systems_list
    )

    if system.targets:
        planned_targets = tuple(
            PlannedTarget(
                name=target.name,
                kind=target.kind,
                backend=_target_backend(
                    target.properties,
                    path=f"targets[{index}].properties.backend",
                ),
                properties=dict(target.properties),
                metadata=dict(target.metadata),
                implicit=False,
            )
            for index, target in enumerate(system.targets)
        )
    else:
        planned_targets = (
            PlannedTarget(
                name="local",
                kind="local",
                backend="local",
                implicit=True,
            ),
        )

    target_map = {target.name: target for target in planned_targets}
    default_target = planned_targets[0] if len(planned_targets) == 1 else None

    def resolve_target(name: str | None, *, path: str) -> PlannedTarget:
        if name is not None:
            return target_map[name]
        if default_target is not None:
            return default_target
        raise SystemPlanningError(
            "PLAN201",
            path,
            "instance has no target but the System declares multiple targets; "
            "placement must be explicit",
        )

    def resolved_parameters(
        kind: SystemParameterTargetKind,
        name: str,
        values: Mapping[str, Any],
        *,
        scope: str | None = None,
    ) -> dict[str, Any]:
        result = dict(values)
        result.update(
            parameter_overrides.get(
                (kind.value, scope, name),
                {},
            )
        )
        return result

    planned_resources = tuple(
        PlannedResource(
            ordinal=index,
            name=resource.name,
            uses=resource.uses,
            target=(resolved := resolve_target(
                resource.target,
                path=f"resources[{index}].target",
            )).name,
            backend=resolved.backend,
            parameters=resolved_parameters(
                SystemParameterTargetKind.RESOURCE,
                resource.name,
                resource.parameters,
            ),
            bindings=dict(resource.bindings),
            metadata=dict(resource.metadata),
            extensions=dict(resource.extensions),
        )
        for index, resource in enumerate(system.resources)
    )
    resource_map = {resource.name: resource for resource in planned_resources}
    resource_edges: list[tuple[str, str]] = []
    for resource in planned_resources:
        for bound in resource.bindings.values():
            if bound == resource.name:
                raise SystemPlanningError(
                    "PLAN303",
                    f"resources[{resource.ordinal}].bindings",
                    "Resource dependency cycle contains a self-binding",
                )
            resource_edges.append((bound, resource.name))
    resource_order, resources_acyclic = _topological_order(
        [resource.name for resource in planned_resources],
        resource_edges,
    )
    if not resources_acyclic:
        raise SystemPlanningError(
            "PLAN303",
            "resources",
            "Resource dependency graph contains a cycle",
        )

    for index, resource in enumerate(planned_resources):
        _ensure_resource_locality(
            owner_path=f"resources[{index}]",
            binding_field="bindings",
            owner_target=resource.target,
            owner_backend=resource.backend,
            bindings=resource.bindings,
            resources=resource_map,
        )

    bound_systems: list[PlannedSystemInstance] = []
    for child in planned_systems:
        resource_bindings: list[
            PlannedChildSystemResourceBinding
        ] = []
        for ordinal, (
            requirement_name,
            parent_resource_name,
        ) in enumerate(child.resources.items()):
            parent_resource = resource_map[
                parent_resource_name
            ]
            requirement = child.plan.resource_requirement(
                requirement_name
            )
            try:
                child_binding = child.plan.bindings.resource(
                    requirement_name
                )
            except KeyError as exc:
                raise SystemPlanningError(
                    "PLAN413",
                    f"systems[{child.ordinal}].resources.{requirement_name}",
                    "child System resource requirement has no concrete "
                    "internal boundary binding",
                ) from exc

            if (
                parent_resource.target != child_binding.target
                or parent_resource.backend != child_binding.backend
            ):
                raise SystemPlanningError(
                    "PLAN412",
                    f"systems[{child.ordinal}].resources.{requirement_name}",
                    "direct child System resource binding crosses "
                    "target/backend placement",
                )

            resource_bindings.append(
                PlannedChildSystemResourceBinding(
                    ordinal=ordinal,
                    requirement=requirement_name,
                    parent_resource=parent_resource.name,
                    child_resource=child_binding.instance,
                    uses=requirement.uses,
                    target=parent_resource.target,
                    backend=parent_resource.backend,
                    parameters=dict(parent_resource.parameters),
                    bindings=dict(parent_resource.bindings),
                    metadata=dict(parent_resource.metadata),
                    extensions=dict(parent_resource.extensions),
                )
            )

        bound_systems.append(
            child.model_copy(
                update={
                    "resource_bindings": tuple(
                        resource_bindings
                    )
                }
            )
        )

    planned_systems = tuple(bound_systems)
    planned_system_map = {
        item.name: item
        for item in planned_systems
    }

    planned_applications_list: list[PlannedApplication] = []
    for index, application in enumerate(system.applications):
        resolved = resolve_target(
            application.target,
            path=f"applications[{index}].target",
        )
        planned = PlannedApplication(
            ordinal=index,
            name=application.name,
            uses=application.uses,
            target=resolved.name,
            backend=resolved.backend,
            parameters=resolved_parameters(
                SystemParameterTargetKind.APPLICATION,
                application.name,
                application.parameters,
            ),
            resources=dict(application.resources),
            metadata=dict(application.metadata),
            extensions=dict(application.extensions),
        )
        _ensure_resource_locality(
            owner_path=f"applications[{index}]",
            binding_field="resources",
            owner_target=planned.target,
            owner_backend=planned.backend,
            bindings=planned.resources,
            resources=resource_map,
        )
        planned_applications_list.append(planned)
    planned_applications = tuple(planned_applications_list)
    application_map = {item.name: item for item in planned_applications}

    planned_graphs: list[PlannedGraph] = []
    node_global_map: dict[tuple[str, str], PlannedNode] = {}

    for graph_index, graph in enumerate(system.graphs):
        planned_nodes: list[PlannedNode] = []
        local_node_map: dict[str, PlannedNode] = {}

        for node_index, node in enumerate(graph.nodes):
            resolved_target = resolve_target(
                node.target,
                path=f"graphs[{graph_index}].nodes[{node_index}].target",
            )
            backend = node.backend or resolved_target.backend
            if not isinstance(backend, str) or not backend.strip():
                raise SystemPlanningError(
                    "PLAN203",
                    f"graphs[{graph_index}].nodes[{node_index}].backend",
                    "Node backend must be a non-empty string",
                )
            backend = backend.strip()
            inputs, outputs, optional_inputs = _definition_contracts(
                node.uses,
                catalog=catalog,
            )
            planned = PlannedNode(
                ordinal=node_index,
                id=f"{graph.name}/{node.name}",
                graph=graph.name,
                name=node.name,
                uses=node.uses,
                target=resolved_target.name,
                backend=backend,
                parameters=resolved_parameters(
                    SystemParameterTargetKind.NODE,
                    node.name,
                    node.parameters,
                    scope=graph.name,
                ),
                resources=dict(node.resources),
                inputs=inputs,
                outputs=outputs,
                optional_inputs=optional_inputs,
                metadata=dict(node.metadata),
                extensions=dict(node.extensions),
            )
            _ensure_resource_locality(
                owner_path=f"graphs[{graph_index}].nodes[{node_index}]",
                binding_field="resources",
                owner_target=planned.target,
                owner_backend=planned.backend,
                bindings=planned.resources,
                resources=resource_map,
            )
            planned_nodes.append(planned)
            local_node_map[node.name] = planned
            node_global_map[(graph.name, node.name)] = planned

        planned_connections: list[PlannedConnection] = []
        topo_edges: list[tuple[str, str]] = []
        for connection_index, connection in enumerate(graph.connections):
            source_name, source_port = split_local_endpoint(connection.source)
            target_name, target_port = split_local_endpoint(connection.target)
            source_node = local_node_map[source_name]
            target_node = local_node_map[target_name]

            if (
                source_node.target != target_node.target
                or source_node.backend != target_node.backend
            ):
                raise SystemPlanningError(
                    "PLAN401",
                    f"graphs[{graph_index}].connections[{connection_index}]",
                    "Graph Connection crosses target/backend placement. "
                    "Split the boundary into Graphs and connect them with an "
                    "explicit SystemLink so transport semantics are visible.",
                )

            source_type = source_node.outputs.get(source_port)
            target_type = target_node.inputs.get(target_port)
            type_id = connection.type_id or source_type or target_type
            planned_connections.append(
                PlannedConnection(
                    ordinal=connection_index,
                    graph=graph.name,
                    **{
                        "from": connection.source,
                        "to": connection.target,
                    },
                    type_id=type_id,
                    placement_target=source_node.target,
                    backend=source_node.backend,
                    metadata=dict(connection.metadata),
                    extensions=dict(connection.extensions),
                )
            )
            topo_edges.append((source_name, target_name))

        order, acyclic = _topological_order(
            [node.name for node in planned_nodes],
            topo_edges,
        )
        if not acyclic:
            diagnostics.append(
                PlanningDiagnostic(
                    code="PLAN101",
                    path=f"graphs[{graph_index}]",
                    message=(
                        f"Graph {graph.name!r} contains a cycle; declared order is "
                        "preserved for unresolved feedback members"
                    ),
                )
            )

        planned_graphs.append(
            PlannedGraph(
                name=graph.name,
                nodes=tuple(planned_nodes),
                connections=tuple(planned_connections),
                topological_order=order,
                acyclic=acyclic,
                targets=tuple(dict.fromkeys(node.target for node in planned_nodes)),
                backends=tuple(dict.fromkeys(node.backend for node in planned_nodes)),
                metadata=dict(graph.metadata),
                extensions=dict(graph.extensions),
            )
        )

    def resolve_endpoint(
        value: str,
        *,
        direction: Literal["source", "target"],
    ) -> _EndpointResolution:
        endpoint = parse_system_endpoint(value)
        instance_name = endpoint.instance
        port_name = endpoint.port

        if endpoint.kind is SystemEndpointKind.APPLICATION:
            application = application_map[
                instance_name
            ]
            return _EndpointResolution(
                kind="application",
                target=application.target,
                backend=application.backend,
                type_id=None,
            )

        if endpoint.kind is SystemEndpointKind.SYSTEM:
            child = planned_system_map[instance_name]
            try:
                if direction == "source":
                    port = child.plan.output(port_name)
                    binding = child.plan.bindings.output(
                        port_name
                    )
                else:
                    port = child.plan.input(port_name)
                    binding = child.plan.bindings.input(
                        port_name
                    )
            except KeyError as exc:
                raise SystemPlanningError(
                    "PLAN410",
                    "links",
                    f"child System endpoint {value!r} has no concrete "
                    "internal boundary binding",
                ) from exc

            return _EndpointResolution(
                kind="system",
                target=binding.target,
                backend=binding.backend,
                type_id=port.type_id,
            )

        graph_name = endpoint.scope
        assert graph_name is not None
        node = node_global_map[
            (graph_name, instance_name)
        ]
        contract = (
            node.outputs.get(port_name)
            if direction == "source"
            else node.inputs.get(port_name)
        )
        return _EndpointResolution(
            kind="graph",
            target=node.target,
            backend=node.backend,
            type_id=contract,
        )

    planned_input_bindings = tuple(
        PlannedSystemPortBinding(
            ordinal=index,
            port=binding.port,
            endpoint=binding.endpoint,
            type_id=system.input(
                binding.port
            ).type_id,
            endpoint_kind=resolved.kind,
            target=resolved.target,
            backend=resolved.backend,
            metadata=dict(binding.metadata),
            extensions=dict(binding.extensions),
        )
        for index, binding in enumerate(
            system.bindings.inputs
        )
        for resolved in (
            resolve_endpoint(
                binding.endpoint,
                direction="target",
            ),
        )
    )
    planned_output_bindings = tuple(
        PlannedSystemPortBinding(
            ordinal=index,
            port=binding.port,
            endpoint=binding.endpoint,
            type_id=system.output(
                binding.port
            ).type_id,
            endpoint_kind=resolved.kind,
            target=resolved.target,
            backend=resolved.backend,
            metadata=dict(binding.metadata),
            extensions=dict(binding.extensions),
        )
        for index, binding in enumerate(
            system.bindings.outputs
        )
        for resolved in (
            resolve_endpoint(
                binding.endpoint,
                direction="source",
            ),
        )
    )
    planned_resource_bindings = tuple(
        PlannedSystemResourceBinding(
            ordinal=index,
            resource=binding.resource,
            instance=binding.instance,
            uses=system.resource_requirement(
                binding.resource
            ).uses,
            target=resource.target,
            backend=resource.backend,
            metadata=dict(binding.metadata),
            extensions=dict(binding.extensions),
        )
        for index, binding in enumerate(
            system.bindings.resources
        )
        for resource in (
            resource_map[binding.instance],
        )
    )
    planned_parameter_bindings = tuple(
        PlannedSystemParameterBinding(
            ordinal=index,
            parameter=binding.parameter,
            targets=tuple(binding.targets),
            value=parameter.value,
            configured=parameter.configured,
            metadata=dict(binding.metadata),
            extensions=dict(binding.extensions),
        )
        for index, binding in enumerate(
            system.bindings.parameters
        )
        for parameter in (
            next(
                item
                for item in planned_parameters
                if item.name == binding.parameter
            ),
        )
    )
    planned_boundary_bindings = (
        PlannedSystemBoundaryBindings(
            inputs=planned_input_bindings,
            outputs=planned_output_bindings,
            parameters=planned_parameter_bindings,
            resources=planned_resource_bindings,
        )
    )

    planned_links: list[PlannedLink] = []
    for index, link in enumerate(system.links):
        source = resolve_endpoint(link.source, direction="source")
        target = resolve_endpoint(link.target, direction="target")
        has_application = "application" in {source.kind, target.kind}
        has_system = "system" in {source.kind, target.kind}
        cross_target = source.target != target.target
        cross_backend = source.backend != target.backend

        if has_system:
            boundary = "system"
        elif has_application:
            boundary = "application"
        elif cross_target:
            boundary = "cross_target"
        elif cross_backend:
            boundary = "cross_backend"
        else:
            boundary = "cross_graph"

        transport_required = (
            has_application
            or (
                has_system
                and link.uses is not None
            )
            or cross_target
            or cross_backend
            or link.uses is not None
        )
        if has_application and link.uses is None:
            raise SystemPlanningError(
                "PLAN402",
                f"links[{index}].uses",
                "Application boundaries require an explicit transport/integration 'uses'",
            )
        if has_system and (cross_target or cross_backend) and link.uses is None:
            raise SystemPlanningError(
                "PLAN411",
                f"links[{index}].uses",
                "Cross-target/backend child System link requires an explicit "
                "transport 'uses'",
            )
        if (cross_target or cross_backend) and link.uses is None:
            raise SystemPlanningError(
                "PLAN403",
                f"links[{index}].uses",
                "Cross-target/backend SystemLink requires an explicit transport 'uses'",
            )

        planned_links.append(
            PlannedLink(
                ordinal=index,
                **{"from": link.source, "to": link.target},
                type_id=link.type_id or source.type_id or target.type_id,
                source_target=source.target,
                target_target=target.target,
                source_backend=source.backend,
                target_backend=target.backend,
                boundary=boundary,
                transport_required=transport_required,
                transport_uses=link.uses,
                parameters=dict(link.parameters),
                metadata=dict(link.metadata),
                extensions=dict(link.extensions),
            )
        )

    planned_artifacts: list[PlannedArtifact] = []
    for artifact in system.artifacts:
        if artifact.producer is None:
            producer_target = None
            producer_backend = None
        else:
            producer = resolve_endpoint(artifact.producer, direction="source")
            producer_target = producer.target
            producer_backend = producer.backend
        planned_artifacts.append(
            PlannedArtifact(
                name=artifact.name,
                kind=artifact.kind,
                producer=artifact.producer,
                target=producer_target,
                backend=producer_backend,
                path=artifact.path,
                media_type=artifact.media_type,
                metadata=dict(artifact.metadata),
                extensions=dict(artifact.extensions),
            )
        )

    graphs_tuple = tuple(planned_graphs)
    links_tuple = tuple(planned_links)
    artifacts_tuple = tuple(planned_artifacts)
    return SystemExecutionPlan(
        system=system.name,
        system_sha256=system_definition_digest(system),
        execution_context_sha256=(
            system_execution_context_digest(
                execution_context
            )
            if execution_context is not None
            else None
        ),
        inputs=planned_inputs,
        outputs=planned_outputs,
        parameters=planned_parameters,
        resource_requirements=(
            planned_resource_requirements
        ),
        bindings=planned_boundary_bindings,
        systems=planned_systems,
        system_startup=planned_system_startup,
        targets=planned_targets,
        resources=planned_resources,
        resource_order=resource_order,
        applications=planned_applications,
        graphs=graphs_tuple,
        links=links_tuple,
        artifacts=artifacts_tuple,
        diagnostics=tuple(diagnostics),
        policies=dict(system.policies),
        metadata=dict(system.metadata),
        extensions=dict(system.extensions),
        summary={
            "systems": len(planned_systems),
            "targets": len(planned_targets),
            "resources": len(planned_resources),
            "applications": len(planned_applications),
            "graphs": len(graphs_tuple),
            "nodes": sum(len(graph.nodes) for graph in graphs_tuple),
            "connections": sum(len(graph.connections) for graph in graphs_tuple),
            "links": len(links_tuple),
            "artifacts": len(artifacts_tuple),
            **(
                {"inputs": len(planned_inputs)}
                if planned_inputs
                else {}
            ),
            **(
                {"outputs": len(planned_outputs)}
                if planned_outputs
                else {}
            ),
            **(
                {"parameters": len(planned_parameters)}
                if planned_parameters
                else {}
            ),
            **(
                {
                    "resource_requirements": len(
                        planned_resource_requirements
                    )
                }
                if planned_resource_requirements
                else {}
            ),
            **(
                {
                    "dependencies": len(
                        planned_system_startup.dependencies
                    ),
                }
                if planned_system_startup is not None
                else {}
            ),
        },
    )



__all__ = [
    "SYSTEM_EXECUTION_PLAN_SCHEMA",
    "PlannedApplication",
    "PlannedArtifact",
    "PlannedConnection",
    "PlannedGraph",
    "PlannedLink",
    "PlannedNode",
    "PlannedResource",
    "PlannedChildSystemResourceBinding",
    "PlannedSystemBoundaryBindings",
    "PlannedSystemParameter",
    "PlannedSystemParameterBinding",
    "PlannedSystemPort",
    "PlannedSystemPortBinding",
    "PlannedSystemResourceBinding",
    "PlannedSystemResourceRequirement",
    "PlannedSystemInstance",
    "PlannedSystemDependency",
    "PlannedSystemStartup",
    "PlannedTarget",
    "PlanningDiagnostic",
    "SystemDefinitionResolver",
    "SystemExecutionPlan",
    "SystemPlanningError",
    "plan_system",
]
