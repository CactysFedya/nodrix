"""Typing-first package discovery for the simplified Plyctl SDK.

This module is intentionally a thin compiler layer.  ``nodrix.yaml`` describes
package identity and discovery only; decorators remain the source of truth for
ports, configuration, resources, and message contracts.  Discovery imports the
listed modules once and compiles their metadata into the existing Provider API
2 descriptors used by the runtime and package builder.
"""

from __future__ import annotations

import importlib
import re
import sys
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, get_args, get_origin

import yaml

from .integration import ManagedResource
from .node import Node
from .provider_api import (
    PLYCTL_PROVIDER_SCHEMA_V2,
    NodeDescriptor,
    ProviderManifest,
    ProviderMetadata,
    ProviderRuntime,
    ResourceDescriptor,
)
from .simplified_sdk import ComponentSpec, ParameterSpec, _PACKAGE_NAMESPACE_OVERRIDE

_PACKAGE_API_VERSIONS = frozenset({"nodrix.dev/v1", "plyctl.dev/v1"})
_NAMESPACE = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]*[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class PackageDefinition:
    """Developer-facing package metadata loaded from ``nodrix.yaml``."""

    root: Path
    manifest_path: Path
    namespace: str
    modules: tuple[str, ...]
    name: str
    version: str
    description: str = ""
    requires_plyctl: str = ">=2.3.0b1,<3"


@dataclass(frozen=True, slots=True)
class MessageContract:
    """One message contract discovered while importing package modules."""

    id: str
    version: int
    python_ref: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "python_ref": self.python_ref,
        }


@dataclass(frozen=True, slots=True)
class CompiledPackage:
    """Result of decorator discovery compiled to existing runtime contracts."""

    definition: PackageDefinition
    provider_manifest: ProviderManifest
    provider_runtime: ProviderRuntime
    messages: tuple[MessageContract, ...] = ()

    def to_static_metadata(self) -> dict[str, Any]:
        return {
            "package": {
                "namespace": self.definition.namespace,
                "name": self.definition.name,
                "version": self.definition.version,
                "description": self.definition.description,
                "modules": list(self.definition.modules),
            },
            "provider": self.provider_manifest.to_dict(),
            "messages": [item.to_dict() for item in self.messages],
        }


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _read_pyproject(root: Path) -> Mapping[str, Any]:
    path = root / "pyproject.toml"
    if not path.is_file():
        raise ValueError("SDK package requires pyproject.toml next to nodrix.yaml")
    with path.open("rb") as handle:
        document = tomllib.load(handle)
    return _mapping(document.get("project"), "pyproject.toml [project]")


def _normalized_distribution_name(value: str) -> str:
    value = value.strip().lower().replace("-", "_")
    value = re.sub(r"[^a-z0-9_.]+", "_", value).strip("._")
    return value


def load_package_definition(path: str | Path = ".") -> PackageDefinition:
    """Load the simplified package document without importing package code.

    ``path`` may point to a directory or directly to ``nodrix.yaml``.  Package
    version is deliberately sourced from ``pyproject.toml`` and cannot be
    duplicated in the SDK manifest.
    """

    candidate = Path(path).expanduser().resolve()
    manifest_path = candidate / "nodrix.yaml" if candidate.is_dir() else candidate
    if not manifest_path.is_file():
        raise ValueError(f"package manifest not found: {manifest_path}")
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    document = _mapping(raw, "nodrix.yaml")
    api_version = str(document.get("apiVersion", "")).strip()
    if api_version not in _PACKAGE_API_VERSIONS:
        expected = ", ".join(sorted(_PACKAGE_API_VERSIONS))
        raise ValueError(f"package apiVersion must be one of: {expected}")

    package = _mapping(document.get("package"), "package")
    discover = _mapping(document.get("discover", {}), "discover")
    project = _read_pyproject(manifest_path.parent)

    project_name = str(project.get("name", "")).strip()
    version = str(project.get("version", "")).strip()
    if not project_name:
        raise ValueError("pyproject.toml [project].name is required")
    if not version:
        if "dynamic" in project and "version" in project.get("dynamic", []):
            raise ValueError("dynamic project version is not supported by SDK package build yet")
        raise ValueError("pyproject.toml [project].version is required")
    if "version" in package:
        raise ValueError("package.version must not be duplicated; use pyproject.toml")

    namespace = str(package.get("namespace") or _normalized_distribution_name(project_name)).strip()
    if not namespace or _NAMESPACE.fullmatch(namespace) is None:
        raise ValueError("package.namespace must be a lowercase dotted identifier")

    modules_raw = discover.get("modules", [])
    if not isinstance(modules_raw, list) or not modules_raw:
        raise ValueError("discover.modules must be a non-empty array")
    modules = tuple(str(item).strip() for item in modules_raw)
    if any(not item for item in modules) or len(set(modules)) != len(modules):
        raise ValueError("discover.modules contains an empty or duplicate module")

    name = str(package.get("name") or project_name).strip()
    description = str(package.get("description") or project.get("description") or "").strip()
    requires_plyctl = str(package.get("requires_plyctl") or ">=2.3.0b1,<3").strip()

    return PackageDefinition(
        root=manifest_path.parent,
        manifest_path=manifest_path,
        namespace=namespace,
        modules=modules,
        name=name,
        version=version,
        description=description,
        requires_plyctl=requires_plyctl,
    )


