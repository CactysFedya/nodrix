"""Unified human-facing presentation for ``plyctl system`` commands.

The System CLI is intentionally separated from execution semantics. These
renderers consume System/plan/backend snapshots and produce a compact,
borderless terminal view while leaving machine-readable ``--json`` contracts
unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from rich.console import Group, RenderableType
from rich.text import Text

from .presentation import format_duration


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _state(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "unknown").strip().lower()


def _state_style(value: object) -> str:
    state = _state(value)
    if state in {
        "valid",
        "prepared",
        "started",
        "running",
        "completed",
        "stopped",
        "ready",
        "ok",
    }:
        return "bold green"
    if state in {"failed", "invalid", "error", "dead"}:
        return "bold red"
    return "bold yellow"


def _state_symbol(value: object) -> str:
    state = _state(value)
    if state in {
        "valid",
        "prepared",
        "started",
        "completed",
        "stopped",
        "ready",
        "ok",
    }:
        return "✓"
    if state == "running":
        return "●"
    if state in {"failed", "invalid", "error", "dead"}:
        return "✗"
    return "!"


def _section(title: str) -> Text:
    return Text(title.upper(), style="bold cyan")


def _short_path(value: object) -> str:
    if value is None:
        return "-"
    text = str(value)
    if not text:
        return "-"
    normalized = text.replace("\\", "/")
    marker = "/.nodrix/"
    if marker in normalized:
        return ".nodrix/" + normalized.split(marker, 1)[1]
    try:
        path = Path(text).expanduser().resolve()
        cwd = Path.cwd().resolve()
        try:
            return str(path.relative_to(cwd))
        except ValueError:
            return str(path)
    except (OSError, RuntimeError, ValueError):
        return text


def _field(label: str, value: object, *, style: str | None = None) -> Text:
    text = Text()
    text.append(f"{label:<11}", style="dim")
    text.append(str(value), style=style)
    return text


def _header(prefix: str, name: object, state: object | None = None) -> Text:
    text = Text()
    text.append("NODRIX", style="bold cyan")
    text.append(f" {prefix.upper()} ", style="dim")
    text.append(str(name or "-"), style="bold")
    if state is not None:
        text.append("  ")
        text.append(_state(state).upper(), style=_state_style(state))
    return text


def _diagnostic_lines(items: Iterable[Any]) -> Text:
    lines = Text()
    for item in items:
        level = str(getattr(item, "level", "warning")).lower()
        code = str(getattr(item, "code", "DIAGNOSTIC"))
        path = str(getattr(item, "path", "") or "")
        message = str(getattr(item, "message", item))
        style = "red" if level == "error" else "yellow"
        symbol = "✗" if level == "error" else "!"
        lines.append(f"{symbol} {code}", style=f"bold {style}")
        if path:
            lines.append(f"  {path}", style="dim")
        lines.append(f"\n  {message}\n")
    return lines


def render_system_error(
    stage: str,
    message: object,
    *,
    code: str | None = None,
    hint: str | None = None,
) -> Group:
    title = Text()
    title.append("✗ ", style="bold red")
    title.append(f"{stage.upper()} FAILED", style="bold red")
    if code:
        title.append(f"  {code}", style="dim")

    body = Text()
    body.append("Error      ", style="dim")
    body.append(str(message), style="red")
    if hint:
        body.append("\nHint       ", style="dim")
        body.append(hint, style="cyan")
    return Group(title, Text(""), body)


def render_system_validation_result(
    *,
    name: str,
    valid: bool,
    mode: str,
    path: object,
    diagnostics: Iterable[Any],
) -> Group:
    items = list(diagnostics)
    state = "valid" if valid else "invalid"
    errors = sum(
        1
        for item in items
        if str(getattr(item, "level", "")).lower() == "error"
    )
    warnings = len(items) - errors

    meta = Text()
    meta.append_text(_field("File", _short_path(path), style="cyan"))
    meta.append("\n")
    meta.append_text(_field("Mode", mode))
    meta.append("\n")
    meta.append_text(_field("Diagnostics", f"{errors} errors · {warnings} warnings"))

    sections: list[RenderableType] = [
        _header("SYSTEM", name, state),
        Text(""),
        meta,
    ]
    if items:
        sections.extend(
            [Text(""), _section("DIAGNOSTICS"), _diagnostic_lines(items)]
        )
    else:
        sections.extend(
            [Text(""), Text("✓ contracts and references are valid", style="green")]
        )
    return Group(*sections)


def _plan_summary(plan: Any) -> str:
    summary = dict(getattr(plan, "summary", {}) or {})
    labels = (
        ("target", "targets"),
        ("resource", "resources"),
        ("app", "applications"),
        ("graph", "graphs"),
        ("node", "nodes"),
        ("connection", "connections"),
        ("link", "links"),
        ("artifact", "artifacts"),
    )
    parts: list[str] = []
    for singular, key in labels:
        count = int(summary.get(key, 0) or 0)
        noun = singular if count == 1 else singular + "s"
        parts.append(f"{count} {noun}")
    return " · ".join(parts)


def _backend_names(plan: Any) -> tuple[str, ...]:
    names: list[str] = []

    def add(value: object) -> None:
        text = str(value or "")
        if text and text not in names:
            names.append(text)

    for target in plan.targets:
        add(target.backend)
    for resource in plan.resources:
        add(resource.backend)
    for application in plan.applications:
        add(application.backend)
    for graph in plan.graphs:
        for backend in graph.backends:
            add(backend)
    for link in plan.links:
        add(link.source_backend)
        add(link.target_backend)
    for artifact in plan.artifacts:
        add(artifact.backend)
    return tuple(names)


def _backend_counts(
    plan: Any,
    backend: str,
) -> tuple[int, int, int, int, int, int, int]:
    targets = sum(1 for item in plan.targets if item.backend == backend)
    resources = sum(1 for item in plan.resources if item.backend == backend)
    applications = sum(1 for item in plan.applications if item.backend == backend)
    graphs = sum(1 for graph in plan.graphs if backend in graph.backends)
    nodes = sum(
        1
        for graph in plan.graphs
        for node in graph.nodes
        if node.backend == backend
    )
    inbound = sum(
        1
        for link in plan.links
        if link.target_backend == backend and link.source_backend != backend
    )
    outbound = sum(
        1
        for link in plan.links
        if link.source_backend == backend and link.target_backend != backend
    )
    return targets, resources, applications, graphs, nodes, inbound, outbound


def _join_pairs(values: Mapping[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values.items()) or "-"


def render_system_plan_result(plan: Any) -> Group:
    meta = Text()
    meta.append_text(_field("Schema", plan.schema_id))
    meta.append("\n")
    meta.append_text(
        _field("Revision", f"sha256:{plan.system_sha256[:12]}", style="cyan")
    )
    meta.append("\n")
    meta.append_text(_field("Shape", _plan_summary(plan)))
    backends = _backend_names(plan)
    if backends:
        meta.append("\n")
        meta.append_text(_field("Backends", ", ".join(backends)))

    sections: list[RenderableType] = [
        _header("PLAN", plan.system),
        Text(""),
        meta,
    ]

    if backends:
        lines = Text()
        for backend in backends:
            (
                targets,
                resources,
                applications,
                graphs,
                nodes,
                inbound,
                outbound,
            ) = _backend_counts(plan, backend)
            lines.append(
                "● ",
                style="green" if backend == "local" else "cyan",
            )
            lines.append(backend, style="bold")
            lines.append(
                f"  {targets} targets · {resources} resources · "
                f"{applications} apps · {graphs} graphs · {nodes} nodes "
                f"· in {inbound} · out {outbound}\n",
                style="dim",
            )
        sections.extend([Text(""), _section("BACKENDS"), lines])

    if plan.targets:
        lines = Text()
        for target in plan.targets:
            lines.append(
                "● ",
                style="green" if target.backend == "local" else "cyan",
            )
            lines.append(target.name, style="bold")
            lines.append(f"  {target.kind}")
            lines.append(f" · {target.backend}", style="dim")
            lines.append(
                " · implicit" if target.implicit else " · declared",
                style="dim",
            )
            lines.append("\n")
        sections.extend([Text(""), _section("TARGETS"), lines])

    if plan.resources:
        order = {
            name: index + 1
            for index, name in enumerate(plan.resource_order)
        }
        lines = Text()
        for resource in sorted(
            plan.resources,
            key=lambda item: order.get(item.name, item.ordinal + 1),
        ):
            lines.append(
                f"{order.get(resource.name, resource.ordinal + 1):>2} ",
                style="dim",
            )
            lines.append(resource.name, style="bold")
            lines.append(f"  {resource.uses}")
            lines.append(
                f" · {resource.target}/{resource.backend}",
                style="dim",
            )
            if resource.bindings:
                lines.append(
                    f" · {_join_pairs(resource.bindings)}",
                    style="dim",
                )
            lines.append("\n")
        sections.extend([Text(""), _section("RESOURCES"), lines])

    if plan.applications:
        lines = Text()
        for application in plan.applications:
            lines.append("● ", style="green")
            lines.append(application.name, style="bold")
            lines.append(f"  {application.uses}")
            lines.append(
                f" · {application.target}/{application.backend}",
                style="dim",
            )
            if application.resources:
                lines.append(
                    f" · resources {_join_pairs(application.resources)}",
                    style="dim",
                )
            lines.append("\n")
        sections.extend([Text(""), _section("APPLICATIONS"), lines])

    for graph in plan.graphs:
        lines = Text()
        order = {
            name: index + 1
            for index, name in enumerate(graph.topological_order)
        }
        by_source: dict[str, list[Any]] = defaultdict(list)
        for connection in graph.connections:
            by_source[str(connection.source).split(".", 1)[0]].append(connection)
        nodes = sorted(
            graph.nodes,
            key=lambda item: order.get(item.name, item.ordinal + 1),
        )
        if not nodes:
            lines.append("No nodes", style="dim")
        for node in nodes:
            lines.append(
                f"{order.get(node.name, node.ordinal + 1):>2} ",
                style="dim",
            )
            lines.append(node.name, style="bold")
            lines.append(f"  {node.uses}")
            lines.append(
                f"  [{node.target}/{node.backend}]",
                style="dim",
            )
            lines.append("\n")
            connections = by_source.get(node.name, [])
            for index, connection in enumerate(connections):
                lines.append(
                    "   └─ "
                    if index == len(connections) - 1
                    else "   ├─ ",
                    style="dim",
                )
                lines.append(connection.source, style="cyan")
                lines.append(" → ", style="dim")
                lines.append(connection.target)
                if connection.type_id:
                    lines.append(
                        f"  {connection.type_id}",
                        style="dim",
                    )
                lines.append("\n")
        sections.extend(
            [Text(""), _section(f"GRAPH {graph.name}"), lines]
        )

    if plan.links:
        lines = Text()
        for link in plan.links:
            lines.append("● ", style="cyan")
            lines.append(link.source, style="bold")
            lines.append(" → ", style="dim")
            lines.append(link.target, style="bold")
            lines.append(f" · {link.boundary}", style="yellow")
            lines.append(
                f" · {link.transport_uses or '-'}",
                style="cyan",
            )
            lines.append(
                f" · {link.source_backend}→{link.target_backend}",
                style="dim",
            )
            lines.append("\n")
        sections.extend([Text(""), _section("SYSTEM LINKS"), lines])

    if plan.artifacts:
        lines = Text()
        for artifact in plan.artifacts:
            lines.append("● ", style="green")
            lines.append(artifact.name, style="bold")
            lines.append(f"  {artifact.kind}")
            if artifact.path:
                lines.append(
                    f" · {_short_path(artifact.path)}",
                    style="cyan",
                )
            if artifact.producer:
                lines.append(
                    f" · producer {artifact.producer}",
                    style="dim",
                )
            lines.append("\n")
        sections.extend([Text(""), _section("ARTIFACTS"), lines])

    diagnostics = list(plan.diagnostics)
    if diagnostics:
        sections.extend(
            [
                Text(""),
                _section("DIAGNOSTICS"),
                _diagnostic_lines(diagnostics),
            ]
        )
    else:
        sections.extend(
            [Text(""), Text("✓ plan ready", style="bold green")]
        )
    return Group(*sections)


def render_backend_validation(report: Any) -> Group:
    items = list(report.diagnostics)
    title = Text()
    title.append("BACKEND  ", style="dim")
    title.append(str(report.backend), style="bold")
    title.append(
        f" · {len(report.errors)} errors · {len(report.warnings)} warnings",
        style="dim",
    )
    return Group(title, _diagnostic_lines(items))


def _graph_flow_lines(plan: Any) -> Text:
    lines = Text()
    for graph in plan.graphs:
        names = list(graph.topological_order) or [
            node.name for node in graph.nodes
        ]
        if not names:
            continue
        lines.append(f"{graph.name}  ", style="dim")
        for index, name in enumerate(names):
            if index:
                lines.append(" → ", style="dim")
            lines.append(str(name), style="cyan")
        lines.append("\n")
    return lines


def render_system_run_intro(system: Any, plan: Any, path: object) -> Group:
    meta = Text()
    meta.append_text(_field("File", _short_path(path), style="cyan"))
    meta.append("\n")
    meta.append_text(
        _field("Backend", ", ".join(_backend_names(plan)) or "-")
    )
    meta.append("\n")
    meta.append_text(_field("Shape", _plan_summary(plan)))

    flow = _graph_flow_lines(plan)
    sections: list[RenderableType] = [
        _header("RUN", system.name),
        Text(""),
        meta,
    ]
    if flow.plain:
        sections.extend([Text(""), _section("FLOW"), flow])
    if plan.diagnostics:
        sections.extend(
            [
                Text(""),
                _section("WARNINGS"),
                _diagnostic_lines(plan.diagnostics),
            ]
        )
    return Group(*sections)


def render_system_prepared(
    system_name: str,
    *,
    manifest_path: object = None,
) -> Group:
    line = Text()
    line.append("✓ PREPARED", style="bold green")
    line.append(f"  {system_name}", style="bold")
    if manifest_path:
        detail = _field(
            "Manifest",
            _short_path(manifest_path),
            style="cyan",
        )
        return Group(line, detail)
    return Group(line)


def render_system_started(
    system_name: str,
    *,
    backend: str,
    execution_id: str,
) -> Group:
    line = Text()
    line.append("✓ STARTED", style="bold green")
    line.append(f"  {system_name}", style="bold")
    detail = _field(
        "Execution",
        f"{backend}:{execution_id}",
        style="cyan",
    )
    return Group(line, detail)


def render_system_running(system_name: str, status: Any, plan: Any) -> Group:
    line = Text()
    line.append("● RUNNING", style="bold green")
    line.append(f"  {system_name}", style="bold")

    detail = Text()
    detail.append_text(
        _field(
            "Execution",
            f"{status.backend}:{status.execution_id}",
            style="cyan",
        )
    )
    detail.append("\n")
    detail.append_text(_field("Components", _plan_summary(plan)))
    detail.append("\n")
    detail.append_text(_field("Control", "Ctrl+C to stop"))
    return Group(line, detail)


def render_system_stopping(
    system_name: str,
    *,
    backend: str,
    execution_id: str,
) -> Group:
    line = Text()
    line.append("! STOPPING", style="bold yellow")
    line.append(f"  {system_name}", style="bold")
    return Group(
        line,
        _field(
            "Execution",
            f"{backend}:{execution_id}",
            style="cyan",
        ),
    )


def _report_nodes(
    report: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        str(name): _mapping(raw)
        for name, raw in _mapping(report.get("nodes", {})).items()
    }


def _report_apps(
    report: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    raw = (
        report.get("applications")
        or report.get("managed_applications")
        or {}
    )
    return {
        str(name): _mapping(value)
        for name, value in _mapping(raw).items()
    }


def _node_state(raw: Mapping[str, Any]) -> str:
    health = _mapping(raw.get("health", {}))
    return str(
        health.get("status")
        or health.get("state")
        or raw.get("status")
        or raw.get("state")
        or "unknown"
    )


def _report_stats(
    report: Mapping[str, Any],
) -> tuple[int, int, int]:
    nodes = _report_nodes(report)
    messages = max(
        (int(raw.get("messages", 0) or 0) for raw in nodes.values()),
        default=0,
    )
    errors = sum(
        int(raw.get("errors", 0) or 0)
        for raw in nodes.values()
    )
    drops = 0
    for edge in list(report.get("edges") or []):
        drops += int(
            _mapping(edge).get("overflow_drops", 0) or 0
        )
    if drops == 0:
        for raw in nodes.values():
            drops += int(
                _mapping(raw.get("resources", {})).get(
                    "overflow_drops",
                    0,
                )
                or 0
            )
    return messages, errors, drops


def _looks_continuous(plan: Any) -> bool:
    if plan.applications:
        return True
    for graph in plan.graphs:
        for node in graph.nodes:
            uses = str(node.uses).lower()
            if (
                uses.endswith(".source")
                or "_source" in uses
                or (uses.startswith("ros2.") and "source" in uses)
            ):
                return True
    return False


def _terminal_reason(
    state: str,
    status: Any,
    report: Mapping[str, Any],
    *,
    stop_requested: bool,
) -> str:
    if state == "failed":
        return str(
            status.message
            or _mapping(getattr(status, "details", {})).get("error")
            or report.get("error")
            or "runtime failed"
        )
    if state == "stopping":
        return str(
            status.message
            or "runtime is still stopping"
        )
    if state == "stopped":
        if stop_requested:
            return "stop requested by user"
        return str(
            status.message
            or report.get("reason")
            or "runtime stopped"
        )
    return str(
        status.message
        or report.get("reason")
        or "runtime returned normally"
    )


def render_system_terminal(
    system_name: str,
    status: Any,
    plan: Any,
    *,
    elapsed_seconds: float,
    stop_requested: bool = False,
) -> Group:
    state = _state(status.state)
    details = _mapping(getattr(status, "details", {}))
    report = _mapping(details.get("report", {}))
    duration = report.get("duration_seconds", elapsed_seconds)
    reason = _terminal_reason(
        state,
        status,
        report,
        stop_requested=stop_requested,
    )

    title = Text()
    title.append(
        f"{_state_symbol(state)} ",
        style=_state_style(state),
    )
    title.append(state.upper(), style=_state_style(state))
    title.append(f"  {system_name}", style="bold")
    title.append(f"  {format_duration(duration)}", style="dim")

    summary = Text()
    summary.append_text(
        _field(
            "Execution",
            f"{status.backend}:{status.execution_id}",
            style="cyan",
        )
    )
    summary.append("\n")
    summary.append_text(
        _field(
            "Reason",
            reason,
            style="red" if state == "failed" else None,
        )
    )

    messages, errors, drops = _report_stats(report)
    if report:
        summary.append("\n")
        summary.append_text(
            _field(
                "Traffic",
                f"{messages} messages · {errors} errors · {drops} drops",
            )
        )

    sections: list[RenderableType] = [title, Text(""), summary]

    nodes = _report_nodes(report)
    if nodes:
        lines = Text()
        for name, raw in nodes.items():
            node_state = _node_state(raw)
            lines.append(
                f"{_state_symbol(node_state)} ",
                style=_state_style(node_state),
            )
            lines.append(f"{name:<18}", style="bold")
            lines.append(
                node_state.upper(),
                style=_state_style(node_state),
            )
            rate = raw.get("rate_hz")
            if rate is not None:
                lines.append(
                    f" · {float(rate or 0.0):.1f} Hz",
                    style="cyan",
                )
            count = int(raw.get("messages", 0) or 0)
            if count:
                lines.append(f" · {count} msg", style="dim")
            node_errors = int(raw.get("errors", 0) or 0)
            if node_errors:
                lines.append(
                    f" · {node_errors} errors",
                    style="red",
                )
            health = _mapping(raw.get("health", {}))
            last_error = health.get("last_error")
            if last_error:
                lines.append(f"\n  {last_error}", style="red")
            lines.append("\n")
        sections.extend([Text(""), _section("COMPONENTS"), lines])

    applications = _report_apps(report)
    if applications:
        lines = Text()
        for name, raw in applications.items():
            app_state = str(
                raw.get("status")
                or raw.get("state")
                or "unknown"
            )
            lines.append(
                f"{_state_symbol(app_state)} ",
                style=_state_style(app_state),
            )
            lines.append(name, style="bold")
            lines.append(
                f"  {app_state.upper()}",
                style=_state_style(app_state),
            )
            error = raw.get("error") or raw.get("last_error")
            if error:
                lines.append(f" · {error}", style="red")
            lines.append("\n")
        sections.extend(
            [Text(""), _section("APPLICATIONS"), lines]
        )

    run_dir = report.get("run_dir") or report.get("artifact_dir")
    if run_dir:
        sections.extend(
            [
                Text(""),
                _field(
                    "Artifacts",
                    _short_path(run_dir),
                    style="cyan",
                ),
            ]
        )

    if (
        state == "completed"
        and not stop_requested
        and elapsed_seconds < 5.0
        and _looks_continuous(plan)
    ):
        warning = Text()
        warning.append(
            "! System completed without a stop request.",
            style="bold yellow",
        )
        warning.append(
            "\n  Continuous sources normally remain RUNNING; "
            "check source EOF, input connectivity, or early source shutdown.",
            style="yellow",
        )
        sections.extend([Text(""), warning])

    return Group(*sections)


def render_system_overview(system: Any, path: object) -> Group:
    counts = (
        f"{len(system.targets)} targets · {len(system.resources)} resources · "
        f"{len(system.applications)} apps · {len(system.graphs)} graphs · "
        f"{len(system.links)} links · {len(system.artifacts)} artifacts"
    )
    meta = Text()
    meta.append_text(_field("File", _short_path(path), style="cyan"))
    meta.append("\n")
    meta.append_text(
        _field("Schema", f"{system.api_version} · {system.kind}")
    )
    meta.append("\n")
    meta.append_text(_field("Shape", counts))
    if system.description:
        meta.append("\n")
        meta.append_text(_field("Description", system.description))

    sections: list[RenderableType] = [
        _header("SYSTEM", system.name),
        Text(""),
        meta,
    ]

    if system.targets:
        lines = Text()
        for target in system.targets:
            lines.append("● ", style="green")
            lines.append(target.name, style="bold")
            lines.append(f"  {target.kind}\n", style="dim")
        sections.extend([Text(""), _section("TARGETS"), lines])

    if system.resources:
        lines = Text()
        for resource in system.resources:
            lines.append("● ", style="green")
            lines.append(resource.name, style="bold")
            lines.append(f"  {resource.uses}\n")
        sections.extend([Text(""), _section("RESOURCES"), lines])

    if system.applications:
        lines = Text()
        for application in system.applications:
            lines.append("● ", style="green")
            lines.append(application.name, style="bold")
            lines.append(f"  {application.uses}\n")
        sections.extend(
            [Text(""), _section("APPLICATIONS"), lines]
        )

    if system.graphs:
        lines = Text()
        for graph in system.graphs:
            lines.append("● ", style="cyan")
            lines.append(graph.name, style="bold")
            lines.append(
                f"  {len(graph.nodes)} nodes · "
                f"{len(graph.connections)} connections\n",
                style="dim",
            )
        sections.extend([Text(""), _section("GRAPHS"), lines])

    if system.artifacts:
        lines = Text()
        for artifact in system.artifacts:
            lines.append("● ", style="green")
            lines.append(artifact.name, style="bold")
            lines.append(f"  {artifact.kind}")
            if artifact.path:
                lines.append(
                    f" · {_short_path(artifact.path)}",
                    style="cyan",
                )
            if artifact.producer:
                lines.append(
                    f" · {artifact.producer}",
                    style="dim",
                )
            lines.append("\n")
        sections.extend([Text(""), _section("ARTIFACTS"), lines])
    return Group(*sections)


def render_system_conversion(
    *,
    pipeline: object,
    destination: object,
    converted: Any,
) -> Group:
    state = "valid" if converted.lossless else "warning"
    title = _header(
        "CONVERT",
        getattr(converted.system, "name", "system"),
        state,
    )
    body = Text()
    body.append_text(
        _field("Input", _short_path(pipeline), style="cyan")
    )
    body.append("\n")
    body.append_text(
        _field("Output", _short_path(destination), style="cyan")
    )
    body.append("\n")
    body.append_text(_field("Lossless", converted.lossless))
    body.append("\n")
    body.append_text(_field("Reversible", converted.reversible))
    counts = converted.report.counts
    body.append("\n")
    body.append_text(
        _field(
            "Changes",
            f"{counts['transformed']} transformed · "
            f"{counts['deferred']} deferred · "
            f"{counts['unsupported']} unsupported",
        )
    )
    sections: list[RenderableType] = [title, Text(""), body]
    if converted.warnings:
        sections.extend(
            [
                Text(""),
                _section("WARNINGS"),
                _diagnostic_lines(converted.warnings),
            ]
        )
    else:
        sections.extend(
            [Text(""), Text("✓ conversion complete", style="green")]
        )
    return Group(*sections)


def render_schema_written(path: object) -> Group:
    line = Text()
    line.append("✓ SCHEMA WRITTEN", style="bold green")
    return Group(
        line,
        _field("Output", _short_path(path), style="cyan"),
    )


__all__ = [
    "render_backend_validation",
    "render_schema_written",
    "render_system_conversion",
    "render_system_error",
    "render_system_overview",
    "render_system_plan_result",
    "render_system_prepared",
    "render_system_run_intro",
    "render_system_running",
    "render_system_started",
    "render_system_stopping",
    "render_system_terminal",
    "render_system_validation_result",
]
