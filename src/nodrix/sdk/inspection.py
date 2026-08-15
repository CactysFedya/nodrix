"""Python annotations -> backend-neutral SDK definitions."""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, AsyncIterator, Generator, Iterator, Mapping
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from ..cv_types import TYPE_REGISTRY, register_message_type
from ..node import NodeContext
from .definitions import (
    CallableDefinition,
    DependencyDefinition,
    NodeDefinition,
    ParameterDefinition,
    PortDefinition,
    ResourceDefinition,
)
from .typing import Input, Outputs, Param, Resource

Context = NodeContext

_PRIMITIVE_TYPES: dict[Any, str] = {
    Any: "core.any",
    bool: "core.bool",
    bytes: "core.bytes",
    bytearray: "core.bytes",
    float: "core.float",
    int: "core.int",
    str: "core.string",
}

for _type_id, _python_type in (
    ("core.bool", bool),
    ("core.float", float),
    ("core.int", int),
    ("core.string", str),
):
    if TYPE_REGISTRY.definition(_type_id) is None:
        register_message_type(_type_id, _python_type)


def unwrap_marker(annotation: Any, marker: type[Any]) -> tuple[bool, Any]:
    if get_origin(annotation) is marker:
        args = get_args(annotation)
        if len(args) != 1:
            raise TypeError(f"{marker.__name__}[T] requires exactly one type argument")
        return True, args[0]
    return False, annotation


def unwrap_optional(annotation: Any) -> tuple[bool, Any]:
    origin = get_origin(annotation)
    if origin not in (Union, UnionType):
        return False, annotation
    args = get_args(annotation)
    non_none = tuple(item for item in args if item is not type(None))
    if len(non_none) == 1 and len(non_none) != len(args):
        return True, non_none[0]
    return False, annotation


def message_type_for(annotation: Any) -> str | None:
    explicit = getattr(annotation, "__plyctl_message_type__", None)
    if explicit:
        return str(explicit)
    primitive = _PRIMITIVE_TYPES.get(annotation)
    if primitive:
        return primitive
    for name in TYPE_REGISTRY.names():
        definition = TYPE_REGISTRY.definition(name)
        if definition is None or definition.payload_type is None:
            continue
        payload_type = definition.payload_type
        if payload_type is annotation:
            return name
        if isinstance(payload_type, tuple) and annotation in payload_type:
            return name
    return None


def resolve_output(annotation: Any, explicit_name: str | None) -> tuple[PortDefinition, ...]:
    if annotation in (inspect.Signature.empty, None, type(None)):
        return ()
    if inspect.isclass(annotation) and issubclass(annotation, Outputs):
        annotations = get_type_hints(annotation, include_extras=True)
        if not annotations:
            raise TypeError(f"Outputs subclass {annotation.__name__!r} declares no annotated fields")
        result: list[PortDefinition] = []
        for name, item in annotations.items():
            type_id = message_type_for(item)
            if type_id is None:
                raise TypeError(
                    f"Cannot infer output type for {annotation.__name__}.{name}; "
                    "use a registered @message type or Input-compatible primitive"
                )
            result.append(PortDefinition(name, type_id))
        return tuple(result)
    type_id = message_type_for(annotation)
    if type_id is None:
        raise TypeError(
            f"Cannot infer return type {annotation!r}; use a registered @message type "
            "or a supported primitive"
        )
    return (PortDefinition(explicit_name or "output", type_id),)


def analyze_callable(
    function: Any,
    *,
    component_name: str,
    output_name: str | None,
    localns: Mapping[str, Any] | None = None,
) -> CallableDefinition:
    signature = inspect.signature(function)
    hints = get_type_hints(
        function,
        globalns=getattr(function, "__globals__", None),
        localns=dict(localns or {}),
        include_extras=True,
    )
    inputs: list[PortDefinition] = []
    parameters: list[ParameterDefinition] = []
    dependencies: list[DependencyDefinition] = []

    for argument in signature.parameters.values():
        if argument.name in {"self", "cls"}:
            continue
        annotation = hints.get(argument.name, argument.annotation)
        if annotation is inspect.Signature.empty:
            raise TypeError(
                f"Cannot infer argument {argument.name!r} in node {component_name!r}; "
                "add a type annotation"
            )
        if annotation is NodeContext or annotation is Context:
            dependencies.append(DependencyDefinition(argument.name, "context", annotation))
            continue

        is_resource, inner = unwrap_marker(annotation, Resource)
        if is_resource:
            dependencies.append(DependencyDefinition(argument.name, "resource", inner))
            continue
        is_input, inner = unwrap_marker(annotation, Input)
        if is_input:
            optional, inner = unwrap_optional(inner)
            type_id = message_type_for(inner)
            if type_id is None:
                raise TypeError(f"Cannot infer input type for {argument.name!r}: {inner!r}")
            inputs.append(PortDefinition(argument.name, type_id, optional))
            continue
        is_param, inner = unwrap_marker(annotation, Param)
        if is_param:
            parameters.append(
                ParameterDefinition(
                    argument.name,
                    inner,
                    argument.default is inspect.Signature.empty,
                    None if argument.default is inspect.Signature.empty else argument.default,
                )
            )
            continue

        optional, unwrapped = unwrap_optional(annotation)
        type_id = message_type_for(unwrapped)
        if type_id is not None and unwrapped not in _PRIMITIVE_TYPES:
            inputs.append(PortDefinition(argument.name, type_id, optional))
            continue
        parameters.append(
            ParameterDefinition(
                argument.name,
                annotation,
                argument.default is inspect.Signature.empty,
                None if argument.default is inspect.Signature.empty else argument.default,
            )
        )

    outputs = resolve_output(hints.get("return", signature.return_annotation), output_name)
    return CallableDefinition(
        name=component_name,
        inputs=tuple(inputs),
        outputs=outputs,
        parameters=tuple(parameters),
        dependencies=tuple(dependencies),
        implementation=function,
    )


