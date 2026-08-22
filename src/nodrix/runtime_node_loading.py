"""Backend-neutral loading of concrete runtime nodes.

This module resolves one already-selected node implementation reference into a
concrete Node instance.

It deliberately does not own parameter-policy resolution, failure handling,
process isolation, graph validation, queue construction, lifecycle, or
telemetry configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import RuntimeGraphError
from .native_plugin import NativePluginNode
from .node import Node
from .packages import resolve_package_node
from .registry import load_node_class


def load_runtime_node(
    uses: str,
    parameters: dict[str, Any],
    *,
    base_dir: Path,
) -> Node:
    """Load and construct one runtime node implementation."""

    resolved_uses = resolve_package_node(
        uses
    )

    if resolved_uses.startswith(
        "native:"
    ):
        body = resolved_uses.removeprefix(
            "native:"
        )

        if "#" not in body:
            raise RuntimeGraphError(
                "Native plugin must use "
                "native:/path/library#node-type"
            )

        library, node_type = body.rsplit(
            "#",
            1,
        )

        path = Path(
            library
        ).expanduser()

        if not path.is_absolute():
            path = (
                base_dir
                / path
            ).resolve()

        if not path.exists():
            raise RuntimeGraphError(
                "Native plugin library does not "
                f"exist: {path}"
            )

        return NativePluginNode(
            path,
            node_type,
            parameters,
        )

    if resolved_uses.startswith(
        "native."
    ):
        raise RuntimeGraphError(
            "Built-in native.* nodes run in "
            "engine: native. Use a "
            "native:/path/plugin#type reference "
            "inside a unified Python/C++ graph."
        )

    node_class = load_node_class(
        resolved_uses,
        base_dir=base_dir,
    )

    return node_class(
        parameters
    )


__all__ = [
    "load_runtime_node",
]
