"""Lower System boundary links into runtime transport adapter nodes."""

from __future__ import annotations

from typing import Any

from ..manifest import PipelineManifest
from .backend import BackendContext
from .graph import split_system_endpoint
from .local_backend import LocalLoweringResult
from .transport import require_transport_runtime


def _adapter_name(direction: str, ordinal: int) -> str:
    return f"__nodrix_transport_{direction}_{ordinal}"


def _endpoint_alias(
    endpoint: str,
    *,
    aliases: dict[str, str],
) -> str:
    graph, instance, port = split_system_endpoint(endpoint)
    if graph is None:
        return f"{instance}.{port}"
    return f"{aliases[f'{graph}/{instance}']}.{port}"


def lower_transport_boundaries(
    context: BackendContext,
    lowering: LocalLoweringResult,
) -> LocalLoweringResult:
    """Inject sender/receiver adapters for cross-scope transport links.

    The ordinary local lowering owns graph nodes and internal edges. This pass
    only materializes links that cross the current execution scope, preserving
    the existing runtime and wire protocol.
    """

    if not context.inbound_links and not context.outbound_links:
        return lowering

    document: dict[str, Any] = lowering.manifest.model_dump(
        by_alias=True,
        exclude_none=True,
    )
    nodes = dict(document.get("nodes") or {})
    edges = list(document.get("edges") or [])
    placement = dict(document.get("placement") or {})
    placement_nodes = dict(placement.get("nodes") or {})
    aliases = dict(lowering.node_aliases)
    local_target = context.targets[0].name if len(context.targets) == 1 else "local"

    for link in context.outbound_links:
        adapter = require_transport_runtime(link.transport_uses)
        name = _adapter_name("out", link.ordinal)
        nodes[name] = {
            "uses": adapter.sender_node,
            "parameters": dict(link.parameters),
            "placement": local_target,
        }
        placement_nodes[name] = local_target
        edges.append(
            {
                "from": _endpoint_alias(link.source, aliases=aliases),
                "to": f"{name}.input",
            }
        )

    for link in context.inbound_links:
        adapter = require_transport_runtime(link.transport_uses)
        name = _adapter_name("in", link.ordinal)
        nodes[name] = {
            "uses": adapter.receiver_node,
            "parameters": dict(link.parameters),
            "placement": local_target,
        }
        placement_nodes[name] = local_target
        edges.append(
            {
                "from": f"{name}.output",
                "to": _endpoint_alias(link.target, aliases=aliases),
            }
        )

    placement["nodes"] = placement_nodes
    document["nodes"] = nodes
    document["edges"] = edges
    document["placement"] = placement

    return LocalLoweringResult(
        manifest=PipelineManifest.model_validate(document),
        node_aliases=aliases,
        generated_from_legacy_snapshot=lowering.generated_from_legacy_snapshot,
    )


__all__ = ["lower_transport_boundaries"]