def analyze_constructor(
    cls: type[Any],
    *,
    component_name: str,
    localns: Mapping[str, Any] | None = None,
) -> CallableDefinition:
    initializer = cls.__dict__.get("__init__")
    if initializer is None:
        return CallableDefinition(component_name, (), (), (), (), cls)
    signature = inspect.signature(initializer)
    hints = get_type_hints(
        initializer,
        globalns=getattr(initializer, "__globals__", None),
        localns=dict(localns or {}),
        include_extras=True,
    )
    parameters: list[ParameterDefinition] = []
    dependencies: list[DependencyDefinition] = []
    for argument in signature.parameters.values():
        if argument.name in {"self", "cls"}:
            continue
        if argument.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            raise TypeError(
                f"Stateful node {component_name!r} cannot infer variadic constructor argument "
                f"{argument.name!r}"
            )
        if argument.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise TypeError(
                f"Stateful node {component_name!r} constructor argument {argument.name!r} "
                "must be keyword-compatible"
            )
        annotation = hints.get(argument.name, argument.annotation)
        if annotation is inspect.Signature.empty:
            raise TypeError(
                f"Cannot infer constructor argument {argument.name!r} in node {component_name!r}; "
                "add a type annotation"
            )
        if annotation is NodeContext or annotation is Context:
            dependencies.append(DependencyDefinition(argument.name, "context", annotation))
            continue
        is_resource, inner = unwrap_marker(annotation, Resource)
        if is_resource:
            dependencies.append(DependencyDefinition(argument.name, "resource", inner))
            continue
        is_input, _ = unwrap_marker(annotation, Input)
        if is_input:
            raise TypeError(
                f"Stateful node {component_name!r} constructor argument {argument.name!r} "
                "cannot be Input[T]; pipeline inputs belong in process()"
            )
        is_param, inner = unwrap_marker(annotation, Param)
        parameters.append(
            ParameterDefinition(
                argument.name,
                inner if is_param else annotation,
                argument.default is inspect.Signature.empty,
                None if argument.default is inspect.Signature.empty else argument.default,
            )
        )
    return CallableDefinition(
        component_name,
        (),
        (),
        tuple(parameters),
        tuple(dependencies),
        cls,
    )


def analyze_injected_method(
    method: Any | None,
    *,
    component_name: str,
    phase: str,
    localns: Mapping[str, Any] | None = None,
) -> tuple[DependencyDefinition, ...]:
    if method is None:
        return ()
    signature = inspect.signature(method)
    hints = get_type_hints(
        method,
        globalns=getattr(method, "__globals__", None),
        localns=dict(localns or {}),
        include_extras=True,
    )
    dependencies: list[DependencyDefinition] = []
    for argument in signature.parameters.values():
        if argument.name in {"self", "cls"}:
            continue
        annotation = hints.get(argument.name, argument.annotation)
        if annotation is NodeContext or annotation is Context:
            dependencies.append(DependencyDefinition(argument.name, "context", annotation))
            continue
        is_resource, inner = unwrap_marker(annotation, Resource)
        if is_resource:
            dependencies.append(DependencyDefinition(argument.name, "resource", inner))
            continue
        raise TypeError(
            f"Stateful node {component_name!r} {phase}() argument {argument.name!r} "
            "must be Context or Resource[T]"
        )
    return tuple(dependencies)


def merge_dependencies(
    *groups: tuple[DependencyDefinition, ...],
) -> tuple[DependencyDefinition, ...]:
    merged: list[DependencyDefinition] = []
    seen: set[tuple[str, str, Any]] = set()
    for group in groups:
        for item in group:
            key = (item.name, item.kind, item.annotation)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return tuple(merged)


def analyze_function_node(
    function: Any,
    *,
    component_name: str,
    output_name: str | None,
    localns: Mapping[str, Any] | None = None,
) -> NodeDefinition:
    call = analyze_callable(
        function,
        component_name=component_name,
        output_name=output_name,
        localns=localns,
    )
    return NodeDefinition(
        name=component_name,
        inputs=call.inputs,
        outputs=call.outputs,
        parameters=call.parameters,
        dependencies=call.dependencies,
        implementation=function,
        process=call,
    )


