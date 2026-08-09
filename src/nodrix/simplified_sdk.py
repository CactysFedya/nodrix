from __future__ import annotations

import inspect
import re
from contextvars import ContextVar
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from types import UnionType
from typing import Any, Generic, TypeVar, Union, get_args, get_origin, get_type_hints

from .cv_types import TYPE_REGISTRY, register_message_type
from .integration import ManagedResource, ResourceContext
from .lifecycle import LifecycleState
from .messages import Message
from .node import Node, NodeContext, SinkNode, SourceNode

T = TypeVar("T")

_PACKAGE_NAMESPACE_OVERRIDE: ContextVar[str | None] = ContextVar(
    "plyctl_package_namespace", default=None
)


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
    override = _PACKAGE_NAMESPACE_OVERRIDE.get()
    if override:
        return override
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


def _analyze_constructor(
    cls: type[Any],
    *,
    component_name: str,
    localns: Mapping[str, Any] | None = None,
) -> ComponentSpec:
    initializer = cls.__dict__.get("__init__")
    if initializer is None:
        return ComponentSpec(component_name, (), (), (), (), cls)

    signature = inspect.signature(initializer)
    hints = get_type_hints(
        initializer,
        globalns=getattr(initializer, "__globals__", None),
        localns=dict(localns or {}),
        include_extras=True,
    )
    parameters: list[ParameterSpec] = []
    dependencies: list[DependencySpec] = []

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
            dependencies.append(DependencySpec(argument.name, "context", annotation))
            continue
        is_resource, inner = _unwrap_marker(annotation, Resource)
        if is_resource:
            dependencies.append(DependencySpec(argument.name, "resource", inner))
            continue
        is_input, _ = _unwrap_marker(annotation, Input)
        if is_input:
            raise TypeError(
                f"Stateful node {component_name!r} constructor argument {argument.name!r} "
                "cannot be Input[T]; pipeline inputs belong in process()"
            )
        is_param, inner = _unwrap_marker(annotation, Param)
        parameters.append(
            ParameterSpec(
                argument.name,
                inner if is_param else annotation,
                argument.default is inspect.Signature.empty,
                None if argument.default is inspect.Signature.empty else argument.default,
            )
        )

    return ComponentSpec(
        component_name,
        (),
        (),
        tuple(parameters),
        tuple(dependencies),
        cls,
    )


def _analyze_injected_method(
    method: Any | None,
    *,
    component_name: str,
    phase: str,
    localns: Mapping[str, Any] | None = None,
) -> tuple[DependencySpec, ...]:
    if method is None:
        return ()
    signature = inspect.signature(method)
    hints = get_type_hints(
        method,
        globalns=getattr(method, "__globals__", None),
        localns=dict(localns or {}),
        include_extras=True,
    )
    dependencies: list[DependencySpec] = []
    for argument in signature.parameters.values():
        if argument.name in {"self", "cls"}:
            continue
        annotation = hints.get(argument.name, argument.annotation)
        if annotation is NodeContext or annotation is Context:
            dependencies.append(DependencySpec(argument.name, "context", annotation))
            continue
        is_resource, inner = _unwrap_marker(annotation, Resource)
        if is_resource:
            dependencies.append(DependencySpec(argument.name, "resource", inner))
            continue
        raise TypeError(
            f"Stateful node {component_name!r} {phase}() argument {argument.name!r} "
            "must be Context or Resource[T]"
        )
    return tuple(dependencies)


def _merge_dependencies(*groups: tuple[DependencySpec, ...]) -> tuple[DependencySpec, ...]:
    merged: list[DependencySpec] = []
    seen: set[tuple[str, str, Any]] = set()
    for group in groups:
        for item in group:
            key = (item.name, item.kind, item.annotation)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return tuple(merged)


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


