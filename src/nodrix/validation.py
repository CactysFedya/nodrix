from __future__ import annotations

from dataclasses import dataclass, asdict
import os
from pathlib import Path
import stat
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


def validate_production(
    manifest: PipelineManifest,
    description: dict[str, Any],
    *,
    strict: bool = False,
    production: bool = False,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    for cycle in _find_cycles(manifest):
        issues.append(ValidationIssue("error", "E301", f"Graph cycle requires an explicit feedback-buffer node: {' -> '.join(cycle)}"))
    for edge in description.get("edges", []):
        memory = dict(edge.get("memory") or {})
        if not memory.get("runtime_supported", True):
            issues.append(ValidationIssue("error", "E204", memory.get("reason", "Unsupported memory path"), f"{edge['from']} -> {edge['to']}"))
        if int(memory.get("planned_copies", 0)) > 0:
            severity = "error" if production else "warning"
            issues.append(ValidationIssue(severity, "W205", f"Edge requires {memory.get('planned_copies')} payload copy/copies", f"{edge['from']} -> {edge['to']}"))
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
    if manifest.streams.exports and manifest.streams.bind_host not in loopback_hosts:
        if not manifest.streams.tls.enabled:
            severity = "error" if strict else "warning"
            issues.append(
                ValidationIssue(
                    severity,
                    "S104",
                    "LAN stream transport is not encrypted; enable streams.tls",
                    "streams.tls",
                )
            )
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
    if production and manifest.runtime.logging.level == "debug":
        issues.append(
            ValidationIssue(
                "error",
                "P505",
                "Production mode rejects debug logging",
                "runtime.logging.level",
            )
        )
    for name, config in manifest.nodes.items():
        if config.health.timeout_ms > 0 and config.execution.isolation == "in_process" and config.health.on_timeout == "restart":
            issues.append(ValidationIssue("warning", "W501", "An in-process Python thread cannot be force-restarted safely; use process isolation", name))
        if config.resources.memory_limit_mb and config.execution.isolation != "process":
            issues.append(ValidationIssue("warning", "W502", "Memory limits are enforceable only for process-isolated nodes", name))
        if config.failure.policy in {"restart", "restart_node"} and config.execution.isolation != "process":
            issues.append(ValidationIssue("warning", "W503", "Safe restart requires process isolation", name))
        if production and config.health.timeout_ms <= 0:
            issues.append(
                ValidationIssue(
                    "error",
                    "P501",
                    "Production nodes require an explicit health timeout",
                    f"nodes.{name}.health.timeout_ms",
                )
            )
        if production:
            acceleration = str(config.parameters.get("acceleration", ""))
            if acceleration == "preferred":
                issues.append(
                    ValidationIssue(
                        "error",
                        "P502",
                        "Production hardware policy must be required or explicitly disabled; preferred permits fallback",
                        f"nodes.{name}.parameters.acceleration",
                    )
                )
            for key, value in config.parameters.items():
                if (
                    isinstance(value, str)
                    and any(token in key.lower() for token in ("model", "weights", "engine"))
                    and "://" not in value
                    and not Path(value).expanduser().is_absolute()
                ):
                    issues.append(
                        ValidationIssue(
                            "error",
                            "P503",
                            "Production model/engine paths must be absolute or content-addressed",
                            f"nodes.{name}.parameters.{key}",
                        )
                    )
            is_external = (
                config.uses.startswith("native:")
                or ":" in config.uses
                or "/" in config.uses
            )
            signature_verified = False
            if config.uses.count("/") == 1 and not config.uses.startswith(("./", "../")):
                try:
                    from .packages import package_verification

                    signature_verified = bool(
                        package_verification(config.uses.split("/", 1)[0]).get(
                            "signature_verified"
                        )
                    )
                except Exception:
                    signature_verified = False
            if (
                is_external
                and (
                    manifest.security.require_signed_plugins
                    or not manifest.security.allow_unsigned_local_plugins
                )
                and not signature_verified
                and not config.uses.startswith(("ros2.",))
            ):
                issues.append(
                    ValidationIssue(
                        "error",
                        "P504",
                        "External plugin signature is not represented in this manifest; use a verified installed package",
                        f"nodes.{name}.uses",
                    )
                )
            if config.uses.startswith("native:"):
                reference = config.uses.removeprefix("native:")
                library_text = reference.rsplit("#", 1)[0]
                library = Path(library_text).expanduser()
                allowlist: list[Path] = []
                for item in manifest.security.native_plugin_allowlist:
                    allow_root = Path(item).expanduser()
                    if not allow_root.is_absolute():
                        issues.append(
                            ValidationIssue(
                                "error",
                                "P510",
                                "Native plugin allowlist entries must be absolute",
                                "security.native_plugin_allowlist",
                            )
                        )
                        continue
                    allowlist.append(allow_root.resolve())
                if not library.is_absolute():
                    issues.append(
                        ValidationIssue(
                            "error",
                            "P506",
                            "Production native plugin paths must be absolute",
                            f"nodes.{name}.uses",
                        )
                    )
                else:
                    resolved = library.resolve()
                    if not allowlist or not any(
                        resolved == root or root in resolved.parents
                        for root in allowlist
                    ):
                        issues.append(
                            ValidationIssue(
                                "error",
                                "P507",
                                "Native plugin is outside security.native_plugin_allowlist",
                                f"nodes.{name}.uses",
                            )
                        )
                    if not resolved.is_file():
                        issues.append(
                            ValidationIssue(
                                "error",
                                "P508",
                                "Native plugin library does not exist",
                                f"nodes.{name}.uses",
                            )
                        )
                    elif (
                        os.name != "nt"
                        and manifest.security.reject_world_writable_plugins
                        and stat.S_IMODE(resolved.stat().st_mode)
                        & stat.S_IWOTH
                    ):
                        issues.append(
                            ValidationIssue(
                                "error",
                                "P509",
                                "World-writable native plugins are forbidden in production",
                                f"nodes.{name}.uses",
                            )
                        )
    if manifest.runtime.shutdown.timeout_ms < 100:
        issues.append(ValidationIssue("warning", "W601", "Graceful shutdown timeout is extremely short", "runtime.shutdown"))
    if production and manifest.api_version != "nodrix.dev/v2":
        issues.append(
            ValidationIssue(
                "error",
                "P200",
                "Production mode requires apiVersion: nodrix.dev/v2",
                "apiVersion",
            )
        )
    if production and manifest.runtime.engine == "auto":
        issues.append(
            ValidationIssue(
                "error",
                "P201",
                "Production mode requires an explicit runtime engine",
                "runtime.engine",
            )
        )
    return issues
