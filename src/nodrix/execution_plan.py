from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
from typing import Any

from . import __version__
from .manifest import PipelineManifest, _redact


EXECUTION_PLAN_SCHEMA = "nodrix.execution-plan/v1"


def _topological_order(manifest: PipelineManifest) -> tuple[list[str], bool]:
    indegree = {name: 0 for name in manifest.nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in (*manifest.edges, *manifest.links):
        source = edge.source.split(".", 1)[0]
        target = edge.target.split(".", 1)[0]
        if source == target:
            continue
        outgoing[source].append(target)
        indegree[target] += 1
    ready = deque(name for name in manifest.nodes if indegree[name] == 0)
    ordered: list[str] = []
    while ready:
        name = ready.popleft()
        ordered.append(name)
        for target in outgoing[name]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    acyclic = len(ordered) == len(manifest.nodes)
    ordered.extend(name for name in manifest.nodes if name not in ordered)
    return ordered, acyclic


def _canonical_manifest(manifest: PipelineManifest) -> tuple[dict[str, Any], str]:
    raw = manifest.model_dump(by_alias=True, exclude_none=True, mode="json")
    redacted = _redact(raw)
    encoded = json.dumps(
        redacted,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return redacted, hashlib.sha256(encoded).hexdigest()


def compile_execution_plan(
    manifest: PipelineManifest,
    description: dict[str, Any],
) -> dict[str, Any]:
    """Compile a deterministic, secret-free runtime contract.

    The returned document contains only resolved decisions. It is suitable for
    review, hashing and run artifacts; creating it does not open node resources.
    """
    canonical, manifest_sha256 = _canonical_manifest(manifest)
    order, acyclic = _topological_order(manifest)
    described_nodes = dict(description.get("nodes") or {})
    described_edges = {
        (str(edge.get("from")), str(edge.get("to"))): dict(edge)
        for edge in description.get("edges") or []
    }
    warnings: list[dict[str, str]] = []
    if not acyclic:
        warnings.append(
            {
                "code": "P101",
                "message": "Graph contains a cycle; explicit feedback semantics are required.",
            }
        )

    nodes: list[dict[str, Any]] = []
    reproducible = manifest.runtime.engine != "auto"
    for ordinal, name in enumerate(order):
        config = manifest.nodes[name]
        described = dict(described_nodes.get(name) or {})
        device = str(described.get("device", config.execution.device))
        if device == "auto":
            reproducible = False
            warnings.append(
                {
                    "code": "P201",
                    "message": f"Node {name!r} uses automatic device selection.",
                }
            )
        automatic = sorted(
            key
            for key, value in config.parameters.items()
            if isinstance(value, str) and value.lower() == "auto"
        )
        if automatic:
            reproducible = False
            warnings.append(
                {
                    "code": "P202",
                    "message": f"Node {name!r} has automatic parameters: {', '.join(automatic)}.",
                }
            )
        nodes.append(
            {
                "ordinal": ordinal,
                "name": name,
                "uses": config.uses,
                "implementation": described.get("implementation", "native" if description.get("engine") == "native" else "python"),
                "class": described.get("class"),
                "isolation": config.execution.isolation,
                "device": device,
                "inputs": dict(described.get("inputs") or config.inputs),
                "optional_inputs": list(described.get("optional_inputs") or config.synchronization.optional_inputs),
                "outputs": dict(described.get("outputs") or config.outputs),
                "synchronization": config.synchronization.model_dump(mode="json"),
                "failure": config.failure.model_dump(mode="json"),
                "resources": config.resources.model_dump(mode="json"),
                "bindings": dict(config.bindings),
                "parameters": _redact(dict(config.parameters)),
            }
        )

    edges: list[dict[str, Any]] = []
    total_planned_copies = 0
    for ordinal, edge in enumerate(manifest.edges):
        described = described_edges.get((edge.source, edge.target), {})
        memory = dict(described.get("memory") or {})
        planned_copies = int(memory.get("planned_copies", 0))
        total_planned_copies += planned_copies
        edges.append(
            {
                "ordinal": ordinal,
                "from": edge.source,
                "to": edge.target,
                "type": described.get("type"),
                "queue": edge.queue.model_dump(mode="json"),
                "memory": memory or edge.memory.model_dump(mode="json"),
                "planned_copies": planned_copies,
            }
        )

    plan = {
        "schema": EXECUTION_PLAN_SCHEMA,
        "runtime": {"name": "nodrix", "version": __version__},
        "pipeline": manifest.metadata.name,
        "manifest_sha256": manifest_sha256,
        "engine": description.get("engine", "unified"),
        "mode": manifest.runtime.mode,
        "profile": manifest.runtime.profile,
        "sessions": [
            {
                "name": name,
                "uses": config.uses,
                "parameters": _redact(dict(config.parameters)),
            }
            for name, config in manifest.sessions.items()
        ],
        "reproducible": reproducible,
        "topological_order": order,
        "nodes": nodes,
        "edges": edges,
        "links": [
            {
                "ordinal": ordinal,
                **_redact(
                    link.model_dump(by_alias=True, exclude_none=True, mode="json")
                ),
                "data_plane": "external",
                "planned_copies": 0,
            }
            for ordinal, link in enumerate(manifest.links)
        ],
        "streams": [
            {
                "name": export.name,
                "from": export.source,
                "access": export.access.mode,
                "queue": export.queue.model_dump(mode="json"),
            }
            for export in manifest.streams.exports
        ],
        "stream_transport": {
            "protocol": "tls" if manifest.streams.tls.enabled else "tcp",
            "mutual_tls": manifest.streams.tls.require_client_certificate,
            "minimum_tls_version": (
                manifest.streams.tls.minimum_version
                if manifest.streams.tls.enabled
                else None
            ),
        },
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "links": len(manifest.links),
            "sessions": len(manifest.sessions),
            "streams": len(manifest.streams.exports),
            "planned_copies": total_planned_copies,
        },
        "warnings": warnings,
        "resolved_manifest": canonical,
    }
    validate_execution_plan(plan)
    return plan


def validate_execution_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema") != EXECUTION_PLAN_SCHEMA:
        raise ValueError(f"Unsupported execution plan schema: {plan.get('schema')!r}")
    digest = str(plan.get("manifest_sha256", ""))
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("Execution plan has an invalid manifest_sha256")
    nodes = list(plan.get("nodes") or [])
    names = [str(node.get("name", "")) for node in nodes]
    if not names or any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Execution plan node names must be non-empty and unique")
    known = set(names)
    for edge in [*(plan.get("edges") or []), *(plan.get("links") or [])]:
        source = str(edge.get("from", "")).split(".", 1)[0]
        target = str(edge.get("to", "")).split(".", 1)[0]
        if source not in known or target not in known:
            raise ValueError(f"Execution plan edge references an unknown node: {edge!r}")


def write_execution_plan(plan: dict[str, Any], path: str | Path) -> Path:
    validate_execution_plan(plan)
    target = Path(path)
    target.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target
