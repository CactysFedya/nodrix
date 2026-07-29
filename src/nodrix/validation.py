from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .manifest import PipelineManifest


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    location: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _find_cycles(manifest: PipelineManifest) -> list[list[str]]:
    graph: dict[str, list[str]] = {name: [] for name in manifest.nodes}
    for edge in manifest.edges:
        source = edge.source.split(".", 1)[0]
        target = edge.target.split(".", 1)[0]
        graph.setdefault(source, []).append(target)
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        if node in visiting:
            try:
                start = stack.index(node)
            except ValueError:
                start = 0
            cycles.append(stack[start:] + [node])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for target in graph.get(node, []):
            visit(target)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for name in graph:
        visit(name)
    return cycles


def validate_production(manifest: PipelineManifest, description: dict[str, Any], *, strict: bool = False) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    for cycle in _find_cycles(manifest):
        issues.append(ValidationIssue("error", "E301", f"Graph cycle requires an explicit feedback-buffer node: {' -> '.join(cycle)}"))
    for edge in description.get("edges", []):
        memory = dict(edge.get("memory") or {})
        if not memory.get("runtime_supported", True):
            issues.append(ValidationIssue("error", "E204", memory.get("reason", "Unsupported memory path"), f"{edge['from']} -> {edge['to']}"))
        if int(memory.get("planned_copies", 0)) > 0:
            issues.append(ValidationIssue("warning", "W205", f"Edge requires {memory.get('planned_copies')} payload copy/copies", f"{edge['from']} -> {edge['to']}"))
    for export in manifest.streams.exports:
        access = export.access
        if access.mode == "open" and manifest.streams.bind_host not in loopback_hosts:
            severity = "error" if strict else "warning"
            issues.append(ValidationIssue(severity, "S101", "LAN stream is open without token authentication", export.name))
        if access.token:
            severity = "error" if strict else "warning"
            issues.append(ValidationIssue(severity, "S102", "Inline stream token can leak through source control; use token_env", export.name))
        if export.queue.policy == "block":
            issues.append(ValidationIssue("warning", "W401", "Network export uses block policy and may propagate backpressure", export.name))
    if manifest.runtime.metrics.listen:
        metrics_host = manifest.runtime.metrics.listen.rpartition(":")[0].strip("[]")
        if metrics_host not in loopback_hosts:
            severity = "error" if strict else "warning"
            issues.append(
                ValidationIssue(
                    severity,
                    "S103",
                    "Metrics endpoint is exposed beyond loopback without authentication",
                    "runtime.metrics.listen",
                )
            )
    for name, config in manifest.nodes.items():
        if config.health.timeout_ms > 0 and config.execution.isolation == "in_process" and config.health.on_timeout == "restart":
            issues.append(ValidationIssue("warning", "W501", "An in-process Python thread cannot be force-restarted safely; use process isolation", name))
        if config.resources.memory_limit_mb and config.execution.isolation != "process":
            issues.append(ValidationIssue("warning", "W502", "Memory limits are enforceable only for process-isolated nodes", name))
        if config.failure.policy == "restart" and config.execution.isolation != "process":
            issues.append(ValidationIssue("warning", "W503", "Safe restart requires process isolation", name))
    if manifest.runtime.shutdown.timeout_ms < 100:
        issues.append(ValidationIssue("warning", "W601", "Graceful shutdown timeout is extremely short", "runtime.shutdown"))
    return issues
