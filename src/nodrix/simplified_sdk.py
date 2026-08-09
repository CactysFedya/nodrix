from __future__ import annotations

import inspect
import re
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from types import UnionType
from typing import Any, Generic, TypeVar, Union, get_args, get_origin, get_type_hints

from .cv_types import TYPE_REGISTRY, register_message_type
from .integration import ManagedResource, ResourceContext
from .messages import Message
from .node import Node, NodeContext, SinkNode, SourceNode

T = TypeVar("T")


class Input(Generic[T]):
    """Explicitly mark an annotation as a pipeline input port."""


class Param(Generic[T]):
    """Explicitly mark an annotation as a configuration parameter."""


class Resource(Generic[T]):
    """Request a pipeline-scoped resource binding by argument name."""


Context = NodeContext


class Outputs:
    """Lightweight named multi-output result.

    Subclasses declare annotated fields and may be constructed with keyword
    arguments without also applying ``@dataclass``.
    """

    def __init__(self, **values: Any) -> None:
        fields = getattr(type(self), "__annotations__", {})
        unknown = sorted(set(values) - set(fields))
        missing = sorted(set(fields) - set(values))
        if unknown:
            raise TypeError(f"Unknown output field(s): {', '.join(unknown)}")
        if missing:
            raise TypeError(f"Missing output field(s): {', '.join(missing)}")
        for name, value in values.items():
            setattr(self, name, value)


@dataclass(frozen=True, slots=True)
class PortSpec:
    name: str
    type_id: str
    optional: bool = False


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    annotation: Any
    required: bool
    default: Any = None


@dataclass(frozen=True, slots=True)
class DependencySpec:
    name: str
    kind: str
    annotation: Any


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    name: str
    inputs: tuple[PortSpec, ...]
    outputs: tuple[PortSpec, ...]
    parameters: tuple[ParameterSpec, ...]
    dependencies: tuple[DependencySpec, ...]
    implementation: Any


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


def _snake_case(value: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).replace("-", "_").lower()


def _default_namespace(module_name: str) -> str:
    root = (module_name or "local").split(".", 1)[0]
    if root in {"__main__", "components", "local"}:
        return "local"
    for prefix in ("nodrix_", "plyctl_"):
        if root.startswith(prefix):
            root = root[len(prefix) :]
            break
    return root or "local"


def _unwrap_marker(annotation: Any, marker: type[Any]) -> tuple[bool, Any]:
    if get_origin(annotation) is marker:
        args = get_args(annotation)
        if len(args) != 1:
            raise TypeError(f"{marker.__name__}[T] requires exactly one type argument")
        return True, args[0]
    return False, annotation


def _unwrap_optional(annotation: Any) -> tuple[bool, Any]:
    origin = get_origin(annotation)
    if origin not in (Union, UnionType):
        return False, annotation
    args = get_args(annotation)
    non_none = tuple(item for item in args if item is not type(None))
    if len(non_none) == 1 and len(non_none) != len(args):
        return True, non_none[0]
    return False, annotation


def _message_type_for(annotation: Any) -> str | None:
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


def _resolve_output(annotation: Any, explicit_name: str | None) -> tuple[PortSpec, ...]:
    if annotation in (inspect.Signature.empty, None, type(None)):
        return ()
    if inspect.isclass(annotation) and issubclass(annotation, Outputs):
        annotations = get_type_hints(annotation, include_extras=True)
        if not annotations:
            raise TypeError(f"Outputs subclass {annotation.__name__!r} declares no annotated fields")
        result: list[PortSpec] = []
        for name, item in annotations.items():
            type_id = _message_type_for(item)
            if type_id is None:
                raise TypeError(
                    f"Cannot infer output type for {annotation.__name__}.{name}; "
                    "use a registered @message type or Input-compatible primitive"
                )
            result.append(PortSpec(name, type_id))
        return tuple(result)
    type_id = _message_type_for(annotation)
    if type_id is None:
        raise TypeError(
            f"Cannot infer return type {annotation!r}; use a registered @message type "
            "or a supported primitive"
        )
    return (PortSpec(explicit_name or "output", type_id),)


