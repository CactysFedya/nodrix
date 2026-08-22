"""Backend-neutral node materialization validation.

This module validates a concrete Node against an already resolved
RuntimeNodeBinding.  It does not read Pipeline manifests, System plans, or
execution-context defaults.

Fallback implementations remain lazy for execution.  Build-time validation may
instantiate a temporary fallback solely to verify its contract, matching the
existing runtime semantics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .errors import RuntimeGraphError
from .node import Node
from .node_docs import validate_parameters
from .runtime_node_loading import load_runtime_node
from .runtime_primitives import RuntimeNodeBinding


def validate_runtime_node_parameters(
    binding: RuntimeNodeBinding,
) -> None:
    """Validate resolved node parameters before implementation construction."""

    validate_parameters(
        binding.uses,
        dict(
            binding.parameters
        ),
    )


def _validate_port_contracts(
    *,
    name: str,
    uses: str,
    node: Node,
    declared_inputs: Mapping[str, str],
    declared_outputs: Mapping[str, str],
) -> None:
    if (
        declared_inputs
        and dict(declared_inputs)
        != dict(node.input_types)
    ):
        raise RuntimeGraphError(
            f"Node {name!r} declared inputs "
            f"{declared_inputs}, but {uses!r} "
            f"provides {node.input_types}"
        )

    if (
        declared_outputs
        and dict(declared_outputs)
        != dict(node.output_types)
    ):
        raise RuntimeGraphError(
            f"Node {name!r} declared outputs "
            f"{declared_outputs}, but {uses!r} "
            f"provides {node.output_types}"
        )


def _validate_optional_inputs(
    *,
    name: str,
    node: Node,
    binding: RuntimeNodeBinding,
) -> None:
    trigger_port = (
        binding
        .synchronization_trigger_port
    )

    if (
        trigger_port
        and trigger_port
        not in node.input_types
    ):
        raise RuntimeGraphError(
            f"Node {name!r} synchronization "
            f"trigger_port {trigger_port!r} "
            "is not an input"
        )

    implementation_optional = set(
        getattr(
            node,
            "optional_inputs",
            (),
        )
    )

    configured_optional = set(
        binding
        .synchronization_optional_inputs
    )

    input_ports = set(
        node.input_types
    )

    unknown_implementation = sorted(
        implementation_optional
        - input_ports
    )

    if unknown_implementation:
        raise RuntimeGraphError(
            f"Node {name!r} declares unknown "
            "optional inputs: "
            f"{unknown_implementation}"
        )

    unknown_configured = sorted(
        configured_optional
        - input_ports
    )

    if unknown_configured:
        raise RuntimeGraphError(
            f"Node {name!r} configures unknown "
            "optional inputs: "
            f"{unknown_configured}"
        )

    unsupported_optional = sorted(
        configured_optional
        - implementation_optional
    )

    if unsupported_optional:
        raise RuntimeGraphError(
            f"Node {name!r} cannot make required "
            "inputs optional: "
            f"{unsupported_optional}"
        )


def load_runtime_fallback_node(
    *,
    name: str,
    primary: Node,
    binding: RuntimeNodeBinding,
    base_dir: Path,
) -> Node:
    """Load and verify one fallback against the primary node contract."""

    fallback_uses = (
        binding.fallback_uses
    )

    if not fallback_uses:
        raise RuntimeGraphError(
            f"Node {name!r} has no configured "
            "fallback"
        )

    if binding.isolation != "in_process":
        raise RuntimeGraphError(
            f"Node {name!r}: fallback_node "
            "currently requires in_process "
            "isolation"
        )

    parameters = dict(
        binding.parameters
    )

    validate_parameters(
        fallback_uses,
        parameters,
    )

    fallback = load_runtime_node(
        fallback_uses,
        parameters,
        base_dir=base_dir,
    )

    if (
        dict(fallback.input_types)
        != dict(primary.input_types)
        or dict(fallback.output_types)
        != dict(primary.output_types)
    ):
        raise RuntimeGraphError(
            f"Node {name!r}: fallback node ports "
            "must exactly match the primary node"
        )

    return fallback


def validate_runtime_node_materialization(
    *,
    name: str,
    node: Node,
    binding: RuntimeNodeBinding,
    declared_inputs: Mapping[str, str],
    declared_outputs: Mapping[str, str],
    base_dir: Path,
) -> None:
    """Validate one loaded implementation against resolved runtime mechanics."""

    if (
        binding.failure_policy
        == "fallback_node"
    ):
        load_runtime_fallback_node(
            name=name,
            primary=node,
            binding=binding,
            base_dir=base_dir,
        )

    _validate_port_contracts(
        name=name,
        uses=binding.uses,
        node=node,
        declared_inputs=declared_inputs,
        declared_outputs=declared_outputs,
    )

    _validate_optional_inputs(
        name=name,
        node=node,
        binding=binding,
    )


__all__ = [
    "load_runtime_fallback_node",
    "validate_runtime_node_materialization",
    "validate_runtime_node_parameters",
]
