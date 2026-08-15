"""Import aliases used during the Nodrix to Plyctl compatibility window."""

from __future__ import annotations

from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec, PathFinder
from importlib.util import find_spec
from types import ModuleType
import sys
from typing import Any


_ALIASES: dict[str, str] = {}


def _public_namespace(module: ModuleType) -> dict[str, Any]:
    return {
        name: value
        for name, value in vars(module).items()
        if name not in {
            "__builtins__",
            "__cached__",
            "__file__",
            "__loader__",
            "__name__",
            "__package__",
            "__path__",
            "__spec__",
        }
    }


class _AliasLoader(Loader):
    def __init__(self, target_name: str) -> None:
        self.target_name = target_name

    def create_module(self, spec: ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        target = import_module(self.target_name)
        module.__dict__.update(_public_namespace(target))
        module.__dict__["__wrapped_module__"] = target


class _AliasFinder(MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        for alias_prefix, target_prefix in tuple(_ALIASES.items()):
            prefix = alias_prefix + "."
            if not fullname.startswith(prefix):
                continue
            # Real compatibility modules such as plyctl.cli take precedence.
            if PathFinder.find_spec(fullname, path) is not None:
                return None
            target_name = target_prefix + fullname[len(alias_prefix) :]
            target_spec = find_spec(target_name)
            if target_spec is None:
                return None
            is_package = target_spec.submodule_search_locations is not None
            return ModuleSpec(
                fullname,
                _AliasLoader(target_name),
                is_package=is_package,
            )
        return None


_FINDER = _AliasFinder()


def install_package_alias(alias_prefix: str, target_prefix: str) -> ModuleType:
    """Map submodules of *alias_prefix* to public objects from *target_prefix*."""

    _ALIASES[alias_prefix] = target_prefix
    if not any(item is _FINDER for item in sys.meta_path):
        sys.meta_path.insert(0, _FINDER)
    return import_module(target_prefix)


def mirror_public_api(namespace: dict[str, Any], target: ModuleType) -> None:
    """Copy the target package API without changing alias module identity."""

    namespace.update(_public_namespace(target))
    namespace["__wrapped_module__"] = target


__all__ = ["install_package_alias", "mirror_public_api"]
