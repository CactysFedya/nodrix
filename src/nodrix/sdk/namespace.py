"""Namespace rules shared by package and local-development SDK discovery."""

from __future__ import annotations

import re
from contextvars import ContextVar

PACKAGE_NAMESPACE_OVERRIDE: ContextVar[str | None] = ContextVar(
    "plyctl_package_namespace", default=None
)


def snake_case(value: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).replace("-", "_").lower()


def default_namespace(module_name: str) -> str:
    override = PACKAGE_NAMESPACE_OVERRIDE.get()
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


__all__ = ["PACKAGE_NAMESPACE_OVERRIDE", "default_namespace", "snake_case"]
