"""Public typing-first decorators.

Decorators describe Python components first, then lower those definitions through
an adapter.  The current adapter targets the existing 2.x runtime and is a
compatibility implementation rather than the canonical component model.
"""

from __future__ import annotations

import inspect
import re
from typing import Any, TypeVar

from ..cv_types import register_message_type
from ..node import Node, NodeContext
from .adapters.legacy import build_node, build_resource
from .definitions import MessageDefinition
from .inspection import analyze_class_node, analyze_function_node, analyze_resource_factory
from .namespace import default_namespace, snake_case

T = TypeVar("T")
Context = NodeContext


def node(
    target: Any = None,
    /,
    *,
    name: str | None = None,
    output: str | None = None,
) -> Any:
    """Turn a typed Python function or stateful class into a runtime Node class."""

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
            if issubclass(component, Node):
                raise TypeError(
                    "@node class syntax is for plain Python classes; existing Node subclasses "
                    "already use the advanced SDK directly"
                )
            namespace = default_namespace(component.__module__)
            local_name = name or snake_case(component.__name__)
            component_name = local_name if "." in local_name else f"{namespace}.{local_name}"
            definition = analyze_class_node(
                component,
                component_name=component_name,
                output_name=output,
                localns=decorator_locals,
            )
            return build_node(definition)
        if inspect.isfunction(component):
            namespace = default_namespace(component.__module__)
            local_name = name or component.__name__
            component_name = local_name if "." in local_name else f"{namespace}.{local_name}"
            definition = analyze_function_node(
                component,
                component_name=component_name,
                output_name=output,
                localns=decorator_locals,
            )
            return build_node(definition)
        raise TypeError("@node can decorate typed functions or plain Python classes")

    return decorate if target is None else decorate(target)


def _parse_contract_name(
    cls: type[Any],
    requested: str | None,
    *,
    version: int | None,
    namespace: str | None,
) -> tuple[str, int]:
    namespace = namespace or default_namespace(cls.__module__)
    requested = requested or snake_case(cls.__name__)
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
    """Register a Python payload class as a typed message contract."""

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
        definition = MessageDefinition(
            type_id=type_id,
            version=schema_version,
            python_type=cls,
            compatible_versions=tuple(compatible_versions or ()),
        )
        setattr(cls, "__plyctl_definition__", definition)
        setattr(cls, "__plyctl_message_definition__", definition)
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

    def decorate(factory: Any):
        if not inspect.isfunction(factory):
            raise TypeError("@resource currently supports functions")
        namespace = default_namespace(factory.__module__)
        local_name = name or factory.__name__
        component_name = local_name if "." in local_name else f"{namespace}.{local_name}"
        definition = analyze_resource_factory(factory, component_name=component_name)
        return build_resource(definition)

    return decorate if target is None else decorate(target)


__all__ = ["Context", "message", "node", "resource"]
