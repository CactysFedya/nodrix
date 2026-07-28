from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Type

from .errors import PluginError
from .node import Node
from .packages import resolve_package_node


BUILTINS: dict[str, type[Node]] = {}


def register_builtin(name: str):
    def decorator(cls: type[Node]) -> type[Node]:
        BUILTINS[name] = cls
        return cls
    return decorator


def _load_file_module(path: Path) -> ModuleType:
    module_name = f"nodrix_user_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginError(f"Cannot create module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    parent = str(path.parent)
    sys.path.insert(0, parent)
    try:
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(parent)
        except ValueError:
            pass
    return module


def load_node_class(reference: str, base_dir: Path | None = None) -> Type[Node]:
    reference = resolve_package_node(reference)
    # Import built-ins lazily so registry decorators have run.
    from . import builtin_nodes  # noqa: F401

    if reference in BUILTINS:
        return BUILTINS[reference]

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
        raise PluginError(f"{reference!r} is not a Nodrix Node class")
    return cls
