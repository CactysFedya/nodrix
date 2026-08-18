"""Semantic, borderless CLI presentation helpers for Nodrix/Plyctl.

This module intentionally depends only on the shape of runtime/system snapshots.
It does not own execution semantics. Human-facing renderers can therefore evolve
without changing ``--json`` contracts or runtime behavior.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from rich.console import Group, RenderableType
from rich.text import Text


GOOD_STATES = {
    "healthy",
    "ok",
    "ready",
    "running",
    "completed",
    "stopped",
    "valid",
}
WARN_STATES = {
    "degraded",
    "warning",
    "warn",
    "starting",
    "stopping",
    "restarting",
    "unknown",
}
BAD_STATES = {
    "failed",
    "error",
    "unhealthy",
    "dead",
    "invalid",
}


@dataclass(frozen=True)
class TopViewSpec:
    """Built-in human-view template.

    ``compact`` remains a compatibility alias for ``overview``.  The shape is
    deliberately small so a future ``nodrix.view/v1`` loader can map YAML onto
    the same model without touching renderers.
    """

    name: str
    show_runtime: bool = True
    show_health: bool = True
    show_graph: bool = True
    show_applications: bool = True
    show_monitors: bool = False
    show_node_performance: bool = False
    show_all_edges: bool = False
    show_attention: bool = True
    show_debug_details: bool = False


TOP_VIEW_SPECS: dict[str, TopViewSpec] = {
    "overview": TopViewSpec(name="overview"),
    "performance": TopViewSpec(
        name="performance",
        show_node_performance=True,
        show_all_edges=True,
    ),
    "operations": TopViewSpec(
        name="operations",
        show_monitors=True,
        show_all_edges=True,
    ),
    "debug": TopViewSpec(
        name="debug",
        show_monitors=True,
        show_node_performance=True,
        show_all_edges=True,
        show_debug_details=True,
    ),
}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def format_bytes(value: object) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    index = 0
    while abs(number) >= 1024.0 and index < len(units) - 1:
        number /= 1024.0
        index += 1
    return f"{number:.1f} {units[index]}"



def format_duration(value: object) -> str:
    try:
        seconds = max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return "-"
    if seconds < 1.0:
        milliseconds = seconds * 1000.0
        if milliseconds < 1.0 and seconds > 0:
            return "<1 ms"
        return f"{milliseconds:.0f} ms"
    if seconds < 60.0:
        return f"{seconds:.1f}s" if not seconds.is_integer() else f"{int(seconds)}s"
    whole = int(seconds)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def _bar(value: float, maximum: float, width: int = 18) -> str:
    ratio = 0.0 if maximum <= 0 else min(max(value / maximum, 0.0), 1.0)
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


def _state(value: object) -> str:
    return str(value or "unknown").strip().lower()


def _state_style(value: object) -> str:
    state = _state(value)
    if state in GOOD_STATES:
        return "bold green"
    if state in BAD_STATES:
        return "bold red"
    if state in WARN_STATES:
        return "bold yellow"
    return "bold yellow"


def _state_symbol(value: object) -> str:
    state = _state(value)
    if state in GOOD_STATES:
        return "✓"
    if state in BAD_STATES:
        return "✗"
    if state in WARN_STATES:
        return "!"
    return "!"


def _section(title: str) -> Text:
    return Text(title.upper(), style="bold cyan")


def _header(
    name: object,
    status: object,
    duration: object,
    *,
    prefix: str = "NODRIX",
    suffix: str | None = None,
) -> Text:
    text = Text()
    text.append(prefix, style="bold cyan")
    text.append("  ")
    text.append(str(name or "-"), style="bold")
    text.append("  ")
    normalized = str(status or "unknown").upper()
    text.append(normalized, style=_state_style(status))
    rendered_duration = format_duration(duration)
    if rendered_duration != "-":
        text.append(f"  {rendered_duration}", style="dim")
    if suffix:
        text.append(f"\n{suffix}", style="dim")
    return text


def _nodes(data: Mapping[str, object]) -> dict[str, dict[str, Any]]:
    return {
        str(name): _mapping(raw)
        for name, raw in _mapping(data.get("nodes", {})).items()
    }


def _applications(data: Mapping[str, object]) -> dict[str, dict[str, Any]]:
    raw = data.get("applications") or data.get("managed_applications") or {}
    return {
        str(name): _mapping(value)
        for name, value in _mapping(raw).items()
    }


def _edges(data: Mapping[str, object]) -> list[dict[str, Any]]:
    return [_mapping(item) for item in list(data.get("edges") or [])]


def _executor_resources(nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    for raw in nodes.values():
        resources = _mapping(raw.get("resources", {}))
        if resources.get("scope") == "executor_shared":
            return resources
    return {}


def _machine_totals(data: Mapping[str, object]) -> tuple[float, float, int, float]:
    nodes = _nodes(data)
    applications = _applications(data)
    system = _mapping(data.get("system", {}))
    executor = _executor_resources(nodes)

    if executor:
        cpu = float(executor.get("executor_cpu_percent", 0.0) or 0.0)
        rss = float(executor.get("executor_rss_bytes", 0.0) or 0.0)
    else:
        cpu = float(
            system.get("process_cpu_percent", system.get("cpu_percent", 0.0))
            or 0.0
        )
        rss = float(
            system.get("process_rss_bytes", system.get("rss_bytes", 0.0))
            or 0.0
        )

    for raw in applications.values():
        resources = _mapping(raw.get("resources", raw))
        cpu += float(resources.get("cpu_percent", 0.0) or 0.0)
        rss += float(resources.get("rss_bytes", 0.0) or 0.0)

    cpu_count = max(int(system.get("cpu_count", 1) or 1), 1)
    total_memory = float(system.get("memory_total_bytes", 0.0) or 0.0)
    return cpu, rss, cpu_count, total_memory



def _machine_line(data: Mapping[str, object]) -> Text:
    system = _mapping(data.get("system", {}))
    cpu, rss, cpu_count, total_memory = _machine_totals(data)
    used_cores = max(cpu, 0.0) / 100.0

    text = Text()
    text.append("CPU  ", style="bold")
    text.append(f"{used_cores:.2f} / {cpu_count} {'core' if cpu_count == 1 else 'cores'}")
    text.append("   RAM  ", style="bold")
    text.append(format_bytes(rss))
    if total_memory > 0:
        text.append(f" / {format_bytes(total_memory)}")

    secondary: list[tuple[str, str, str | None]] = []
    temperature = system.get("temperature_c")
    if temperature is not None:
        value = float(temperature)
        style = "red" if value >= 85 else "yellow" if value >= 75 else "green"
        secondary.append(("TEMP", f"{value:.1f}°C", style))

    load = list(system.get("load_average") or [])
    if load:
        secondary.append(
            ("LOAD", " · ".join(f"{float(item):.2f}" for item in load[:3]), None)
        )

    if secondary:
        text.append("\n")
        for index, (label, value, style) in enumerate(secondary):
            if index:
                text.append("   ")
            text.append(f"{label} ", style="bold")
            text.append(value, style=style)
    return text


def _health_counts(data: Mapping[str, object]) -> tuple[int, int, int, int]:
    healthy = degraded = failed = unknown = 0
    for raw in _nodes(data).values():
        health = _mapping(raw.get("health", {}))
        state = _state(health.get("status"))
        if state in GOOD_STATES:
            healthy += 1
        elif state in BAD_STATES:
            failed += 1
        elif state in WARN_STATES:
            degraded += 1
        else:
            unknown += 1
    return healthy, degraded, failed, unknown


def _health_summary(data: Mapping[str, object]) -> Text:
    healthy, degraded, failed, unknown = _health_counts(data)
    text = Text()
    text.append(f"✓ {healthy} healthy", style="green")
    text.append("   ")
    text.append(f"! {degraded} degraded", style="yellow")
    text.append("   ")
    text.append(f"✗ {failed} failed", style="red")
    if unknown:
        text.append(f"   ? {unknown} unknown", style="dim")
    return text


def _runtime_order(data: Mapping[str, object]) -> list[str]:
    nodes = _nodes(data)
    indegree = {name: 0 for name in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in _edges(data):
        source = str(edge.get("source") or "").split(".", 1)[0]
        target = str(edge.get("target") or "").split(".", 1)[0]
        if source not in nodes or target not in nodes or source == target:
            continue
        outgoing[source].append(target)
        indegree[target] = indegree.get(target, 0) + 1
    ready = deque(name for name in nodes if indegree.get(name, 0) == 0)
    ordered: list[str] = []
    while ready:
        name = ready.popleft()
        ordered.append(name)
        for target in outgoing.get(name, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    ordered.extend(name for name in nodes if name not in ordered)
    return ordered


def _node_status(raw: Mapping[str, Any]) -> str:
    health = _mapping(raw.get("health", {}))
    return str(health.get("status") or health.get("state") or "unknown")


def _node_rate_label(name: str) -> str:
    return "monitor Hz" if name.endswith("_health") else "Hz"



def _node_line(
    name: str,
    raw: Mapping[str, Any],
    *,
    performance: bool,
    bottleneck_p95: float,
) -> Text:
    # A relative maximum is not itself a problem. Without an explicit
    # rate/latency target Nodrix must not label a healthy node a bottleneck.
    _ = bottleneck_p95
    resources = _mapping(raw.get("resources", {}))
    info = _mapping(raw.get("runtime_info", {}))
    status = _node_status(raw)
    rate = float(raw.get("rate_hz", 0.0) or 0.0)
    p95 = float(
        raw.get(
            "p95_ms",
            _mapping(raw.get("processing", {})).get("p95_ms", 0.0),
        )
        or 0.0
    )

    text = Text()
    text.append(f"{_state_symbol(status)} ", style=_state_style(status))
    text.append(name, style="bold")
    text.append(f"  {rate:.1f} {_node_rate_label(name)}", style="cyan")

    if performance:
        text.append(f"  p95 {p95:.2f} ms")
        if resources.get("scope") == "executor_shared":
            text.append("  shared executor", style="dim")
        else:
            if resources.get("cpu_percent") is not None:
                text.append(
                    f"  CPU {float(resources.get('cpu_percent', 0.0)) / 100.0:.2f} core"
                )
            memory = resources.get("rss_bytes") or resources.get("shared_buffer_bytes")
            if memory:
                text.append(f"  RAM {format_bytes(memory)}")
        backend = info.get("backend")
        if backend:
            text.append(
                f"  {backend}",
                style="green" if info.get("hardware") else "cyan",
            )
        threads = info.get("threads")
        if threads is not None:
            text.append(f" · {threads} threads", style="dim")
        stale = int(resources.get("stale_skips", 0) or 0)
        overflow = int(resources.get("overflow_drops", 0) or 0)
        sync = int(resources.get("sync_misses", 0) or 0)
        if stale:
            text.append(f"  stale={stale}", style="dim")
        if overflow:
            text.append(f"  overflow={overflow}", style="red")
        if sync:
            text.append(f"  sync={sync}", style="magenta")

    if _state(status) not in GOOD_STATES:
        text.append(f"  {str(status).upper()}", style=_state_style(status))
    return text


def _edge_label(edge: Mapping[str, Any], *, detailed: bool) -> Text:
    depth = int(edge.get("depth", 0) or 0)
    capacity = max(int(edge.get("capacity", 0) or 0), 0)
    policy = str(edge.get("policy") or "-")
    stale = int(edge.get("stale_skips", 0) or 0)
    overflow = int(edge.get("overflow_drops", 0) or 0)

    text = Text()
    text.append(str(edge.get("source") or "?"), style="cyan")
    text.append(" → ", style="dim")
    text.append(str(edge.get("target") or "?"))
    if detailed:
        text.append(f"  {policy} {depth}/{capacity}", style="dim")
        if stale:
            text.append(f"  stale={stale}", style="yellow")
        if overflow:
            text.append(f"  overflow={overflow}", style="red")
    else:
        text.append(f"  {policy}", style="dim")
    return text


def _graph(data: Mapping[str, object], *, performance: bool) -> Text:
    nodes = _nodes(data)
    edges = _edges(data)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        source = str(edge.get("source") or "").split(".", 1)[0]
        outgoing[source].append(edge)

    throughput = [
        raw
        for raw in nodes.values()
        if bool(_mapping(raw.get("health", {})).get("participates_in_throughput", True))
    ]
    bottleneck_p95 = max(
        (
            float(raw.get("p95_ms", 0.0) or 0.0)
            for raw in throughput
        ),
        default=0.0,
    )

    text = Text()
    order = _runtime_order(data)
    for index, name in enumerate(order):
        raw = nodes[name]
        text.append_text(
            _node_line(
                name,
                raw,
                performance=performance,
                bottleneck_p95=bottleneck_p95,
            )
        )
        text.append("\n")
        node_edges = outgoing.get(name, [])
        for edge_index, edge in enumerate(node_edges):
            branch = "  └─ " if edge_index == len(node_edges) - 1 else "  ├─ "
            text.append(branch, style="dim")
            text.append_text(_edge_label(edge, detailed=performance))
            text.append("\n")
        if index != len(order) - 1 and not node_edges:
            text.append("  ↓\n", style="dim")
    if not nodes:
        text.append("No runtime nodes", style="dim")
    return text


def _application_status(raw: Mapping[str, Any]) -> str:
    status = raw.get("status") or raw.get("health")
    if status:
        return str(status)
    return "running" if raw.get("running") else "unknown"


def _application_lines(
    data: Mapping[str, object],
    *,
    operations: bool,
    debug: bool = False,
) -> Text:
    applications = _applications(data)
    text = Text()
    if not applications:
        text.append("No managed applications", style="dim")
        return text
    for name, raw in applications.items():
        status = _application_status(raw)
        resources = _mapping(raw.get("resources", raw))
        text.append(f"{_state_symbol(status)} ", style=_state_style(status))
        text.append(name, style="bold")
        text.append(f"  {status}", style=_state_style(status))
        pid = raw.get("pid")
        if pid:
            text.append(f"  pid {pid}", style="dim")
        text.append(f"  CPU {float(resources.get('cpu_percent', 0.0) or 0.0):.1f}%")
        text.append(f"  RAM {format_bytes(resources.get('rss_bytes', 0))}")
        if operations or debug:
            process_count = resources.get("process_count", raw.get("process_count", raw.get("proc")))
            thread_count = resources.get("thread_count", raw.get("thread_count", raw.get("threads")))
            restarts = int(raw.get("restart_count", raw.get("restarts", 0)) or 0)
            if process_count is not None:
                text.append(f"  proc {process_count}")
            if thread_count is not None:
                text.append(f"  threads {thread_count}")
            text.append(f"  restarts {restarts}")
        text.append("\n")
    return text


def _monitor_lines(data: Mapping[str, object], *, debug: bool) -> Text:
    text = Text()
    monitors = {
        name: raw
        for name, raw in _nodes(data).items()
        if name.endswith("_health") or "topic_monitor" in str(raw.get("uses", ""))
    }
    if not monitors:
        text.append("No dedicated monitors", style="dim")
        return text
    for name, raw in monitors.items():
        health = _mapping(raw.get("health", {}))
        status = health.get("status", "unknown")
        text.append(f"{_state_symbol(status)} ", style=_state_style(status))
        text.append(name.removesuffix("_health"), style="bold")
        text.append(f"  {float(raw.get('rate_hz', 0.0) or 0.0):.1f} Hz")
        text.append(f"  p95 {float(raw.get('p95_ms', 0.0) or 0.0):.2f} ms")
        if debug:
            text.append(f"  messages {int(raw.get('messages', 0) or 0)}")
        if _state(status) not in GOOD_STATES:
            text.append(f"  {str(status).upper()}", style=_state_style(status))
        text.append("\n")
    return text


def _edge_lines(data: Mapping[str, object], *, all_edges: bool) -> Text:
    text = Text()
    shown = 0
    for edge in _edges(data):
        depth = int(edge.get("depth", 0) or 0)
        stale = int(edge.get("stale_skips", 0) or 0)
        overflow = int(edge.get("overflow_drops", 0) or 0)
        if not all_edges and not (depth or stale or overflow):
            continue
        shown += 1
        text.append_text(_edge_label(edge, detailed=True))
        text.append("\n")
    if shown == 0:
        text.append("✓ no active queue pressure or overflow", style="green")
    return text



def _attention(data: Mapping[str, object]) -> Text:
    # Only actionable problems belong here. Relative ranking such as
    # "highest p95" remains a measurement unless an explicit target is violated.
    text = Text()
    nodes = _nodes(data)
    applications = _applications(data)

    for name, raw in nodes.items():
        health = _mapping(raw.get("health", {}))
        status = health.get("status", "unknown")
        state = _state(status)
        if state in BAD_STATES:
            text.append("✗ ", style="red")
            text.append(name, style="bold")
            text.append(f" is {status}")
            error = health.get("last_error")
            if error:
                text.append(f" · {error}", style="red")
            text.append("\n")
        elif state not in GOOD_STATES:
            text.append("! ", style="yellow")
            text.append(name, style="bold")
            text.append(f" is {status}")
            pressure = float(health.get("queue_pressure", 0.0) or 0.0)
            if pressure:
                text.append(f" · queue pressure {pressure:.2f}")
            text.append("\n")

    overflow_total = 0
    for edge in _edges(data):
        overflow = int(edge.get("overflow_drops", 0) or 0)
        overflow_total += overflow
        capacity = int(edge.get("capacity", 0) or 0)
        depth = int(edge.get("depth", 0) or 0)
        if capacity > 0 and depth / capacity >= 0.8:
            text.append("! ", style="yellow")
            text.append(
                f"{edge.get('source')} → {edge.get('target')}",
                style="bold",
            )
            text.append(f" queue pressure {depth}/{capacity}\n")
    if overflow_total:
        text.append(
            f"✗ {overflow_total} queue overflow drop(s)\n",
            style="red",
        )

    restart_total = 0
    for name, raw in applications.items():
        status = _application_status(raw)
        restarts = int(raw.get("restart_count", raw.get("restarts", 0)) or 0)
        restart_total += restarts
        if _state(status) not in GOOD_STATES:
            text.append("! ", style="yellow")
            text.append(name, style="bold")
            text.append(f" application is {status}\n")
    if restart_total:
        text.append(
            f"! {restart_total} managed application restart(s)\n",
            style="yellow",
        )
    return text



def render_top_view(
    data: dict[str, object],
    view: str | TopViewSpec = "compact",
) -> Group:
    if isinstance(view, TopViewSpec):
        spec = view
        selected = spec.name.strip().lower()
    else:
        selected = view.strip().lower()
        if selected == "compact":
            selected = "overview"
        if selected not in TOP_VIEW_SPECS:
            choices = (
                "overview, performance, operations, debug "
                "(compact is an alias for overview)"
            )
            raise ValueError(f"Unknown top view {view!r}; choose {choices}")
        spec = TOP_VIEW_SPECS[selected]

    sections: list[RenderableType] = [
        _header(
            data.get("pipeline", "-"),
            data.get("status", "running"),
            data.get("duration_seconds", 0.0),
            suffix=f"view {spec.name}",
        ),
    ]
    if spec.show_runtime:
        sections.extend([Text(""), _machine_line(data)])
    if spec.show_health:
        sections.append(_health_summary(data))

    if spec.show_graph:
        sections.extend(
            [
                Text(""),
                _section(
                    "GRAPH" if not spec.show_node_performance else "PERFORMANCE"
                ),
                _graph(data, performance=spec.show_node_performance),
            ]
        )

    applications = _applications(data)
    if spec.show_applications and (applications or spec.show_debug_details):
        sections.extend(
            [
                Text(""),
                _section("APPLICATIONS"),
                _application_lines(
                    data,
                    operations=spec.show_monitors or spec.show_debug_details,
                    debug=spec.show_debug_details,
                ),
            ]
        )

    monitors = {
        name: raw
        for name, raw in _nodes(data).items()
        if name.endswith("_health")
        or "topic_monitor" in str(raw.get("uses", ""))
    }
    if spec.show_monitors and (monitors or spec.show_debug_details):
        sections.extend(
            [
                Text(""),
                _section("MONITORS"),
                _monitor_lines(data, debug=spec.show_debug_details),
            ]
        )

    if spec.show_all_edges or selected == "debug":
        sections.extend(
            [
                Text(""),
                _section("QUEUES"),
                _edge_lines(data, all_edges=spec.show_debug_details),
            ]
        )

    if spec.show_attention:
        attention = _attention(data)
        if attention.plain.strip():
            sections.extend([Text(""), _section("ATTENTION"), attention])

    if spec.show_debug_details:
        system = _mapping(data.get("system", {}))
        executor = _executor_resources(_nodes(data))
        debug = Text()
        if executor:
            debug.append("shared executor", style="bold")
            debug.append(
                f"  CPU "
                f"{float(executor.get('executor_cpu_percent', 0.0) or 0.0) / 100.0:.2f} core"
                f"  RAM {format_bytes(executor.get('executor_rss_bytes', 0))}\n"
            )
        if system:
            for key in sorted(system):
                if key in {
                    "load_average",
                    "temperature_c",
                    "cpu_count",
                    "memory_total_bytes",
                }:
                    continue
                debug.append(f"{key}: {system[key]}\n", style="dim")
        sections.extend(
            [
                Text(""),
                _section("DEBUG"),
                debug or Text("No extra debug fields", style="dim"),
            ]
        )
    return Group(*sections)


def render_status(data: dict[str, object], *, run_id: str | None = None) -> Group:
    """Render a concise semantic status summary instead of a node table."""

    nodes = _nodes(data)
    applications = _applications(data)
    issues: list[tuple[str, dict[str, Any]]] = []
    for name, raw in nodes.items():
        status = _node_status(raw)
        if _state(status) not in GOOD_STATES:
            issues.append((name, raw))

    details = Text()
    if issues:
        for name, raw in issues:
            health = _mapping(raw.get("health", {}))
            status = _node_status(raw)
            details.append(f"{_state_symbol(status)} ", style=_state_style(status))
            details.append(name, style="bold")
            details.append(f"  {str(status).upper()}", style=_state_style(status))
            pressure = float(health.get("queue_pressure", 0.0) or 0.0)
            if pressure:
                details.append(f"  queue pressure {pressure:.2f}")
            restarts = int(health.get("restart_count", 0) or 0)
            if restarts:
                details.append(f"  restarts {restarts}", style="yellow")
            error = health.get("last_error")
            if error:
                details.append(f"\n  {error}", style="red")
            details.append("\n")
    else:
        details.append(f"✓ {len(nodes)}/{len(nodes)} runtime components healthy\n", style="green")
        if applications:
            bad_apps = [
                name
                for name, raw in applications.items()
                if _state(_application_status(raw)) not in GOOD_STATES
            ]
            if bad_apps:
                details.append(f"! applications need attention: {', '.join(bad_apps)}\n", style="yellow")
            else:
                details.append("✓ managed applications running\n", style="green")
        overflow = sum(int(edge.get("overflow_drops", 0) or 0) for edge in _edges(data))
        if overflow:
            details.append(f"✗ {overflow} queue overflow drop(s)\n", style="red")
        else:
            details.append("✓ no queue overflow\n", style="green")

    metadata = Text()
    if run_id:
        metadata.append("Run      ", style="dim")
        metadata.append(str(run_id))
        metadata.append("\n")
    if data.get("artifact_dir"):
        metadata.append("Artifacts", style="dim")
        metadata.append(f"  {data.get('artifact_dir')}")

    sections: list[RenderableType] = [
        _header(
            data.get("pipeline", run_id or "-"),
            data.get("status", "unknown"),
            data.get("duration_seconds", 0.0),
        ),
        Text(""),
        _health_summary(data),
        _machine_line(data),
        Text(""),
        _section("STATUS"),
        details,
    ]
    if metadata.plain:
        sections.extend([Text(""), metadata])
    return Group(*sections)



def render_health(data: dict[str, object]) -> Group:
    lines = Text()
    run_state = _state(data.get("status"))
    terminal = run_state in {"completed", "stopped", "failed"}

    for name, raw in _nodes(data).items():
        health = _mapping(raw.get("health", {}))
        status = health.get("status", health.get("state", "unknown"))
        state = str(health.get("state") or "").strip().lower()

        lines.append(f"{_state_symbol(status)} ", style=_state_style(status))
        lines.append(name, style="bold")

        if terminal:
            lifecycle = state.upper() if state else "STOPPED"
            lines.append(f"  {lifecycle}", style="dim")
            lines.append(f" · {str(status).lower()}", style=_state_style(status))
        else:
            lines.append(f"  {str(status).upper()}", style=_state_style(status))
            if health.get("ready"):
                lines.append(" · ready", style="green")
            elif health.get("alive"):
                lines.append(" · alive", style="dim")
            else:
                lines.append(" · not ready", style="yellow")

        pressure = float(health.get("queue_pressure", 0.0) or 0.0)
        if pressure:
            lines.append(
                f"  queue {pressure:.2f}",
                style="yellow" if pressure >= 0.8 else "dim",
            )
        restarts = int(health.get("restart_count", 0) or 0)
        if restarts:
            lines.append(f"  restarts {restarts}", style="yellow")
        error = health.get("last_error")
        if error:
            lines.append(f"\n  {error}", style="red")
        lines.append("\n")

    if not lines.plain:
        lines.append("No runtime nodes", style="dim")

    footer = Text()
    healthy, degraded, failed, unknown = _health_counts(data)
    total = healthy + degraded + failed + unknown
    if terminal and total and failed == 0 and degraded == 0:
        footer.append(f"✓ {total}/{total} completed cleanly", style="green")

    sections: list[RenderableType] = [
        _header(
            data.get("pipeline", "-"),
            data.get("status", "unknown"),
            data.get("duration_seconds", 0.0),
        ),
        Text(""),
        _health_summary(data),
        Text(""),
        _section("COMPONENTS"),
        lines,
    ]
    if footer.plain:
        sections.extend([Text(""), footer])
    return Group(*sections)


def _short_artifact_path(value: object) -> str:
    text = str(value or "")
    if not text:
        return "-"
    normalized = text.replace("\\", "/")
    marker = "/.nodrix/"
    if marker in normalized:
        return ".nodrix/" + normalized.split(marker, 1)[1]
    if normalized.endswith("/.nodrix"):
        return ".nodrix"
    return text



def render_run_summary(report: Mapping[str, object]) -> Group:
    nodes = _nodes(report)
    status = str(report.get("status", "completed"))
    duration = report.get("duration_seconds", 0.0)

    message_count = max(
        (int(raw.get("messages", 0) or 0) for raw in nodes.values()),
        default=0,
    )
    error_count = sum(
        int(raw.get("errors", 0) or 0)
        for raw in nodes.values()
    )
    drop_count = sum(
        int(edge.get("overflow_drops", 0) or 0)
        for edge in _edges(report)
    )
    if drop_count == 0:
        drop_count = sum(
            int(_mapping(raw.get("resources", {})).get("overflow_drops", 0) or 0)
            for raw in nodes.values()
        )

    summary = Text()
    summary.append(f"{message_count} messages", style="cyan")
    summary.append(f" · {error_count} errors")
    summary.append(f" · {drop_count} drops")

    sections: list[RenderableType] = [
        _header(report.get("pipeline", "-"), status, duration),
        Text(""),
        summary,
    ]
    run_dir = report.get("run_dir") or report.get("artifact_dir")
    if run_dir:
        artifacts = Text()
        artifacts.append("Artifacts  ", style="dim")
        artifacts.append(_short_artifact_path(run_dir), style="cyan")
        sections.extend([Text(""), artifacts])
    return Group(*sections)


def render_run_active_info(
    artifacts_root: object,
    *,
    monitor_command: str | None = None,
) -> Group:
    lines = Text()
    lines.append("Artifacts  ", style="dim")
    lines.append(_short_artifact_path(artifacts_root), style="cyan")
    if monitor_command:
        lines.append("\n")
        lines.append("Monitor    ", style="dim")
        lines.append(monitor_command, style="cyan")
    return Group(Text(""), lines)


def _join_pairs(values: Mapping[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values.items()) or "-"


def _plan_backend_names(plan: Any) -> tuple[str, ...]:
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


def _backend_counts(plan: Any, backend: str) -> tuple[int, int, int, int, int, int, int]:
    targets = sum(1 for item in plan.targets if item.backend == backend)
    resources = sum(1 for item in plan.resources if item.backend == backend)
    applications = sum(1 for item in plan.applications if item.backend == backend)
    graphs = sum(1 for graph in plan.graphs if backend in graph.backends)
    nodes = sum(1 for graph in plan.graphs for node in graph.nodes if node.backend == backend)
    inbound = sum(1 for link in plan.links if link.target_backend == backend and link.source_backend != backend)
    outbound = sum(1 for link in plan.links if link.source_backend == backend and link.target_backend != backend)
    return targets, resources, applications, graphs, nodes, inbound, outbound


def _plan_summary(plan: Any) -> Text:
    summary = plan.summary
    labels = (
        ("system", "systems"),
        ("target", "targets"),
        ("resource", "resources"),
        ("application", "applications"),
        ("graph", "graphs"),
        ("node", "nodes"),
        ("connection", "connections"),
        ("link", "links"),
        ("artifact", "artifacts"),
    )
    parts: list[str] = []
    for singular, key in labels:
        count = int(summary.get(key, 0) or 0)
        plural = singular if count == 1 else singular + "s"
        parts.append(f"{count} {plural}")
    return Text(" · ".join(parts), style="dim")


def _system_plan_tree(
    plan: Any,
) -> Text:
    """Render recursive child-System composition without changing plan semantics."""

    lines = Text()

    lines.append("● ", style="cyan")
    lines.append(
        str(plan.system),
        style="bold",
    )
    lines.append(
        f"  sha256:{str(plan.system_sha256)[:12]}",
        style="dim",
    )
    lines.append("\n")

    def append_children(
        parent: Any,
        prefix: str,
    ) -> None:
        children = tuple(
            parent.systems
        )

        for index, child in enumerate(
            children
        ):
            last = (
                index
                == len(children) - 1
            )

            connector = (
                "└─ "
                if last
                else "├─ "
            )

            lines.append(
                prefix + connector,
                style="dim",
            )

            # Left side is the instance role inside the parent.
            lines.append(
                str(child.name),
                style="bold",
            )

            # Right side is the independently identified System Definition.
            lines.append(
                " → ",
                style="dim",
            )
            lines.append(
                str(child.plan.system),
                style="cyan",
            )

            lines.append(
                "  "
                f"sha256:{str(child.plan.system_sha256)[:12]}",
                style="dim",
            )
            lines.append("\n")

            append_children(
                child.plan,
                prefix
                + (
                    "   "
                    if last
                    else "│  "
                ),
            )

    append_children(
        plan,
        "",
    )

    return lines



def _execution_state_value(value: object) -> str:
    state = getattr(value, "value", value)
    return str(state or "unknown").strip().lower()


def _execution_state_symbol(value: object) -> str:
    state = _execution_state_value(value)

    if state == "failed":
        return "✗"
    if state == "completed":
        return "✓"
    if state == "stopped":
        return "■"
    if state == "running":
        return "●"
    if state == "prepared":
        return "○"
    if state == "stopping":
        return "!"

    return "!"


def _execution_state_style(value: object) -> str:
    return _state_style(
        _execution_state_value(value)
    )


def _execution_has_failed_child(status: Any) -> bool:
    for item in getattr(status, "scopes", ()):
        if (
            _execution_state_value(
                item.status.state
            )
            == "failed"
        ):
            return True

    for child in getattr(status, "systems", ()):
        if (
            _execution_state_value(
                child.status.state
            )
            == "failed"
        ):
            return True

    return False




def _execution_visible_details(
    status: Any,
) -> tuple[tuple[str, str], ...]:
    """Return stable execution details suitable for human presentation.

    The list is intentionally conservative. Arbitrary runtime telemetry and
    backend-specific report payloads are not exposed as canonical CLI state.
    """

    raw = getattr(
        status,
        "details",
        {},
    )

    if not isinstance(
        raw,
        Mapping,
    ):
        return ()

    details = dict(raw)

    message = getattr(
        status,
        "message",
        None,
    )
    message_text = (
        str(message)
        if message is not None
        else None
    )

    result: list[
        tuple[str, str]
    ] = []

    def add(
        label: str,
        value: object,
    ) -> None:
        if value is None:
            return

        rendered = str(value).strip()
        if not rendered:
            return

        if (
            message_text is not None
            and rendered == message_text
        ):
            return

        item = (
            label,
            rendered,
        )

        if item not in result:
            result.append(item)

    exception_type = details.get(
        "exception_type"
    )

    if (
        exception_type is not None
        and (
            message_text is None
            or not message_text.startswith(
                f"{exception_type}:"
            )
        )
    ):
        add(
            "exception",
            exception_type,
        )

    add(
        "error",
        details.get("error"),
    )
    add(
        "source",
        details.get(
            "failure_source"
        ),
    )
    add(
        "scope",
        details.get("scope"),
    )
    add(
        "backend",
        details.get("backend"),
    )
    add(
        "system",
        details.get("system"),
    )

    return tuple(result)


def _execution_observation_fingerprint(
    status: Any,
) -> tuple[Any, ...] | None:
    """Return the presentation-relevant execution observation."""

    observation = getattr(
        status,
        "observation",
        None,
    )
    if observation is None:
        return None

    health = getattr(
        observation,
        "health",
        None,
    )
    health_value = getattr(
        health,
        "value",
        health,
    )

    return (
        getattr(
            observation,
            "ready",
            None,
        ),
        (
            str(health_value)
            if health_value is not None
            else "unknown"
        ),
        getattr(
            observation,
            "message",
            None,
        ),
    )


def _append_execution_observation(
    lines: Text,
    status: Any,
    *,
    include_message: bool = True,
) -> None:
    """Append live readiness and health without changing lifecycle semantics."""

    observation = getattr(
        status,
        "observation",
        None,
    )

    if observation is None:
        lines.append(
            "  observation=unavailable",
            style="dim",
        )
        return

    ready = getattr(
        observation,
        "ready",
        None,
    )
    ready_value = (
        "yes"
        if ready is True
        else "no"
        if ready is False
        else "unknown"
    )
    ready_style = {
        "yes": "green",
        "no": "yellow",
    }.get(
        ready_value,
        "dim",
    )

    health = getattr(
        observation,
        "health",
        None,
    )
    health_value = str(
        getattr(
            health,
            "value",
            health,
        )
        or "unknown"
    )
    health_style = {
        "healthy": "green",
        "degraded": "yellow",
        "unhealthy": "red",
    }.get(
        health_value,
        "dim",
    )

    lines.append("  ")
    lines.append(
        f"ready={ready_value}",
        style=ready_style,
    )
    lines.append(
        " · ",
        style="dim",
    )
    lines.append(
        f"health={health_value}",
        style=health_style,
    )

    message = getattr(
        observation,
        "message",
        None,
    )
    status_message = getattr(
        status,
        "message",
        None,
    )

    if (
        include_message
        and message
        and message != status_message
    ):
        lines.append("  ")
        lines.append(
            str(message),
            style=health_style,
        )


def system_execution_status_fingerprint(
    status: Any,
) -> tuple[Any, ...]:
    """Return the presentation-relevant identity of an execution snapshot.

    Dynamic backend details are intentionally excluded. The fingerprint changes
    only when information visible in the human execution tree changes.
    """

    scopes = tuple(
        (
            str(item.scope.id),
            str(item.status.backend),
            str(item.status.execution_id),
            _execution_state_value(
                item.status.state
            ),
            item.status.message,
            _execution_visible_details(
                item.status
            ),
            _execution_observation_fingerprint(
                item.status
            ),
        )
        for item in getattr(
            status,
            "scopes",
            (),
        )
    )

    systems = []

    for child in getattr(
        status,
        "systems",
        (),
    ):
        child_plan = getattr(
            getattr(
                child,
                "instance",
                None,
            ),
            "plan",
            None,
        )

        definition = (
            getattr(
                child_plan,
                "system",
                None,
            )
            if child_plan is not None
            else None
        )

        systems.append(
            (
                str(child.name),
                (
                    str(definition)
                    if definition is not None
                    else None
                ),
                system_execution_status_fingerprint(
                    child.status
                ),
            )
        )

    return (
        str(
            getattr(
                status,
                "execution_id",
                "",
            )
        ),
        _execution_state_value(
            status.state
        ),
        getattr(
            status,
            "message",
            None,
        ),
        _execution_visible_details(
            status
        ),
        _execution_observation_fingerprint(
            status
        ),
        scopes,
        tuple(systems),
    )

def render_system_execution_status(
    system_name: str,
    status: Any,
) -> Group:
    """Render one hierarchical System execution status snapshot.

    The renderer owns presentation only. Execution aggregation, lifecycle
    transitions and failure propagation remain responsibilities of the
    orchestration layer.
    """

    lines = Text()

    def append_system(
        name: str,
        item_status: Any,
        *,
        definition: str | None = None,
        prefix: str = "",
        connector: str = "",
    ) -> None:
        state = _execution_state_value(
            item_status.state
        )
        style = _execution_state_style(
            item_status.state
        )

        if connector:
            lines.append(
                prefix + connector,
                style="dim",
            )

        lines.append(
            f"{_execution_state_symbol(item_status.state)} ",
            style=style,
        )
        lines.append(
            name,
            style="bold",
        )

        if (
            definition is not None
            and definition != name
        ):
            lines.append(
                " → ",
                style="dim",
            )
            lines.append(
                definition,
                style="cyan",
            )

        lines.append("  ")
        lines.append(
            state.upper(),
            style=style,
        )

        execution_id = getattr(
            item_status,
            "execution_id",
            None,
        )
        if execution_id:
            lines.append(
                f"  {execution_id}",
                style="dim",
            )

        scopes = tuple(
            getattr(
                item_status,
                "scopes",
                (),
            )
        )
        systems = tuple(
            getattr(
                item_status,
                "systems",
                (),
            )
        )

        lines.append(
            f"  scopes={len(scopes)}"
            f" · systems={len(systems)}",
            style="dim",
        )
        _append_execution_observation(
            lines,
            item_status,
            include_message=not connector,
        )
        lines.append("\n")

        children: list[tuple[str, Any]] = [
            ("scope", scope)
            for scope in scopes
        ]
        children.extend(
            ("system", child)
            for child in systems
        )

        child_prefix = (
            prefix
            + (
                "   "
                if connector == "└─ "
                else "│  "
                if connector == "├─ "
                else ""
            )
        )

        for index, (
            kind,
            child,
        ) in enumerate(children):
            last = (
                index
                == len(children) - 1
            )
            branch = (
                "└─ "
                if last
                else "├─ "
            )

            if kind == "scope":
                scope_status = child.status
                scope_state = (
                    _execution_state_value(
                        scope_status.state
                    )
                )
                scope_style = (
                    _execution_state_style(
                        scope_status.state
                    )
                )

                lines.append(
                    child_prefix + branch,
                    style="dim",
                )
                lines.append(
                    f"{_execution_state_symbol(scope_status.state)} ",
                    style=scope_style,
                )
                lines.append(
                    child.scope.id,
                    style="bold",
                )
                lines.append("  ")
                lines.append(
                    scope_state.upper(),
                    style=scope_style,
                )
                lines.append(
                    f"  {scope_status.backend}:"
                    f"{scope_status.execution_id}",
                    style="dim",
                )
                _append_execution_observation(
                    lines,
                    scope_status,
                    include_message=False,
                )
                lines.append("\n")

                if scope_status.message:
                    message_prefix = (
                        child_prefix
                        + (
                            "   "
                            if last
                            else "│  "
                        )
                    )
                    lines.append(
                        message_prefix,
                        style="dim",
                    )
                    lines.append(
                        str(scope_status.message),
                        style="red",
                    )
                    lines.append("\n")

                scope_details = (
                    _execution_visible_details(
                        scope_status
                    )
                )

                for label, value in scope_details:
                    detail_prefix = (
                        child_prefix
                        + (
                            "   "
                            if last
                            else "│  "
                        )
                    )

                    lines.append(
                        detail_prefix,
                        style="dim",
                    )
                    lines.append(
                        f"{label}: ",
                        style="dim",
                    )
                    lines.append(
                        value,
                        style=(
                            "red"
                            if scope_state
                            == "failed"
                            else "dim"
                        ),
                    )
                    lines.append("\n")

                continue

            child_definition = getattr(
                getattr(
                    child,
                    "instance",
                    None,
                ),
                "plan",
                None,
            )
            definition_name = (
                getattr(
                    child_definition,
                    "system",
                    None,
                )
                if child_definition is not None
                else None
            )

            append_system(
                str(child.name),
                child.status,
                definition=(
                    str(definition_name)
                    if definition_name
                    else None
                ),
                prefix=child_prefix,
                connector=branch,
            )

        message = getattr(
            item_status,
            "message",
            None,
        )

        # Aggregated parent failures usually repeat lower-level context.
        # Present the reason and stable details at the lowest informative
        # System boundary instead of repeating them on every ancestor.
        if not _execution_has_failed_child(
            item_status
        ):
            detail_prefix = (
                prefix
                + (
                    "   "
                    if connector == "└─ "
                    else "│  "
                    if connector == "├─ "
                    else "   "
                )
            )

            if message:
                lines.append(
                    detail_prefix,
                    style="dim",
                )
                lines.append(
                    str(message),
                    style="red",
                )
                lines.append("\n")

            for label, value in (
                _execution_visible_details(
                    item_status
                )
            ):
                lines.append(
                    detail_prefix,
                    style="dim",
                )
                lines.append(
                    f"{label}: ",
                    style="dim",
                )
                lines.append(
                    value,
                    style=(
                        "red"
                        if state == "failed"
                        else "dim"
                    ),
                )
                lines.append("\n")

    append_system(
        system_name,
        status,
    )

    return Group(lines)

def render_system_plan(plan: Any) -> Group:
    """Render a nodrix.system execution plan as a readable architecture tree."""

    header = Text()
    header.append(f"PLAN {plan.system}", style="bold cyan")
    header.append(f"  sha256:{plan.system_sha256[:12]}", style="dim")
    header.append(f"\n{plan.schema_id}", style="dim")

    sections: list[RenderableType] = [header, _plan_summary(plan)]

    if plan.systems:
        sections.extend(
            [
                Text(""),
                _section("SYSTEMS"),
                _system_plan_tree(plan),
            ]
        )

    backend_names = _plan_backend_names(plan)
    if backend_names:
        lines = Text()
        for backend in backend_names:
            targets, resources, applications, graphs, nodes, inbound, outbound = _backend_counts(plan, backend)
            lines.append("● ", style="green" if backend == "local" else "cyan")
            lines.append(backend, style="bold")
            lines.append(
                f"  targets {targets} · resources {resources} · apps {applications} · "
                f"graphs {graphs} · nodes {nodes} · in {inbound} · out {outbound}\n",
                style="dim",
            )
        sections.extend([Text(""), _section("BACKENDS"), lines])

    if plan.targets:
        lines = Text()
        for target in plan.targets:
            lines.append("● ", style="green")
            lines.append(target.name, style="bold")
            lines.append(f"  {target.kind} · backend {target.backend}")
            lines.append(" · implicit" if target.implicit else " · declared", style="dim")
            lines.append("\n")
        sections.extend([Text(""), _section("TARGETS"), lines])

    if plan.resources:
        order = {name: index + 1 for index, name in enumerate(plan.resource_order)}
        lines = Text()
        for resource in sorted(plan.resources, key=lambda item: order.get(item.name, item.ordinal + 1)):
            lines.append(f"{order.get(resource.name, resource.ordinal + 1):>2} ", style="dim")
            lines.append("● ", style="green")
            lines.append(resource.name, style="bold")
            lines.append(f"  {resource.uses}")
            lines.append(f"\n     target {resource.target} · backend {resource.backend}", style="dim")
            if resource.bindings:
                lines.append(f" · bindings {_join_pairs(resource.bindings)}", style="dim")
            lines.append("\n")
        sections.extend([Text(""), _section("RESOURCES"), lines])

    if plan.applications:
        lines = Text()
        for application in plan.applications:
            lines.append("● ", style="green")
            lines.append(application.name, style="bold")
            lines.append(f"  {application.uses}")
            lines.append(f"\n  target {application.target} · backend {application.backend}", style="dim")
            if application.resources:
                lines.append(f" · resources {_join_pairs(application.resources)}", style="dim")
            lines.append("\n")
        sections.extend([Text(""), _section("APPLICATIONS"), lines])

    for graph in plan.graphs:
        lines = Text()
        order = {name: index + 1 for index, name in enumerate(graph.topological_order)}
        by_source: dict[str, list[Any]] = defaultdict(list)
        for connection in graph.connections:
            by_source[str(connection.source).split(".", 1)[0]].append(connection)
        sorted_nodes = sorted(graph.nodes, key=lambda item: order.get(item.name, item.ordinal + 1))
        if not sorted_nodes:
            lines.append("No nodes", style="dim")
        for node in sorted_nodes:
            lines.append(f"{order.get(node.name, node.ordinal + 1):>2} ", style="dim")
            lines.append("● ", style="green")
            lines.append(node.name, style="bold")
            lines.append(f"  {node.uses}")
            lines.append(f"  [{node.target} · {node.backend}]", style="dim")
            lines.append("\n")
            connections = by_source.get(node.name, [])
            for index, connection in enumerate(connections):
                lines.append("   └─ " if index == len(connections) - 1 else "   ├─ ", style="dim")
                lines.append(connection.source, style="cyan")
                lines.append(" → ", style="dim")
                lines.append(connection.target)
                if connection.type_id:
                    lines.append(f"  {connection.type_id}", style="dim")
                lines.append(f"  [{connection.placement_target} · {connection.backend}]", style="dim")
                lines.append("\n")
        sections.extend([Text(""), _section(f"GRAPH {graph.name}"), lines])

    if plan.links:
        lines = Text()
        for link in plan.links:
            lines.append("● ", style="cyan")
            lines.append(link.source, style="bold")
            lines.append(" → ", style="dim")
            lines.append(link.target, style="bold")
            lines.append(f"\n  {link.boundary}", style="yellow" if "cross" in str(link.boundary) else "dim")
            lines.append(f" · {link.transport_uses or '-'}", style="cyan")
            lines.append(f" · {link.source_backend} → {link.target_backend}\n", style="dim")
        sections.extend([Text(""), _section("SYSTEM LINKS"), lines])

    if plan.artifacts:
        lines = Text()
        for artifact in plan.artifacts:
            lines.append("● ", style="green")
            lines.append(artifact.name, style="bold")
            lines.append(f"  {artifact.kind}")
            if artifact.path:
                lines.append(f"\n  {artifact.path}", style="cyan")
            meta: list[str] = []
            if artifact.producer:
                meta.append(f"producer {artifact.producer}")
            if artifact.target:
                meta.append(f"target {artifact.target}")
            if artifact.backend:
                meta.append(f"backend {artifact.backend}")
            if meta:
                lines.append("\n  " + " · ".join(meta), style="dim")
            lines.append("\n")
        sections.extend([Text(""), _section("ARTIFACTS"), lines])

    if plan.diagnostics:
        lines = Text()
        for item in plan.diagnostics:
            style = "red" if str(item.level).lower() == "error" else "yellow"
            symbol = "✗" if style == "red" else "!"
            lines.append(f"{symbol} {str(item.level).upper()} {item.code}", style=style)
            if item.path:
                lines.append(f"  {item.path}", style="dim")
            lines.append(f"\n  {item.message}\n")
        sections.extend([Text(""), _section("DIAGNOSTICS"), lines])
    else:
        sections.extend([Text(""), Text("✓ plan ready", style="bold green")])

    return Group(*sections)


def render_validation(
    *,
    name: str,
    valid: bool,
    mode: str,
    diagnostics: Iterable[Any],
    noun: str = "SYSTEM",
) -> Group:
    """Generic semantic validation output used by System validation first."""

    status = "VALID" if valid else "INVALID"
    header = Text()
    header.append(f"{_state_symbol(status)} ", style=_state_style(status))
    header.append(status, style=_state_style(status))
    header.append(f"  {name}", style="bold")
    header.append(f"  {mode}", style="dim")

    items = list(diagnostics)
    lines = Text()
    for item in items:
        level = str(item.level).lower()
        style = "red" if level == "error" else "yellow"
        symbol = "✗" if level == "error" else "!"
        lines.append(f"{symbol} {str(item.level).upper()} {item.code}", style=style)
        if item.path:
            lines.append(f"  {item.path}", style="dim")
        lines.append(f"\n  {item.message}\n")
    if not items:
        lines.append(f"✓ {noun.lower()} contracts and references are valid", style="green")
    return Group(header, Text(""), _section("DIAGNOSTICS"), lines)
