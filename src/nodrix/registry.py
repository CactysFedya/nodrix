from __future__ import annotations

import importlib
import importlib.util
import hashlib
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Type

from .errors import PluginError
from .node import Node
from .packages import resolve_package_node


BUILTINS: dict[str, type[Node]] = {}
_CORE_LOADED = False
_LOADED_PROVIDERS: set[str] = set()
_REGISTRY_LOCK = threading.RLock()
_FILE_MODULE_CACHE: dict[Path, ModuleType] = {}
_BUILTIN_PROVIDERS = {
    "vision.": "nodrix.vision.nodes",
    "media.": "nodrix.media",
    "record.": "nodrix.recording",
    "ros2.": "nodrix.ros2_adapter",
}


def register_builtin(name: str):
    def decorator(cls: type[Node]) -> type[Node]:
        with _REGISTRY_LOCK:
            BUILTINS[name] = cls
        return cls
    return decorator


def _load_core_builtins() -> None:
    global _CORE_LOADED
    with _REGISTRY_LOCK:
        if _CORE_LOADED:
            return
        importlib.import_module("nodrix.builtin_nodes")
        _CORE_LOADED = True


def _load_provider(prefix: str) -> None:
    with _REGISTRY_LOCK:
        if prefix in _LOADED_PROVIDERS:
            return
        module = importlib.import_module(_BUILTIN_PROVIDERS[prefix])
        if prefix == "record.":
            register_builtin("record.ndrx_source")(module.NdrxSourceNode)
            register_builtin("record.ndrx_writer")(module.NdrxWriterNode)
        _LOADED_PROVIDERS.add(prefix)


def load_builtin_providers() -> None:
    """Load every optional built-in pack for discovery-oriented CLI commands."""
    _load_core_builtins()
    for prefix in _BUILTIN_PROVIDERS:
        try:
            _load_provider(prefix)
        except ModuleNotFoundError:
            # Listing Core nodes must remain available in a minimal installation.
            continue


def reset_file_module_cache() -> None:
    # Clear cached local modules for tests and development reloads.
    with _REGISTRY_LOCK:
        for module in tuple(_FILE_MODULE_CACHE.values()):
            if sys.modules.get(module.__name__) is module:
                sys.modules.pop(module.__name__, None)
        _FILE_MODULE_CACHE.clear()


def _load_file_module(path: Path) -> ModuleType:
    canonical = path.expanduser().resolve()
    with _REGISTRY_LOCK:
        cached = _FILE_MODULE_CACHE.get(canonical)
        if cached is not None:
            return cached

        digest = hashlib.sha256(
            canonical.as_posix().encode("utf-8")
        ).hexdigest()[:24]
        module_name = f"nodrix_user_{digest}"

        existing = sys.modules.get(module_name)
        if (
            isinstance(existing, ModuleType)
            and Path(getattr(existing, "__file__", "")).resolve() == canonical
        ):
            _FILE_MODULE_CACHE[canonical] = existing
            return existing

        spec = importlib.util.spec_from_file_location(module_name, canonical)
        if spec is None or spec.loader is None:
            raise PluginError(f"Cannot create module spec for {canonical}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        parent = str(canonical.parent)
        inserted_parent = parent not in sys.path
        if inserted_parent:
            sys.path.insert(0, parent)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            _FILE_MODULE_CACHE.pop(canonical, None)
            if sys.modules.get(module_name) is module:
                sys.modules.pop(module_name, None)
            raise
        finally:
            if inserted_parent:
                try:
                    sys.path.remove(parent)
                except ValueError:
                    pass

        _FILE_MODULE_CACHE[canonical] = module
        return module


def load_node_class(reference: str, base_dir: Path | None = None) -> Type[Node]:
    reference = resolve_package_node(reference)
    _load_core_builtins()
    for prefix in _BUILTIN_PROVIDERS:
        if reference.startswith(prefix):
            try:
                _load_provider(prefix)
            except ModuleNotFoundError as exc:
                extra = prefix.removesuffix(".")
                raise PluginError(
                    f"Node pack {extra!r} is unavailable; install Plyctl with the appropriate extra"
                ) from exc
            break

    with _REGISTRY_LOCK:
        builtin = BUILTINS.get(reference)
    if builtin is not None:
        return builtin

    if ":" not in reference:
        # Provider API discovery is metadata-only.  The selected provider is
        # imported here, after compatibility and trust checks, only when a
        # pipeline actually references one of its declared Node ids.
        from .providers import load_provider_node

        provider_class = load_provider_node(reference)
        if provider_class is not None:
            if not issubclass(provider_class, Node):
                raise PluginError(
                    f"Provider Node {reference!r} is not a Plyctl Node class"
                )
            return provider_class

    if ":" not in reference:
        raise PluginError(
            f"Unknown node {reference!r}. Use a built-in id or module.py:Class"
        )

    module_ref, class_name = reference.rsplit(":", 1)
    try:
        if module_ref.endswith(".py") or "/" in module_ref or "\\" in module_ref:
            path = Path(module_ref)
            if not path.is_absolute():
                path = (base_dir or Path.cwd()) / path
            path = path.resolve()
            if not path.exists():
                raise PluginError(f"Node module does not exist: {path}")
            module = _load_file_module(path)
        else:
            module = importlib.import_module(module_ref)
        cls = getattr(module, class_name)
    except PluginError:
        raise
    except Exception as exc:
        raise PluginError(f"Cannot load node {reference!r}: {exc}") from exc

    if not isinstance(cls, type) or not issubclass(cls, Node):
        raise PluginError(f"{reference!r} is not a Plyctl Node class")
    return cls
