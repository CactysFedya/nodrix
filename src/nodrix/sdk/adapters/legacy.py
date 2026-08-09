"""Compatibility lowering from neutral SDK definitions to the 2.x runtime."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any

from ...integration import ManagedResource, ResourceContext
from ...lifecycle import LifecycleState
from ...messages import Message
from ...node import Node, NodeContext, SinkNode, SourceNode
from ..definitions import (
    CallableDefinition,
    DependencyDefinition,
    NodeDefinition,
    ParameterDefinition,
    ResourceDefinition,
)
from ..typing import Outputs


def resolve_parameters(
    parameters: tuple[ParameterDefinition, ...],
    supplied: Mapping[str, Any] | None,
    *,
    component_name: str,
) -> dict[str, Any]:
    values = dict(supplied or {})
    known = {item.name for item in parameters}
    unknown = sorted(set(values) - known)
    if unknown:
        raise TypeError(f"Unknown parameter(s) for {component_name}: {', '.join(unknown)}")
    resolved: dict[str, Any] = {}
    missing: list[str] = []
    for item in parameters:
        if item.name in values:
            resolved[item.name] = values[item.name]
        elif item.required:
            missing.append(item.name)
        else:
            resolved[item.name] = item.default
    if missing:
        raise TypeError(
            f"Missing required parameter(s) for {component_name}: {', '.join(missing)}"
        )
    return resolved


def _wrap_message(type_id: str, payload: Any, base: Message | None, source_id: str) -> Message:
    if isinstance(payload, Message):
        if payload.type == type_id:
            return payload
        return payload.with_updates(type=type_id)
    if base is not None:
        return base.with_updates(type=type_id, payload=payload, source_id=source_id or base.source_id)
    return Message(type=type_id, payload=payload, source_id=source_id)


def wrap_outputs(
    definition: NodeDefinition | CallableDefinition,
    value: Any,
    inputs: Mapping[str, Message],
    source_id: str,
) -> dict[str, Message] | None:
    if not definition.outputs:
        return None
    base = next(iter(inputs.values()), None)
    if len(definition.outputs) == 1:
        output = definition.outputs[0]
        return {output.name: _wrap_message(output.type_id, value, base, source_id)}
    if isinstance(value, Outputs):
        values = {item.name: getattr(value, item.name) for item in definition.outputs}
    elif isinstance(value, Mapping):
        values = dict(value)
    else:
        raise TypeError(
            f"Node {definition.name!r} must return Outputs or a mapping for multiple outputs"
        )
    expected = {item.name for item in definition.outputs}
    if set(values) != expected:
        missing = sorted(expected - set(values))
        extra = sorted(set(values) - expected)
        detail: list[str] = []
        if missing:
            detail.append(f"missing={missing}")
        if extra:
            detail.append(f"extra={extra}")
        raise TypeError(f"Invalid outputs from {definition.name!r}: {'; '.join(detail)}")
    return {
        item.name: _wrap_message(item.type_id, values[item.name], base, source_id)
        for item in definition.outputs
    }


def dependency_arguments(
    instance: Node,
    dependencies: tuple[DependencyDefinition, ...],
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


def invoke_arguments(
    instance: Node,
    definition: NodeDefinition | CallableDefinition,
    inputs: Mapping[str, Message],
    *,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for port in definition.inputs:
        message = inputs.get(port.name)
        if message is None:
            if port.optional:
                values[port.name] = None
                continue
            raise KeyError(f"Node {definition.name!r} requires input {port.name!r}")
        values[port.name] = message.payload
    if parameters is None:
        values.update(instance._simple_parameters)  # type: ignore[attr-defined]
    else:
        values.update(parameters)
    values.update(
        dependency_arguments(
            instance,
            definition.dependencies,
            component_name=definition.name,
        )
    )
    return values


def _runtime_base(definition: NodeDefinition | CallableDefinition) -> type[Node]:
    if not definition.inputs and definition.outputs:
        return SourceNode
    if definition.inputs and not definition.outputs:
        return SinkNode
    return Node


def _build_function_node(definition: NodeDefinition) -> type[Node]:
    function = definition.implementation
    base_class = _runtime_base(definition)

    class FunctionNode(base_class):
        input_types = {item.name: item.type_id for item in definition.inputs}
        output_types = {item.name: item.type_id for item in definition.outputs}
        optional_inputs = frozenset(item.name for item in definition.inputs if item.optional)
        __plyctl_definition__ = definition
        __plyctl_component_spec__ = definition
        __plyctl_original__ = function

        def __init__(self, parameters: dict[str, Any] | None = None) -> None:
            super().__init__(parameters)
            self._simple_parameters = resolve_parameters(
                definition.parameters,
                parameters,
                component_name=definition.name,
            )

    if not issubclass(base_class, SourceNode):
        if inspect.iscoroutinefunction(function):
            async def process_async(
                self: Node,
                inputs: dict[str, Message],
            ) -> dict[str, Message] | None:
                arguments = invoke_arguments(self, definition, inputs)
                value = await function(**arguments)
                return wrap_outputs(
                    definition,
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
                arguments = invoke_arguments(self, definition, inputs)
                value = function(**arguments)
                if inspect.isawaitable(value):
                    raise TypeError(
                        f"Node {definition.name!r} returned an awaitable from a synchronous "
                        "function; declare the node with 'async def'"
                    )
                return wrap_outputs(
                    definition,
                    value,
                    inputs,
                    self.context.name if self.context else "",
                )

            FunctionNode.process = process_sync  # type: ignore[assignment]

    if issubclass(base_class, SourceNode):
        def produce(
            self: SourceNode,
        ) -> Iterator[dict[str, Message]] | AsyncIterator[dict[str, Message]]:
            arguments = invoke_arguments(self, definition, {})
            produced = function(**arguments)
            source_id = self.context.name if self.context else ""
            if inspect.isasyncgen(produced):
                async def async_stream() -> AsyncIterator[dict[str, Message]]:
                    async for item in produced:
                        wrapped = wrap_outputs(definition, item, {}, source_id)
                        if wrapped is not None:
                            yield wrapped
                return async_stream()
            if inspect.isawaitable(produced):
                async def async_once() -> AsyncIterator[dict[str, Message]]:
                    item = await produced
                    wrapped = wrap_outputs(definition, item, {}, source_id)
                    if wrapped is not None:
                        yield wrapped
                return async_once()
            if isinstance(produced, Iterator):
                def stream() -> Iterator[dict[str, Message]]:
                    for item in produced:
                        wrapped = wrap_outputs(definition, item, {}, source_id)
                        if wrapped is not None:
                            yield wrapped
                return stream()
            wrapped = wrap_outputs(definition, produced, {}, source_id)
            return iter(()) if wrapped is None else iter((wrapped,))

        FunctionNode.produce = produce  # type: ignore[assignment]

    FunctionNode.__name__ = function.__name__
    FunctionNode.__qualname__ = function.__qualname__
    FunctionNode.__module__ = function.__module__
    FunctionNode.__doc__ = function.__doc__
    return FunctionNode


def _build_class_node(definition: NodeDefinition) -> type[Node]:
    constructor = definition.constructor
    process = definition.process
    if constructor is None or process is None:
        raise TypeError(f"Stateful node definition {definition.name!r} is incomplete")
    user_class = definition.implementation
    base_class = _runtime_base(process)
    lifecycle_dependencies = definition.lifecycle_dependencies
    user_process = getattr(user_class, "process")
    user_start = user_class.__dict__.get("start")
    user_drain = user_class.__dict__.get("drain")
    user_stop = user_class.__dict__.get("stop")
    user_health = user_class.__dict__.get("health")

    class StatefulNode(base_class):
        input_types = {item.name: item.type_id for item in process.inputs}
        output_types = {item.name: item.type_id for item in process.outputs}
        optional_inputs = frozenset(item.name for item in process.inputs if item.optional)
        __plyctl_definition__ = definition
        __plyctl_component_spec__ = definition
        __plyctl_constructor_spec__ = constructor
        __plyctl_process_spec__ = process
        __plyctl_original__ = user_class

        def __init__(self, parameters: dict[str, Any] | None = None) -> None:
            super().__init__(parameters)
            self._simple_parameters = resolve_parameters(
                constructor.parameters,
                parameters,
                component_name=definition.name,
            )
            self._simple_instance: Any | None = None
            if not constructor.dependencies:
                self._simple_instance = user_class(**self._simple_parameters)

        @property
        def implementation(self) -> Any | None:
            return self._simple_instance

        def _ensure_instance(self) -> Any:
            if self._simple_instance is None:
                arguments = dict(self._simple_parameters)
                arguments.update(
                    dependency_arguments(
                        self,
                        constructor.dependencies,
                        component_name=definition.name,
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
            arguments = dependency_arguments(
                self,
                lifecycle_dependencies.get("start", ()),
                component_name=definition.name,
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
            arguments = dependency_arguments(
                self,
                lifecycle_dependencies.get("stop", ()),
                component_name=definition.name,
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
            arguments = dependency_arguments(
                self,
                lifecycle_dependencies.get("health", ()),
                component_name=definition.name,
            )
            details = implementation.health(**arguments)
            if inspect.isawaitable(details):
                raise TypeError(f"Stateful node {definition.name!r} health() must be synchronous")
            if details is None:
                return base
            if not isinstance(details, Mapping):
                raise TypeError(
                    f"Stateful node {definition.name!r} health() must return a mapping or None"
                )
            return {**base, "details": dict(details)}

    if issubclass(base_class, SourceNode):
        def produce(
            self: SourceNode,
        ) -> Iterator[dict[str, Message]] | AsyncIterator[dict[str, Message]]:
            implementation = self._ensure_instance()  # type: ignore[attr-defined]
            arguments = invoke_arguments(self, process, {}, parameters={})
            produced = implementation.process(**arguments)
            source_id = self.context.name if self.context else ""
            if inspect.isasyncgen(produced):
                async def async_stream() -> AsyncIterator[dict[str, Message]]:
                    async for item in produced:
                        wrapped = wrap_outputs(process, item, {}, source_id)
                        if wrapped is not None:
                            yield wrapped
                return async_stream()
            if inspect.isawaitable(produced):
                async def async_once() -> AsyncIterator[dict[str, Message]]:
                    item = await produced
                    wrapped = wrap_outputs(process, item, {}, source_id)
                    if wrapped is not None:
                        yield wrapped
                return async_once()
            if isinstance(produced, Iterator):
                def stream() -> Iterator[dict[str, Message]]:
                    for item in produced:
                        wrapped = wrap_outputs(process, item, {}, source_id)
                        if wrapped is not None:
                            yield wrapped
                return stream()
            wrapped = wrap_outputs(process, produced, {}, source_id)
            return iter(()) if wrapped is None else iter((wrapped,))

        StatefulNode.produce = produce  # type: ignore[assignment]
    elif inspect.iscoroutinefunction(user_process):
        async def process_async(
            self: Node,
            inputs: dict[str, Message],
        ) -> dict[str, Message] | None:
            implementation = self._ensure_instance()  # type: ignore[attr-defined]
            arguments = invoke_arguments(self, process, inputs, parameters={})
            value = await implementation.process(**arguments)
            return wrap_outputs(
                process,
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
            arguments = invoke_arguments(self, process, inputs, parameters={})
            value = implementation.process(**arguments)
            if inspect.isawaitable(value):
                raise TypeError(
                    f"Stateful node {definition.name!r} process() returned an awaitable from a "
                    "synchronous method; declare process() with 'async def'"
                )
            return wrap_outputs(
                process,
                value,
                inputs,
                self.context.name if self.context else "",
            )

        StatefulNode.process = process_sync  # type: ignore[assignment]

    if user_drain is not None:
        if inspect.iscoroutinefunction(user_drain):
            async def flush_async(self: Node) -> dict[str, Message] | None:
                implementation = self._ensure_instance()  # type: ignore[attr-defined]
                arguments = dependency_arguments(
                    self,
                    lifecycle_dependencies.get("drain", ()),
                    component_name=definition.name,
                )
                value = await implementation.drain(**arguments)
                return wrap_outputs(
                    process,
                    value,
                    {},
                    self.context.name if self.context else "",
                )

            StatefulNode.flush = flush_async  # type: ignore[assignment]
        else:
            def flush_sync(self: Node) -> dict[str, Message] | None:
                implementation = self._ensure_instance()  # type: ignore[attr-defined]
                arguments = dependency_arguments(
                    self,
                    lifecycle_dependencies.get("drain", ()),
                    component_name=definition.name,
                )
                value = implementation.drain(**arguments)
                if inspect.isawaitable(value):
                    raise TypeError(
                        f"Stateful node {definition.name!r} drain() returned an awaitable from a "
                        "synchronous method; declare drain() with 'async def'"
                    )
                return wrap_outputs(
                    process,
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


def build_node(definition: NodeDefinition) -> type[Node]:
    if inspect.isclass(definition.implementation):
        return _build_class_node(definition)
    return _build_function_node(definition)


def build_resource(definition: ResourceDefinition) -> type[ManagedResource]:
    factory = definition.implementation

    class FunctionResource(ManagedResource):
        __plyctl_definition__ = definition
        __plyctl_component_spec__ = definition
        __plyctl_original__ = factory

        def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
            super().__init__(parameters)
            self._simple_parameters = resolve_parameters(
                definition.parameters,
                parameters,
                component_name=definition.name,
            )
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
                        raise RuntimeError(f"Resource {definition.name!r} yielded no value") from exc
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
                    raise RuntimeError(f"Resource {definition.name!r} yielded no value") from exc
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
                        raise RuntimeError(f"Resource {definition.name!r} yielded more than once")
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
                    raise RuntimeError(f"Resource {definition.name!r} yielded more than once")
            return super().close()

    FunctionResource.__name__ = factory.__name__
    FunctionResource.__qualname__ = factory.__qualname__
    FunctionResource.__module__ = factory.__module__
    FunctionResource.__doc__ = factory.__doc__
    return FunctionResource


__all__ = [
    "build_node",
    "build_resource",
    "dependency_arguments",
    "invoke_arguments",
    "resolve_parameters",
    "wrap_outputs",
]
