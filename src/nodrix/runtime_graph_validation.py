"""Backend-neutral validation of a materialized runtime graph."""

from __future__ import annotations

from collections.abc import Mapping

from .errors import RuntimeGraphError
from .runtime_components import LoadedNode


def validate_runtime_graph(
    nodes: Mapping[
        str,
        LoadedNode,
    ],
) -> None:
    """Validate graph-wide invariants after edge wiring.

    Edge-local properties such as endpoint existence, port contracts,
    type compatibility, duplicate targets, and memory compatibility are
    validated while each edge is materialized.

    This validation therefore handles only invariants that require the
    completely wired runtime graph.
    """

    for name, loaded in nodes.items():
        optional_inputs = set(
            getattr(
                loaded.node,
                "optional_inputs",
                (),
            )
        )

        missing = sorted(
            set(
                loaded.node.input_types
            )
            - optional_inputs
            - set(
                loaded.inputs
            )
        )

        if missing:
            raise RuntimeGraphError(
                (
                    f"Node {name!r} has "
                    "unconnected inputs: "
                    f"{missing}"
                )
            )


__all__ = [
    "validate_runtime_graph",
]
