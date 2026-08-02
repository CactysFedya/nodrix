from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from rich.console import Group
from rich.panel import Panel
from rich.text import Text


def _format_bytes(value: object) -> str:
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


def _bar(value: float, maximum: float, width: int = 20) -> str:
    if maximum <= 0:
        ratio = 0.0
    else:
        ratio = min(max(float(value) / float(maximum), 0.0), 1.0)
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


def _topological_order(manifest: Any) -> list[str]:
    indegree = {str(name): 0 for name in manifest.nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in manifest.edges:
        source = edge.source.split(".", 1)[0]
        target = edge.target.split(".", 1)[0]
        if source == target:
            continue
        outgoing[source].append(target)
        indegree[target] = indegree.get(target, 0) + 1
    ready = deque(name for name in manifest.nodes if indegree.get(str(name), 0) == 0)
    ordered: list[str] = []
    while ready:
        node = str(ready.popleft())
        ordered.append(node)
        for target in outgoing.get(node, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    for name in manifest.nodes:
        if str(name) not in ordered:
            ordered.append(str(name))
    return ordered


def render_pipeline_graph(manifest: Any, *, details: bool = False) -> Group:
    header = Text()
    header.append(str(manifest.metadata.name), style="bold cyan")
    header.append(f"  {manifest.runtime.mode} · {manifest.runtime.engine}")
    if manifest.runtime.profile:
        header.append(f" · {manifest.runtime.profile}")
    header.append(
        f"\n{len(manifest.nodes)} nodes · {len(manifest.edges)} edges · "
        f"{len(manifest.streams.exports)} streams"
    )

    outgoing: dict[str, list[Any]] = defaultdict(list)
    exports: dict[str, list[Any]] = defaultdict(list)
    for edge in manifest.edges:
        outgoing[edge.source.split(".", 1)[0]].append(edge)
    for export in manifest.streams.exports:
        exports[export.source.split(".", 1)[0]].append(export)

    graph = Text()
    order = _topological_order(manifest)
    for node_index, node_name in enumerate(order):
        config = manifest.nodes[node_name]
        graph.append("● ", style="bold green")
        graph.append(node_name, style="bold")
        graph.append("  ")
        graph.append(config.uses, style="dim")
        info: list[str] = []
        if config.synchronization.policy != "exact_sequence" or config.synchronization.trigger_port:
            sync = config.synchronization.policy
            if config.synchronization.trigger_port:
                sync += f" trigger={config.synchronization.trigger_port}"
            info.append(sync)
        if config.execution.device != "auto":
            info.append(f"device={config.execution.device}")
        if info:
            graph.append("  " + " · ".join(info), style="yellow")
        graph.append("\n")

        node_edges = outgoing.get(node_name, [])
        node_exports = exports.get(node_name, [])
        rows: list[tuple[str, str]] = []
        for edge in node_edges:
            source_port = edge.source.split(".", 1)[1]
            queue = f"{edge.queue.policy}:{edge.queue.capacity}"
            memory = "" if edge.memory.domain == "auto" else f" · {edge.memory.domain}"
            rows.append((source_port, f"{queue}{memory} ──▶ {edge.target}"))
        for export in node_exports:
            source_port = export.source.split(".", 1)[1]
            rows.append((source_port, f"publish ──▶ {export.name} [{export.access.mode}]"))
        for row_index, (port, target) in enumerate(rows):
            last = row_index == len(rows) - 1
            graph.append("  └─ " if last else "  ├─ ", style="dim")
            graph.append(port, style="cyan")
            graph.append(" ─ ", style="dim")
            graph.append(target)
            graph.append("\n")
        if details and config.parameters:
            for key, value in config.parameters.items():
                graph.append(f"    {key}: {value!r}\n", style="dim")
        if node_index != len(order) - 1:
            graph.append("  │\n", style="dim")

    footer = Text()
    footer.append("Direct: ", style="dim")
    footer.append(
        f"nodrix://HOST:{manifest.streams.listen_port or 7420}/…",
        style="cyan",
    )
    footer.append("   Discovery: ", style="dim")
    footer.append("plyctl stream list", style="cyan")
    return Group(Panel(header, title="Plyctl graph"), graph, footer)


def render_node_details(manifest: Any, node_name: str) -> Group:
    if node_name not in manifest.nodes:
        available = ", ".join(str(name) for name in manifest.nodes)
        raise KeyError(f"Unknown node {node_name!r}; available nodes: {available}")
    node = manifest.nodes[node_name]
    summary = Text()
    summary.append(node_name, style="bold cyan")
    summary.append(f"\nNode type: {node.uses}")
    summary.append(f"\nIsolation: {node.execution.isolation}")
    summary.append(f" · Device: {node.execution.device}")
    summary.append(f"\nSynchronization: {node.synchronization.policy}")
    if node.synchronization.trigger_port:
        summary.append(f" · trigger={node.synchronization.trigger_port}")

    parameters = Text()
    if node.parameters:
        for key, value in node.parameters.items():
            parameters.append(f"{key:<28}", style="cyan")
            parameters.append(f" {value!r}\n")
    else:
        parameters.append("No parameters\n", style="dim")

    connections = Text()
    found = False
    for edge in manifest.edges:
        if edge.target.startswith(node_name + "."):
            found = True
            connections.append("IN   ", style="green")
            connections.append(
                f"{edge.source} ──[{edge.queue.policy}:{edge.queue.capacity}]──▶ {edge.target}\n"
            )
        if edge.source.startswith(node_name + "."):
            found = True
            connections.append("OUT  ", style="yellow")
            connections.append(
                f"{edge.source} ──[{edge.queue.policy}:{edge.queue.capacity}]──▶ {edge.target}\n"
            )
    if not found:
        connections.append("No graph connections\n", style="dim")
    return Group(
        Panel(summary, title="Node instance"),
        Panel(parameters, title="Parameters"),
        Panel(connections, title="Connections"),
    )


def render_startup_summary(manifest: Any, version: str) -> Group:
    text = Text()
    text.append(f"Plyctl {version}", style="bold cyan")
    text.append(f" · {manifest.metadata.name}", style="bold")
    text.append(
        f"\n{manifest.runtime.mode} · {manifest.runtime.engine} · "
        f"{manifest.runtime.profile or 'no profile'}"
    )
    text.append(
        f"\nStarting {len(manifest.nodes)} nodes, {len(manifest.edges)} edges, "
        f"{len(manifest.streams.exports)} streams…"
    )
    return Group(Panel(text, title="Starting pipeline"))


def _runtime_info_text(info: dict[str, Any]) -> str:
    selected: list[str] = []
    backend = info.get("backend")
    if backend:
        selected.append(str(backend))
    if info.get("hardware") is True:
        selected.append("hardware")
    elif info.get("hardware") is False and backend:
        selected.append("software")
    if info.get("threads") is not None:
        selected.append(f"{info['threads']} threads")
    if info.get("frame_clocked"):
        selected.append("frame-clocked")
    return " · ".join(selected)


def render_runtime_event(event: dict[str, Any], indexes: dict[str, int], total: int) -> Text:
    kind = str(event.get("kind", "event"))
    text = Text()
    if kind == "pipeline_starting":
        text.append("Runtime STARTING", style="bold cyan")
        return text
    if kind == "node_ready":
        name = str(event.get("node", "?"))
        index = indexes.get(name, 0)
        text.append(f"[{index}/{total}] ", style="dim")
        text.append(f"{name:<14}", style="bold")
        text.append(f" {event.get('uses', ''):<28}")
        text.append(" READY", style="bold green")
        info = _runtime_info_text(dict(event.get("runtime_info") or {}))
        if info:
            text.append(f" · {info}", style="cyan")
        return text
    if kind == "stream_server_ready":
        text.append("Streams READY", style="bold green")
        text.append(f" · port {event.get('port')}")
        for name in event.get("streams") or []:
            text.append(f"\n  plyctl-viewer {name}", style="cyan")
        return text
    if kind == "pipeline_running":
        text.append("RUNNING", style="bold green")
        text.append(" · press Ctrl+C to stop")
        return text
    if kind == "node_failed":
        text.append("FAILED ", style="bold red")
        text.append(f"{event.get('node')}: {event.get('error')}")
        return text
    if kind == "node_stopped":
        text.append("STOPPED ", style="dim")
        text.append(str(event.get("node")))
        return text
    if kind == "pipeline_stopped":
        text.append(f"Pipeline {event.get('status', 'stopped')}", style="yellow")
        return text
    text.append(kind, style="dim")
    return text


def _node_line(name: str, raw: dict[str, Any], bottleneck_p95: float) -> Text:
    resources = dict(raw.get("resources", {}))
    health = dict(raw.get("health", {}))
    info = dict(raw.get("runtime_info", {}))
    busy = min(100.0, max(0.0, float(resources.get("cpu_percent", 0.0))))
    rate = float(raw.get("rate_hz", 0.0))
    p95 = float(raw.get("p95_ms", raw.get("processing", {}).get("p95_ms", 0.0)))
    text = Text()
    text.append(f"{name:<14}", style="bold")
    text.append(f" {rate:6.1f} Hz")
    text.append(f" {p95:8.2f} ms")
    text.append(f"  {_bar(busy, 100.0, 16)} ")
    text.append(f"{busy:5.1f}%")
    backend = info.get("backend")
    if backend:
        style = "green" if info.get("hardware") else "cyan"
        text.append(f"  {backend}", style=style)
    stale = int(resources.get("stale_skips", 0))
    overflow = int(resources.get("overflow_drops", 0))
    sync = int(resources.get("sync_misses", 0))
    if stale:
        text.append(f"  stale={stale}", style="yellow")
    if overflow:
        text.append(f"  overflow={overflow}", style="red")
    if sync:
        text.append(f"  sync={sync}", style="magenta")
    status = str(health.get("status", "unknown"))
    if status != "healthy":
        text.append(f"  {status}", style="bold red")
    if p95 > 0 and bottleneck_p95 > 0 and p95 >= bottleneck_p95 * 0.95:
        text.append("  BOTTLENECK", style="bold red")
    return text


def render_top(data: dict[str, object]) -> Group:
    raw_nodes = {str(name): dict(raw) for name, raw in dict(data.get("nodes", {})).items()}
    system = dict(data.get("system", {}))
    process: dict[str, Any] = {}
    for raw in raw_nodes.values():
        resources = dict(raw.get("resources", {}))
        if resources.get("scope") == "executor_shared":
            process = resources
            break

    cpu_count = max(int(system.get("cpu_count", 1) or 1), 1)
    process_cpu = float(process.get("executor_cpu_percent", 0.0))
    rss = float(process.get("executor_rss_bytes", 0.0))
    total_memory = float(system.get("memory_total_bytes", 0.0))
    duration = float(data.get("duration_seconds", 0.0) or 0.0)

    header = Text()
    header.append("Plyctl top", style="bold cyan")
    header.append(f" · {data.get('pipeline', '-')}", style="bold")
    header.append(f" · {str(data.get('status', 'running')).upper()}", style="green")
    header.append(f" · {duration:,.1f}s")

    machine = Text()
    machine.append(f"CPU  {process_cpu:6.1f}/{cpu_count * 100}% ")
    machine.append(_bar(process_cpu, cpu_count * 100.0, 24), style="green")
    machine.append(f"   RAM {_format_bytes(rss)}")
    if total_memory > 0:
        machine.append(f"/{_format_bytes(total_memory)} ")
        machine.append(_bar(rss, total_memory, 16), style="blue")
    temperature = system.get("temperature_c")
    if temperature is not None:
        machine.append(f"   TEMP {float(temperature):.1f}°C")
    load = list(system.get("load_average") or [])
    if load:
        machine.append("   LOAD " + " ".join(f"{float(item):.2f}" for item in load[:3]))

    node_rates = {name: float(raw.get("rate_hz", 0.0)) for name, raw in raw_nodes.items()}
    rates = Text()
    source_names = [name for name in raw_nodes if "source" in name.lower()]
    detector_names = [name for name in raw_nodes if "detector" in name.lower()]
    tracker_names = [name for name in raw_nodes if "tracker" in name.lower()]
    output_names = [name for name in raw_nodes if "encoder" in name.lower() or "output" in name.lower()]
    for label, names in (
        ("IN", source_names),
        ("DET", detector_names),
        ("TRACK", tracker_names),
        ("OUT", output_names),
    ):
        if names:
            rates.append(f"{label} {max(node_rates[name] for name in names):.1f} FPS   ", style="bold")

    p95_values = [float(raw.get("p95_ms", 0.0)) for raw in raw_nodes.values()]
    bottleneck_p95 = max(p95_values, default=0.0)
    node_lines: list[Text] = []
    for name, raw in raw_nodes.items():
        node_lines.append(_node_line(name, raw, bottleneck_p95))

    edge_lines = Text()
    edge_count = 0
    for edge_raw in list(data.get("edges") or []):
        edge = dict(edge_raw)
        stale = int(edge.get("stale_skips", 0))
        overflow = int(edge.get("overflow_drops", 0))
        depth = int(edge.get("depth", 0))
        capacity = int(edge.get("capacity", 1))
        if stale == 0 and overflow == 0 and depth == 0:
            continue
        edge_count += 1
        edge_lines.append(f"{edge.get('source')} → {edge.get('target')}")
        edge_lines.append(f"  queue {depth}/{capacity} {edge.get('policy')}", style="dim")
        if stale:
            edge_lines.append(f"  stale-skipped {stale}", style="yellow")
        if overflow:
            edge_lines.append(f"  overflow {overflow}", style="red")
        edge_lines.append("\n")
    if edge_count == 0:
        edge_lines.append("No active queue pressure or overflow", style="dim")

    return Group(
        Panel(header, title="Runtime"),
        machine,
        rates,
        Text("\n"),
        *node_lines,
        Text("\n"),
        Panel(edge_lines, title="Edges"),
    )