def analyze_class_node(
    user_class: type[Any],
    *,
    component_name: str,
    output_name: str | None,
    localns: Mapping[str, Any] | None = None,
) -> NodeDefinition:
    user_process = getattr(user_class, "process", None)
    if user_process is None or not callable(user_process):
        raise TypeError(f"@node class {user_class.__name__!r} must define process()")
    localns = {**dict(localns or {}), user_class.__name__: user_class}
    constructor = analyze_constructor(user_class, component_name=component_name, localns=localns)
    process = analyze_callable(
        user_process,
        component_name=component_name,
        output_name=output_name,
        localns=localns,
    )
    if process.parameters:
        names = ", ".join(item.name for item in process.parameters)
        raise TypeError(
            f"Stateful node {component_name!r} process() contains configuration parameter(s): "
            f"{names}. Move configuration to __init__(); use Input[T] for primitive ports."
        )
    if process.inputs and (
        inspect.isgeneratorfunction(user_process) or inspect.isasyncgenfunction(user_process)
    ):
        raise TypeError(
            f"Stateful node {component_name!r} process() cannot be a generator when it has inputs"
        )
    lifecycle = {
        phase: analyze_injected_method(
            user_class.__dict__.get(phase),
            component_name=component_name,
            phase=phase,
            localns=localns,
        )
        for phase in ("start", "drain", "stop", "health")
    }
    if inspect.iscoroutinefunction(user_class.__dict__.get("health")):
        raise TypeError(f"Stateful node {component_name!r} health() must be synchronous")
    dependencies = merge_dependencies(
        constructor.dependencies,
        process.dependencies,
        *lifecycle.values(),
    )
    return NodeDefinition(
        name=component_name,
        inputs=process.inputs,
        outputs=process.outputs,
        parameters=constructor.parameters,
        dependencies=dependencies,
        implementation=user_class,
        constructor=constructor,
        process=process,
        lifecycle_dependencies=lifecycle,
    )



_RESOURCE_LIFECYCLE_ORIGINS = frozenset(
    {
        Iterator,
        Generator,
        AsyncIterator,
        AsyncGenerator,
    }
)


def infer_resource_provided_type(
    factory: Any,
    *,
    explicit: Any | None = None,
) -> Any | None:
    """Infer the value exposed by a simplified resource.

    Normal/async factories expose their return annotation directly. Generator
    resources expose the yielded type from Iterator[T]/Generator[T, ...] (and
    their async equivalents). ``@resource(provides=T)`` remains available for
    unannotated factories or cases where the factory's lifecycle annotation
    cannot express the runtime resource type precisely.
    """

    signature = inspect.signature(factory)
    hints = get_type_hints(factory, include_extras=True)
    annotation = hints.get("return", signature.return_annotation)

    inferred: Any | None = None
    if annotation not in (inspect.Signature.empty, None, type(None)):
        origin = get_origin(annotation)
        if origin in _RESOURCE_LIFECYCLE_ORIGINS:
            args = get_args(annotation)
            inferred = args[0] if args else None
        else:
            inferred = annotation

    if explicit is not None and inferred is not None and explicit != inferred:
        try:
            compatible = (
                inspect.isclass(explicit)
                and inspect.isclass(inferred)
                and issubclass(explicit, inferred)
            )
        except TypeError:
            compatible = False
        if not compatible:
            raise TypeError(
                f"@resource provides={explicit!r} disagrees with return annotation "
                f"{annotation!r} on {factory.__qualname__}"
            )

    return explicit if explicit is not None else inferred


def analyze_resource_factory(
    factory: Any,
    *,
    component_name: str,
    provided_type: Any | None = None,
) -> ResourceDefinition:
    signature = inspect.signature(factory)
    hints = get_type_hints(factory, include_extras=True)
    parameters: list[ParameterDefinition] = []
    for argument in signature.parameters.values():
        annotation = hints.get(argument.name, argument.annotation)
        if annotation is inspect.Signature.empty:
            raise TypeError(
                f"Cannot infer resource parameter {argument.name!r} in {component_name!r}; "
                "add a type annotation"
            )
        is_param, inner = unwrap_marker(annotation, Param)
        parameters.append(
            ParameterDefinition(
                argument.name,
                inner if is_param else annotation,
                argument.default is inspect.Signature.empty,
                None if argument.default is inspect.Signature.empty else argument.default,
            )
        )
    return ResourceDefinition(
        name=component_name,
        parameters=tuple(parameters),
        implementation=factory,
        provided_type=infer_resource_provided_type(
            factory,
            explicit=provided_type,
        ),
    )


__all__ = [
    "Context",
    "analyze_callable",
    "analyze_class_node",
    "analyze_constructor",
    "analyze_function_node",
    "analyze_injected_method",
    "analyze_resource_factory",
    "infer_resource_provided_type",
    "merge_dependencies",
    "message_type_for",
    "resolve_output",
    "unwrap_marker",
    "unwrap_optional",
]
