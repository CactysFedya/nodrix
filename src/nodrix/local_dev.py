"""Local developer workflow for the typing-first SDK.

Local projects keep their Python files in ``components/`` and do not need a
package manifest while iterating.  Discovery assigns the reserved ``local``
namespace, compiles decorators through the Package SDK, and can temporarily
register the resulting ProviderRuntime with the normal runtime resolver.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterator

from .package_sdk import (
    CompiledPackage,
    PackageDefinition,
    compile_discovered_modules,
    compile_package,
)
from .provider_loading import (
    register_development_provider,
    unregister_development_provider,
)
from .simplified_sdk import _PACKAGE_NAMESPACE_OVERRIDE

_LOCAL_NAMESPACE = "local"
_LOCAL_MODULES: dict[str, ModuleType] = {}


@dataclass(frozen=True, slots=True)
class LocalProject:
    """Compiled local/package project ready for development commands."""

    root: Path
    compiled: CompiledPackage
    module_names: tuple[str, ...]
    source_files: tuple[Path, ...]
    package_mode: bool = False

    @property
    def namespace(self) -> str:
        return self.compiled.definition.namespace


def _project_root(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if candidate.is_file():
        return candidate.parent
    return candidate


def _component_files(root: Path) -> tuple[Path, ...]:
    components = root / "components"
    if not components.is_dir():
        raise ValueError(
            f"local project has no components directory: {components}; "
            "create components/*.py or add nodrix.yaml for a package"
        )
    files = tuple(
        path
        for path in sorted(components.rglob("*.py"))
        if "__pycache__" not in path.parts and not path.name.startswith(".")
    )
    if not files:
        raise ValueError(f"local project contains no Python components: {components}")
    return files


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    if not parts:
        raise ValueError(f"cannot derive module name for {path}")
    return ".".join(parts)


def _module_file(module: ModuleType) -> Path | None:
    value = getattr(module, "__file__", None)
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _assert_local_namespace(module: ModuleType) -> None:
    prefix = _LOCAL_NAMESPACE + "."
    for value in vars(module).values():
        if not isinstance(value, type) or getattr(value, "__module__", None) != module.__name__:
            continue
        spec = getattr(value, "__plyctl_component_spec__", None)
        if spec is not None and not str(spec.name).startswith(prefix):
            raise RuntimeError(
                f"local module {module.__name__!r} was imported before local discovery; "
                "start a fresh process or reset local development modules"
            )
        message_id = getattr(value, "__plyctl_message_type__", None)
        if message_id and not str(message_id).startswith(prefix):
            raise RuntimeError(
                f"local module {module.__name__!r} was imported before local discovery; "
                "start a fresh process or reset local development modules"
            )


@contextmanager
def _root_on_path(root: Path) -> Iterator[None]:
    text = str(root)
    inserted = text not in sys.path
    if inserted:
        sys.path.insert(0, text)
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(text)
            except ValueError:
                pass


def reset_local_development_modules() -> None:
    """Forget modules imported by local discovery; intended for tests/reload."""

    for name, module in tuple(_LOCAL_MODULES.items()):
        if sys.modules.get(name) is module:
            sys.modules.pop(name, None)
    _LOCAL_MODULES.clear()
    importlib.invalidate_caches()


def compile_local_project(path: str | Path = ".") -> LocalProject:
    """Compile a package project or implicit ``components/`` local project."""

    root = _project_root(path)
    if not root.is_dir():
        raise ValueError(f"project directory does not exist: {root}")

    if (root / "nodrix.yaml").is_file():
        compiled = compile_package(root)
        return LocalProject(
            root=root,
            compiled=compiled,
            module_names=compiled.definition.modules,
            source_files=(),
            package_mode=True,
        )

    files = _component_files(root)
    names = tuple(_module_name(root, item) for item in files)
    if len(set(names)) != len(names):
        raise ValueError("local components resolve to duplicate Python module names")

    definition = PackageDefinition(
        root=root,
        manifest_path=root / "components",
        namespace=_LOCAL_NAMESPACE,
        modules=names,
        name=f"{root.name} local components",
        version="0+local",
        description="Implicit local development components",
        requires_plyctl=">=2.3.0b1,<3",
    )

    modules: list[ModuleType] = []
    token = _PACKAGE_NAMESPACE_OVERRIDE.set(_LOCAL_NAMESPACE)
    try:
        with _root_on_path(root):
            for name, source in zip(names, files, strict=True):
                existing = sys.modules.get(name)
                if existing is not None:
                    existing_file = _module_file(existing)
                    if existing_file != source.resolve():
                        raise RuntimeError(
                            f"Python module {name!r} already resolves to "
                            f"{existing_file or '<namespace>'}, not {source.resolve()}"
                        )
                    module = existing
                    _assert_local_namespace(module)
                else:
                    module = importlib.import_module(name)
                _LOCAL_MODULES[name] = module
                modules.append(module)
    finally:
        _PACKAGE_NAMESPACE_OVERRIDE.reset(token)

    compiled = compile_discovered_modules(definition, modules)
    return LocalProject(
        root=root,
        compiled=compiled,
        module_names=names,
        source_files=files,
        package_mode=False,
    )


@contextmanager
def activate_local_project(project: LocalProject) -> Iterator[LocalProject]:
    """Expose one compiled project to normal provider resolution temporarily."""

    provider_id = project.compiled.provider_manifest.metadata.id
    register_development_provider(
        project.compiled.provider_manifest,
        project.compiled.provider_runtime,
    )
    try:
        yield project
    finally:
        unregister_development_provider(provider_id)


__all__ = [
    "LocalProject",
    "activate_local_project",
    "compile_local_project",
    "reset_local_development_modules",
]