def _analyze_callable(
    function: Any,
    *,
    component_name: str,
    output_name: str | None,
    localns: Mapping[str, Any] | None = None,
) -> ComponentSpec:
    signature = inspect.signature(function)
    hints = get_type_hints(
        function,
        globalns=getattr(function, "__globals__", None),
        localns=dict(localns or {}),
        include_extras=True,
    )
    inputs: list[PortSpec] = []
    parameters: list[ParameterSpec] = []
    dependencies: list[DependencySpec] = []

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
            dependencies.append(DependencySpec(argument.name, "context", annotation))
            continue

        is_resource, inner = _unwrap_marker(annotation, Resource)
        if is_resource:
            dependencies.append(DependencySpec(argument.name, "resource", inner))
            continue

        is_input, inner = _unwrap_marker(annotation, Input)
        if is_input:
            optional, inner = _unwrap_optional(inner)
            type_id = _message_type_for(inner)
            if type_id is None:
                raise TypeError(f"Cannot infer input type for {argument.name!r}: {inner!r}")
            inputs.append(PortSpec(argument.name, type_id, optional))
            continue

        is_param, inner = _unwrap_marker(annotation, Param)
        if is_param:
            parameters.append(
                ParameterSpec(
                    argument.name,
                    inner,
                    argument.default is inspect.Signature.empty,
                    None if argument.default is inspect.Signature.empty else argument.default,
                )
            )
            continue

        optional, unwrapped = _unwrap_optional(annotation)
        type_id = _message_type_for(unwrapped)
        if type_id is not None and unwrapped not in _PRIMITIVE_TYPES:
            inputs.append(PortSpec(argument.name, type_id, optional))
            continue

        parameters.append(
            ParameterSpec(
                argument.name,
                annotation,
                argument.default is inspect.Signature.empty,
                None if argument.default is inspect.Signature.empty else argument.default,
            )
        )

    outputs = _resolve_output(hints.get("return", signature.return_annotation), output_name)
    return ComponentSpec(
        name=component_name,
        inputs=tuple(inputs),
        outputs=outputs,
        parameters=tuple(parameters),
        dependencies=tuple(dependencies),
        implementation=function,
    )


def _resolve_parameters(spec: ComponentSpec, supplied: Mapping[str, Any] | None) -> dict[str, Any]:
    values = dict(supplied or {})
    known = {item.name for item in spec.parameters}
    unknown = sorted(set(values) - known)
    if unknown:
        raise TypeError(f"Unknown parameter(s) for {spec.name}: {', '.join(unknown)}")
    resolved: dict[str, Any] = {}
    missing: list[str] = []
    for item in spec.parameters:
        if item.name in values:
            resolved[item.name] = values[item.name]
        elif item.required:
            missing.append(item.name)
        else:
            resolved[item.name] = item.default
    if missing:
        raise TypeError(f"Missing required parameter(s) for {spec.name}: {', '.join(missing)}")
    return resolved


def _wrap_message(type_id: str, payload: Any, base: Message | None, source_id: str) -> Message:
    if isinstance(payload, Message):
        if payload.type == type_id:
            return payload
        return payload.with_updates(type=type_id)
    if base is not None:
        return base.with_updates(type=type_id, payload=payload, source_id=source_id or base.source_id)
    return Message(type=type_id, payload=payload, source_id=source_id)


def _wrap_outputs(spec: ComponentSpec, value: Any, inputs: Mapping[str, Message], source_id: str) -> dict[str, Message] | None:
    if not spec.outputs:
        return None
    base = next(iter(inputs.values()), None)
    if len(spec.outputs) == 1:
        output = spec.outputs[0]
        return {output.name: _wrap_message(output.type_id, value, base, source_id)}

    if isinstance(value, Outputs):
        values = {item.name: getattr(value, item.name) for item in spec.outputs}
    elif isinstance(value, Mapping):
        values = dict(value)
    else:
        raise TypeError(f"Node {spec.name!r} must return Outputs or a mapping for multiple outputs")

    expected = {item.name for item in spec.outputs}
    if set(values) != expected:
        missing = sorted(expected - set(values))
        extra = sorted(set(values) - expected)
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if extra:
            detail.append(f"extra={extra}")
        raise TypeError(f"Invalid outputs from {spec.name!r}: {'; '.join(detail)}")
    return {
        item.name: _wrap_message(item.type_id, values[item.name], base, source_id)
        for item in spec.outputs
    }