def _dependency_arguments(
    instance: Node,
    dependencies: tuple[DependencySpec, ...],
    *,
    component_name: str,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for dependency in dependencies:
        if instance.context is None:
            raise RuntimeError(f"Node {component_name!r} has not been configured")
        if dependency.kind == "context":
            values[dependency.name] = instance.context
        elif dependency.kind == "resource":
            resource = instance.context.binding(dependency.name)
            values[dependency.name] = getattr(resource, "value", resource)
    return values


def _invoke_arguments(
    instance: Node,
    spec: ComponentSpec,
    inputs: Mapping[str, Message],
    *,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for port in spec.inputs:
        message = inputs.get(port.name)
        if message is None:
            if port.optional:
                values[port.name] = None
                continue
            raise KeyError(f"Node {spec.name!r} requires input {port.name!r}")
        values[port.name] = message.payload

    if parameters is None:
        values.update(instance._simple_parameters)  # type: ignore[attr-defined]
    else:
        values.update(parameters)
    values.update(
        _dependency_arguments(
            instance,
            spec.dependencies,
            component_name=spec.name,
        )
    )
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

    if not issubclass(base_class, SourceNode):
        if inspect.iscoroutinefunction(function):
            async def process_async(
                self: Node,
                inputs: dict[str, Message],
            ) -> dict[str, Message] | None:
                arguments = _invoke_arguments(self, spec, inputs)
                value = await function(**arguments)
                return _wrap_outputs(
                    spec,
                    value,
                    inputs,
                    self.context.name if self.context else "",
                )

            FunctionNode.process = process_async  # type: ignore[assignment]
        else:
            def process_sync(
                self: Node,
                inputs: dict[str, Message],
            ) -> dict[str, Message] | None:
                arguments = _invoke_arguments(self, spec, inputs)
                value = function(**arguments)
                if inspect.isawaitable(value):
                    raise TypeError(
                        f"Node {spec.name!r} returned an awaitable from a synchronous function; "
                        "declare the node with 'async def'"
                    )
                return _wrap_outputs(
                    spec,
                    value,
                    inputs,
                    self.context.name if self.context else "",
                )

            FunctionNode.process = process_sync  # type: ignore[assignment]

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


def _build_class_node(
    component_spec: ComponentSpec,
    constructor_spec: ComponentSpec,
    process_spec: ComponentSpec,
    user_class: type[Any],
    lifecycle_dependencies: Mapping[str, tuple[DependencySpec, ...]],
) -> type[Node]:
    base_class: type[Node]
    if not process_spec.inputs and process_spec.outputs:
        base_class = SourceNode
    elif process_spec.inputs and not process_spec.outputs:
        base_class = SinkNode
    else:
        base_class = Node

    user_process = getattr(user_class, "process")
    user_start = user_class.__dict__.get("start")
    user_drain = user_class.__dict__.get("drain")
    user_stop = user_class.__dict__.get("stop")
    user_health = user_class.__dict__.get("health")

    class StatefulNode(base_class):
        input_types = {item.name: item.type_id for item in process_spec.inputs}
        output_types = {item.name: item.type_id for item in process_spec.outputs}
        optional_inputs = frozenset(item.name for item in process_spec.inputs if item.optional)
        __plyctl_component_spec__ = component_spec
        __plyctl_constructor_spec__ = constructor_spec
        __plyctl_process_spec__ = process_spec
        __plyctl_original__ = user_class

        def __init__(self, parameters: dict[str, Any] | None = None) -> None:
            super().__init__(parameters)
            self._simple_parameters = _resolve_parameters(constructor_spec, parameters)
            self._simple_instance: Any | None = None
            if not constructor_spec.dependencies:
                self._simple_instance = user_class(**self._simple_parameters)

        @property
        def implementation(self) -> Any | None:
            """Return the wrapped user object after it has been constructed."""

            return self._simple_instance

        def _ensure_instance(self) -> Any:
            if self._simple_instance is None:
                arguments = dict(self._simple_parameters)
                arguments.update(
                    _dependency_arguments(
                        self,
                        constructor_spec.dependencies,
                        component_name=component_spec.name,
                    )
                )
                self._simple_instance = user_class(**arguments)
            return self._simple_instance

        def open(self, context: NodeContext) -> Any:
            self.context = context
            self._ensure_instance()
            return None

        def start(self) -> Any:
            implementation = self._ensure_instance()
            if user_start is None:
                return super().start()
            arguments = _dependency_arguments(
                self,
                lifecycle_dependencies["start"],
                component_name=component_spec.name,
            )
            result = implementation.start(**arguments)
            if inspect.isawaitable(result):
                async def finish_start() -> Any:
                    resolved = await result
                    self._lifecycle.transition(LifecycleState.RUNNING)
                    return resolved

                return finish_start()
            self._lifecycle.transition(LifecycleState.RUNNING)
            return result

        def stop(self) -> Any:
            self._lifecycle.transition(LifecycleState.STOPPING)
            implementation = self._simple_instance
            if implementation is None or user_stop is None:
                self._lifecycle.transition(LifecycleState.STOPPED)
                return None
            arguments = _dependency_arguments(
                self,
                lifecycle_dependencies["stop"],
                component_name=component_spec.name,
            )
            try:
                result = implementation.stop(**arguments)
            except BaseException:
                self._lifecycle.transition(LifecycleState.STOPPED)
                raise
            if inspect.isawaitable(result):
                async def finish_stop() -> Any:
                    try:
                        return await result
                    finally:
                        self._lifecycle.transition(LifecycleState.STOPPED)

                return finish_stop()
            self._lifecycle.transition(LifecycleState.STOPPED)
            return result

        def health(self) -> dict[str, Any]:
            base = super().health()
            implementation = self._simple_instance
            if implementation is None or user_health is None:
                return base
            arguments = _dependency_arguments(
                self,
                lifecycle_dependencies["health"],
                component_name=component_spec.name,
            )
            details = implementation.health(**arguments)
            if inspect.isawaitable(details):
                raise TypeError(
                    f"Stateful node {component_spec.name!r} health() must be synchronous"
                )
            if details is None:
                return base
            if not isinstance(details, Mapping):
                raise TypeError(
                    f"Stateful node {component_spec.name!r} health() must return a mapping or None"
                )
            return {**base, "details": dict(details)}

    if issubclass(base_class, SourceNode):
        def produce(
            self: SourceNode,
        ) -> Iterator[dict[str, Message]] | AsyncIterator[dict[str, Message]]:
            implementation = self._ensure_instance()  # type: ignore[attr-defined]
            arguments = _invoke_arguments(self, process_spec, {}, parameters={})
            produced = implementation.process(**arguments)
            source_id = self.context.name if self.context else ""

            if inspect.isasyncgen(produced):
                async def async_stream() -> AsyncIterator[dict[str, Message]]:
                    async for item in produced:
                        wrapped = _wrap_outputs(process_spec, item, {}, source_id)
                        if wrapped is not None:
                            yield wrapped

                return async_stream()
            if inspect.isawaitable(produced):
                async def async_once() -> AsyncIterator[dict[str, Message]]:
                    item = await produced
                    wrapped = _wrap_outputs(process_spec, item, {}, source_id)
                    if wrapped is not None:
                        yield wrapped

                return async_once()
            if isinstance(produced, Iterator):
                def stream() -> Iterator[dict[str, Message]]:
                    for item in produced:
                        wrapped = _wrap_outputs(process_spec, item, {}, source_id)
                        if wrapped is not None:
                            yield wrapped

                return stream()
            wrapped = _wrap_outputs(process_spec, produced, {}, source_id)
            return iter(()) if wrapped is None else iter((wrapped,))

        StatefulNode.produce = produce  # type: ignore[assignment]
    elif inspect.iscoroutinefunction(user_process):
        async def process_async(
            self: Node,
            inputs: dict[str, Message],
        ) -> dict[str, Message] | None:
            implementation = self._ensure_instance()  # type: ignore[attr-defined]
            arguments = _invoke_arguments(self, process_spec, inputs, parameters={})
            value = await implementation.process(**arguments)
            return _wrap_outputs(
                process_spec,
                value,
                inputs,
                self.context.name if self.context else "",
            )

        StatefulNode.process = process_async  # type: ignore[assignment]
    else:
        def process_sync(
            self: Node,
            inputs: dict[str, Message],
        ) -> dict[str, Message] | None:
            implementation = self._ensure_instance()  # type: ignore[attr-defined]
            arguments = _invoke_arguments(self, process_spec, inputs, parameters={})
            value = implementation.process(**arguments)
            if inspect.isawaitable(value):
                raise TypeError(
                    f"Stateful node {component_spec.name!r} process() returned an awaitable "
                    "from a synchronous method; declare process() with 'async def'"
                )
            return _wrap_outputs(
                process_spec,
                value,
                inputs,
                self.context.name if self.context else "",
            )

        StatefulNode.process = process_sync  # type: ignore[assignment]

    if user_drain is not None:
        if inspect.iscoroutinefunction(user_drain):
            async def flush_async(self: Node) -> dict[str, Message] | None:
                implementation = self._ensure_instance()  # type: ignore[attr-defined]
                arguments = _dependency_arguments(
                    self,
                    lifecycle_dependencies["drain"],
                    component_name=component_spec.name,
                )
                value = await implementation.drain(**arguments)
                return _wrap_outputs(
                    process_spec,
                    value,
                    {},
                    self.context.name if self.context else "",
                )

            StatefulNode.flush = flush_async  # type: ignore[assignment]
        else:
            def flush_sync(self: Node) -> dict[str, Message] | None:
                implementation = self._ensure_instance()  # type: ignore[attr-defined]
                arguments = _dependency_arguments(
                    self,
                    lifecycle_dependencies["drain"],
                    component_name=component_spec.name,
                )
                value = implementation.drain(**arguments)
                if inspect.isawaitable(value):
                    raise TypeError(
                        f"Stateful node {component_spec.name!r} drain() returned an awaitable "
                        "from a synchronous method; declare drain() with 'async def'"
                    )
                return _wrap_outputs(
                    process_spec,
                    value,
                    {},
                    self.context.name if self.context else "",
                )

            StatefulNode.flush = flush_sync  # type: ignore[assignment]

    StatefulNode.__name__ = user_class.__name__
    StatefulNode.__qualname__ = user_class.__qualname__
    StatefulNode.__module__ = user_class.__module__
    StatefulNode.__doc__ = user_class.__doc__
    return StatefulNode


def _decorate_class_node(
    user_class: type[Any],
    *,
    name: str | None,
    output: str | None,
    decorator_locals: Mapping[str, Any],
) -> type[Node]:
    if issubclass(user_class, Node):
        raise TypeError(
            "@node class syntax is for plain Python classes; existing Node subclasses "
            "already use the advanced SDK directly"
        )
    user_process = getattr(user_class, "process", None)
    if user_process is None or not callable(user_process):
        raise TypeError(f"@node class {user_class.__name__!r} must define process()")

    namespace = _default_namespace(user_class.__module__)
    local_name = name or _snake_case(user_class.__name__)
    component_name = local_name if "." in local_name else f"{namespace}.{local_name}"
    localns = {**dict(decorator_locals), user_class.__name__: user_class}

    constructor_spec = _analyze_constructor(
        user_class,
        component_name=component_name,
        localns=localns,
    )
    process_spec = _analyze_callable(
        user_process,
        component_name=component_name,
        output_name=output,
        localns=localns,
    )
    if process_spec.parameters:
        names = ", ".join(item.name for item in process_spec.parameters)
        raise TypeError(
            f"Stateful node {component_name!r} process() contains configuration parameter(s): "
            f"{names}. Move configuration to __init__(); use Input[T] for primitive ports."
        )
    if process_spec.inputs and (
        inspect.isgeneratorfunction(user_process) or inspect.isasyncgenfunction(user_process)
    ):
        raise TypeError(
            f"Stateful node {component_name!r} process() cannot be a generator when it has inputs"
        )

    lifecycle_dependencies = {
        phase: _analyze_injected_method(
            user_class.__dict__.get(phase),
            component_name=component_name,
            phase=phase,
            localns=localns,
        )
        for phase in ("start", "drain", "stop", "health")
    }
    if inspect.iscoroutinefunction(user_class.__dict__.get("health")):
        raise TypeError(f"Stateful node {component_name!r} health() must be synchronous")

    dependencies = _merge_dependencies(
        constructor_spec.dependencies,
        process_spec.dependencies,
        *lifecycle_dependencies.values(),
    )
    component_spec = ComponentSpec(
        name=component_name,
        inputs=process_spec.inputs,
        outputs=process_spec.outputs,
        parameters=constructor_spec.parameters,
        dependencies=dependencies,
        implementation=user_class,
    )
    return _build_class_node(
        component_spec,
        constructor_spec,
        process_spec,
        user_class,
        lifecycle_dependencies,
    )


def node(
    target: Any = None,
    /,
    *,
    name: str | None = None,
    output: str | None = None,
) -> Any:
    """Turn a typed Python function or stateful class into a Nodrix Node class.

    Functions remain the smallest SDK surface. Plain classes add persistent
    state: ``__init__`` defines configuration/dependencies, ``process`` defines
    ports, and optional ``start``/``drain``/``stop``/``health`` methods extend
    the runtime lifecycle without requiring inheritance from :class:`Node`.
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

    def decorate(component: Any) -> type[Node]:
        if inspect.isclass(component):
            return _decorate_class_node(
                component,
                name=name,
                output=output,
                decorator_locals=decorator_locals,
            )
        if inspect.isfunction(component):
            namespace = _default_namespace(component.__module__)
            local_name = name or component.__name__
            component_name = local_name if "." in local_name else f"{namespace}.{local_name}"
            spec = _analyze_callable(
                component,
                component_name=component_name,
                output_name=output,
                localns=decorator_locals,
            )
            return _build_function_node(spec, component)
        raise TypeError("@node can decorate typed functions or plain Python classes")

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