@contextmanager
def _import_path(root: Path):
    candidates = [root / "src", root]
    inserted: list[str] = []
    try:
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            text = str(candidate)
            if text not in sys.path:
                sys.path.insert(0, text)
                inserted.append(text)
        yield
    finally:
        for text in inserted:
            try:
                sys.path.remove(text)
            except ValueError:
                pass


def _json_schema_for(annotation: Any) -> dict[str, Any]:
    if annotation is Any:
        return {}
    primitive = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        bytes: {"type": "string", "contentEncoding": "base64"},
    }.get(annotation)
    if primitive is not None:
        return dict(primitive)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (list, tuple, set, frozenset):
        item = args[0] if args else Any
        return {"type": "array", "items": _json_schema_for(item)}
    if origin is dict:
        value = args[1] if len(args) == 2 else Any
        return {"type": "object", "additionalProperties": _json_schema_for(value)}
    if isinstance(annotation, type):
        python_type = f"{annotation.__module__}:{annotation.__qualname__}"
        return {"type": "object", "python_type": python_type}
    return {}


def _parameter_schema(parameters: tuple[ParameterSpec, ...]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for item in parameters:
        schema = _json_schema_for(item.annotation)
        if not item.required:
            schema = {**schema, "default": item.default}
        else:
            required.append(item.name)
        properties[item.name] = schema
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


def _factory_ref(module: ModuleType, attribute: str) -> str:
    return f"{module.__name__}:{attribute}"


def _iter_local_exports(module: ModuleType):
    seen: set[int] = set()
    for name, value in vars(module).items():
        if name.startswith("_") or not isinstance(value, type):
            continue
        if getattr(value, "__module__", None) != module.__name__:
            continue
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        yield name, value


def _node_descriptor(module: ModuleType, attribute: str, cls: type[Node]) -> NodeDescriptor:
    spec: ComponentSpec = cls.__plyctl_component_spec__  # type: ignore[attr-defined]
    bindings = {
        item.name: item.kind
        for item in spec.dependencies
        if item.kind == "resource"
    }
    return NodeDescriptor(
        id=spec.name,
        factory=_factory_ref(module, attribute),
        inputs={item.name: item.type_id for item in spec.inputs},
        outputs={item.name: item.type_id for item in spec.outputs},
        optional_inputs=tuple(item.name for item in spec.inputs if item.optional),
        parameters_schema=_parameter_schema(spec.parameters),
        bindings=bindings,
    )


def _resource_descriptor(
    module: ModuleType,
    attribute: str,
    cls: type[ManagedResource],
) -> ResourceDescriptor:
    spec: ComponentSpec = cls.__plyctl_component_spec__  # type: ignore[attr-defined]
    return ResourceDescriptor(
        id=spec.name,
        factory=_factory_ref(module, attribute),
        parameters_schema=_parameter_schema(spec.parameters),
    )


def _message_contract(module: ModuleType, attribute: str, cls: type[Any]) -> MessageContract:
    return MessageContract(
        id=str(cls.__plyctl_message_type__),  # type: ignore[attr-defined]
        version=int(cls.__plyctl_message_version__),  # type: ignore[attr-defined]
        python_ref=_factory_ref(module, attribute),
    )


def _assert_unique(kind: str, items: list[Any]) -> None:
    ids = [item.id for item in items]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate {kind} id(s): {', '.join(duplicates)}")


def compile_discovered_modules(
    definition: PackageDefinition,
    modules: tuple[ModuleType, ...] | list[ModuleType],
) -> CompiledPackage:
    """Compile already imported decorator modules into Provider API 2.

    Local-development discovery uses this entry point so it can own module
    identity and reload semantics while reusing the exact same descriptor
    compiler as published packages.
    """

    nodes: list[NodeDescriptor] = []
    resources: list[ResourceDescriptor] = []
    messages: list[MessageContract] = []
    runtime_nodes: dict[str, type[Any]] = {}
    runtime_resources: dict[str, type[Any]] = {}

    for module in modules:
        for attribute, value in _iter_local_exports(module):
            if hasattr(value, "__plyctl_message_type__"):
                messages.append(_message_contract(module, attribute, value))
            if issubclass(value, Node) and hasattr(value, "__plyctl_component_spec__"):
                descriptor = _node_descriptor(module, attribute, value)
                nodes.append(descriptor)
                runtime_nodes[descriptor.id] = value
                continue
            if issubclass(value, ManagedResource) and hasattr(value, "__plyctl_component_spec__"):
                descriptor = _resource_descriptor(module, attribute, value)
                resources.append(descriptor)
                runtime_resources[descriptor.id] = value

    _assert_unique("node", nodes)
    _assert_unique("resource", resources)
    _assert_unique("message", messages)
    nodes.sort(key=lambda item: item.id)
    resources.sort(key=lambda item: item.id)
    messages.sort(key=lambda item: item.id)

    provider_manifest = ProviderManifest(
        schema=PLYCTL_PROVIDER_SCHEMA_V2,
        metadata=ProviderMetadata(
            id=definition.namespace,
            name=definition.name,
            version=definition.version,
            provider_api="2",
            requires_nodrix=definition.requires_plyctl,
            description=definition.description,
        ),
        nodes=tuple(nodes),
        resources=tuple(resources),
    )
    provider_runtime = ProviderRuntime(
        provider_id=definition.namespace,
        nodes=runtime_nodes,
        resources=runtime_resources,
    )
    return CompiledPackage(
        definition=definition,
        provider_manifest=provider_manifest,
        provider_runtime=provider_runtime,
        messages=tuple(messages),
    )


def compile_package(definition_or_path: PackageDefinition | str | Path = ".") -> CompiledPackage:
    """Import configured modules and compile decorators into Provider API 2.

    This is the development/build-time path.  The resulting provider manifest
    is static data and can be written into the existing package format so
    production discovery does not have to import arbitrary implementation code.
    """

    definition = (
        definition_or_path
        if isinstance(definition_or_path, PackageDefinition)
        else load_package_definition(definition_or_path)
    )
    token = _PACKAGE_NAMESPACE_OVERRIDE.set(definition.namespace)
    modules: list[ModuleType] = []
    try:
        with _import_path(definition.root):
            for name in definition.modules:
                existing = sys.modules.get(name)
                if existing is not None:
                    discovered_ids: list[str] = []
                    for _, value in _iter_local_exports(existing):
                        spec = getattr(value, "__plyctl_component_spec__", None)
                        if spec is not None:
                            discovered_ids.append(str(spec.name))
                        message_id = getattr(value, "__plyctl_message_type__", None)
                        if message_id:
                            discovered_ids.append(str(message_id))
                    prefix = definition.namespace + "."
                    if any(not item.startswith(prefix) for item in discovered_ids):
                        raise RuntimeError(
                            f"package discovery module {name!r} is already imported outside "
                            f"namespace {definition.namespace!r}; run compilation in a "
                            "fresh process"
                        )
                    modules.append(existing)
                else:
                    modules.append(importlib.import_module(name))
    finally:
        _PACKAGE_NAMESPACE_OVERRIDE.reset(token)

    return compile_discovered_modules(definition, modules)


__all__ = [
    "CompiledPackage",
    "MessageContract",
    "PackageDefinition",
    "compile_discovered_modules",
    "compile_package",
    "load_package_definition",
]