def _invoke_arguments(instance: Node, spec: ComponentSpec, inputs: Mapping[str, Message]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for port in spec.inputs:
        message = inputs.get(port.name)
        if message is None:
            if port.optional:
                values[port.name] = None
                continue
            raise KeyError(f"Node {spec.name!r} requires input {port.name!r}")
        values[port.name] = message.payload

    values.update(instance._simple_parameters)  # type: ignore[attr-defined]
    for dependency in spec.dependencies:
        if dependency.kind == "context":
            if instance.context is None:
                raise RuntimeError(f"Node {spec.name!r} has not been configured")
            values[dependency.name] = instance.context
        elif dependency.kind == "resource":
            if instance.context is None:
                raise RuntimeError(f"Node {spec.name!r} has not been configured")
            resource = instance.context.binding(dependency.name)
            values[dependency.name] = getattr(resource, "value", resource)
    return values


def _build_function_node(spec: ComponentSpec, function: Any) -> type[Node]:
    base_class: type[Node]
    if not spec.inputs and spec.outputs:
        base_class = SourceNode
    elif spec.inputs and not spec.outputs:
        base_class = SinkNode
    else:
        base_class = Node

    class FunctionNode(base_class):
        input_types = {item.name: item.type_id for item in spec.inputs}
        output_types = {item.name: item.type_id for item in spec.outputs}
        optional_inputs = frozenset(item.name for item in spec.inputs if item.optional)
        __plyctl_component_spec__ = spec
        __plyctl_original__ = function

        def __init__(self, parameters: dict[str, Any] | None = None) -> None:
            super().__init__(parameters)
            self._simple_parameters = _resolve_parameters(spec, parameters)

        def process(self, inputs: dict[str, Message]) -> dict[str, Message] | None | Any:
            arguments = _invoke_arguments(self, spec, inputs)
            value = function(**arguments)
            if inspect.isawaitable(value):
                async def finish() -> dict[str, Message] | None:
                    resolved = await value
                    return _wrap_outputs(spec, resolved, inputs, self.context.name if self.context else "")
                return finish()
            return _wrap_outputs(spec, value, inputs, self.context.name if self.context else "")

    if issubclass(base_class, SourceNode):
        def produce(self: SourceNode) -> Iterator[dict[str, Message]] | AsyncIterator[dict[str, Message]]:
            arguments = _invoke_arguments(self, spec, {})
            produced = function(**arguments)
            source_id = self.context.name if self.context else ""

            if inspect.isasyncgen(produced):
                async def async_stream() -> AsyncIterator[dict[str, Message]]:
                    async for item in produced:
                        wrapped = _wrap_outputs(spec, item, {}, source_id)
                        if wrapped is not None:
                            yield wrapped
                return async_stream()

            if inspect.isawaitable(produced):
                async def async_once() -> AsyncIterator[dict[str, Message]]:
                    item = await produced
                    wrapped = _wrap_outputs(spec, item, {}, source_id)
                    if wrapped is not None:
                        yield wrapped
                return async_once()

            if isinstance(produced, Iterator):
                def stream() -> Iterator[dict[str, Message]]:
                    for item in produced:
                        wrapped = _wrap_outputs(spec, item, {}, source_id)
                        if wrapped is not None:
                            yield wrapped
                return stream()

            wrapped = _wrap_outputs(spec, produced, {}, source_id)
            return iter(()) if wrapped is None else iter((wrapped,))

        FunctionNode.produce = produce  # type: ignore[assignment]

    FunctionNode.__name__ = function.__name__
    FunctionNode.__qualname__ = function.__qualname__
    FunctionNode.__module__ = function.__module__
    FunctionNode.__doc__ = function.__doc__
    return FunctionNode


def node(
    target: Any = None,
    /,
    *,
    name: str | None = None,
    output: str | None = None,
) -> Any:
    """Turn a typed Python function into a Nodrix Node class.

    This first simplified-SDK implementation intentionally supports functions.
    Stateful class adapters are reserved for the next patch so the initial API
    can be tested against real pipelines before lifecycle magic is expanded.
    """

    caller_frame = inspect.currentframe()
    decorator_locals = (
        dict(caller_frame.f_back.f_locals)
        if caller_frame is not None and caller_frame.f_back is not None
        else {}
    )

    if isinstance(target, str):
        if name is not None:
            raise TypeError("node name was provided twice")
        name = target
        target = None

    def decorate(function: Any) -> type[Node]:
        if not inspect.isfunction(function):
            raise TypeError("@node currently supports functions; subclass Node for stateful components")
        namespace = _default_namespace(function.__module__)
        local_name = name or function.__name__
        component_name = local_name if "." in local_name else f"{namespace}.{local_name}"
        spec = _analyze_callable(
            function,
            component_name=component_name,
            output_name=output,
            localns=decorator_locals,
        )
        return _build_function_node(spec, function)

    return decorate if target is None else decorate(target)


def _parse_contract_name(
    cls: type[Any],
    requested: str | None,
    *,
    version: int | None,
    namespace: str | None,
) -> tuple[str, int]:
    namespace = namespace or _default_namespace(cls.__module__)
    requested = requested or _snake_case(cls.__name__)
    match = re.search(r"/v(\d+)$", requested)
    parsed_version = int(match.group(1)) if match else int(version or 1)
    if version is not None and match and int(version) != parsed_version:
        raise ValueError("message version disagrees with the /vN suffix")
    if not match:
        requested = f"{requested}/v{parsed_version}"
    stem = requested[: requested.rfind("/v")]
    if "." not in stem:
        requested = f"{namespace}.{requested}"
    return requested, parsed_version


def message(
    target: Any = None,
    /,
    *,
    name: str | None = None,
    version: int | None = None,
    namespace: str | None = None,
    compatible_versions: tuple[int, ...] | None = None,
    replace: bool = False,
) -> Any:
    """Register a Python payload class as a typed Nodrix message contract."""

    if isinstance(target, str):
        if name is not None:
            raise TypeError("message name was provided twice")
        name = target
        target = None

    def decorate(cls: type[T]) -> type[T]:
        if not inspect.isclass(cls):
            raise TypeError("@message can only decorate classes")
        type_id, schema_version = _parse_contract_name(
            cls,
            name,
            version=version,
            namespace=namespace,
        )
        register_message_type(
            type_id,
            cls,
            version=schema_version,
            compatible_versions=compatible_versions,
            replace=replace,
        )
        setattr(cls, "__plyctl_message_type__", type_id)
        setattr(cls, "__plyctl_message_version__", schema_version)
        return cls

    return decorate if target is None else decorate(target)


def resource(
    target: Any = None,
    /,
    *,
    name: str | None = None,
) -> Any:
    """Turn a factory or generator function into a pipeline-scoped resource."""

    if isinstance(target, str):
        if name is not None:
            raise TypeError("resource name was provided twice")
        name = target
        target = None

    def decorate(factory: Any) -> type[ManagedResource]:
        if not inspect.isfunction(factory):
            raise TypeError("@resource currently supports functions")
        namespace = _default_namespace(factory.__module__)
        local_name = name or factory.__name__
        component_name = local_name if "." in local_name else f"{namespace}.{local_name}"
        signature = inspect.signature(factory)
        hints = get_type_hints(factory, include_extras=True)
        parameter_defs: list[ParameterSpec] = []
        for argument in signature.parameters.values():
            annotation = hints.get(argument.name, argument.annotation)
            if annotation is inspect.Signature.empty:
                raise TypeError(
                    f"Cannot infer resource parameter {argument.name!r} in {component_name!r}; "
                    "add a type annotation"
                )
            parameter_defs.append(
                ParameterSpec(
                    argument.name,
                    annotation,
                    argument.default is inspect.Signature.empty,
                    None if argument.default is inspect.Signature.empty else argument.default,
                )
            )
        spec = ComponentSpec(component_name, (), (), tuple(parameter_defs), (), factory)

        class FunctionResource(ManagedResource):
            __plyctl_component_spec__ = spec
            __plyctl_original__ = factory

            def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
                super().__init__(parameters)
                self._simple_parameters = _resolve_parameters(spec, parameters)
                self.value: Any = None
                self._generator: Any = None

            def open(self, context: ResourceContext) -> Any:
                super().open(context)
                created = factory(**self._simple_parameters)
                if inspect.isasyncgen(created):
                    async def open_async() -> Any:
                        try:
                            self.value = await created.__anext__()
                        except StopAsyncIteration as exc:
                            raise RuntimeError(f"Resource {component_name!r} yielded no value") from exc
                        self._generator = created
                        return self.value
                    return open_async()
                if inspect.isawaitable(created):
                    async def open_awaitable() -> Any:
                        self.value = await created
                        return self.value
                    return open_awaitable()
                if isinstance(created, Iterator):
                    try:
                        self.value = next(created)
                    except StopIteration as exc:
                        raise RuntimeError(f"Resource {component_name!r} yielded no value") from exc
                    self._generator = created
                    return self.value
                self.value = created
                return self.value

            def close(self) -> Any:
                generator = self._generator
                self._generator = None
                self.value = None
                if inspect.isasyncgen(generator):
                    async def close_async() -> None:
                        try:
                            await generator.__anext__()
                        except StopAsyncIteration:
                            pass
                        else:
                            raise RuntimeError(f"Resource {component_name!r} yielded more than once")
                        finally:
                            await generator.aclose()
                            super(FunctionResource, self).close()
                    return close_async()
                if isinstance(generator, Iterator):
                    try:
                        next(generator)
                    except StopIteration:
                        pass
                    else:
                        raise RuntimeError(f"Resource {component_name!r} yielded more than once")
                return super().close()

        FunctionResource.__name__ = factory.__name__
        FunctionResource.__qualname__ = factory.__qualname__
        FunctionResource.__module__ = factory.__module__
        FunctionResource.__doc__ = factory.__doc__
        return FunctionResource

    return decorate if target is None else decorate(target)


__all__ = [
    "ComponentSpec",
    "Context",
    "DependencySpec",
    "Input",
    "Outputs",
    "Param",
    "ParameterSpec",
    "PortSpec",
    "Resource",
    "message",
    "node",
    "resource",
]
