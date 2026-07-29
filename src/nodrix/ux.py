from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
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


def render_pipeline_graph(manifest: Any) -> Group:
    header = Text()
    header.append(str(manifest.metadata.name), style="bold")
    header.append(f"  profile={manifest.runtime.profile or '-'}")
    header.append(f"  mode={manifest.runtime.mode}")
    header.append(f"  engine={manifest.runtime.engine}")

    nodes = Table("Instance", "Node type", "Parameters", title="Nodes")
    for name, config in manifest.nodes.items():
        parameters = ", ".join(
            f"{key}={value!r}" for key, value in config.parameters.items()
        )
        nodes.add_row(str(name), str(config.uses), parameters or "-")

    edges = Table("Connection", "Queue", "Memory", title="Graph")
    for edge in manifest.edges:
        edges.add_row(
            f"{edge.source}  ──▶  {edge.target}",
            f"{edge.queue.policy}:{edge.queue.capacity}",
            f"{edge.memory.domain}"
            + ("" if edge.memory.allow_copy else " · no-copy"),
        )

    streams = Table("Published stream", "Source", "Access", title="Streams")
    exports = list(manifest.streams.exports)
    if exports:
        for export in exports:
            streams.add_row(
                str(export.name),
                str(export.source),
                str(export.access.mode),
            )
    else:
        streams.add_row("-", "-", "-")

    return Group(Panel(header, title="Pipeline"), nodes, edges, streams)


def render_node_details(manifest: Any, node_name: str) -> Group:
    if node_name not in manifest.nodes:
        available = ", ".join(str(name) for name in manifest.nodes)
        raise KeyError(
            f"Unknown node {node_name!r}; available nodes: {available}"
        )

    node = manifest.nodes[node_name]
    header = Panel(
        f"[bold]{node_name}[/bold]\n"
        f"Node type: {node.uses}\n"
        f"Isolation: {node.execution.isolation}\n"
        f"Device: {node.execution.device}\n"
        f"Synchronization: {node.synchronization.policy}",
        title="Node instance",
    )

    parameters = Table("Parameter", "Resolved value", title="Parameters")
    if node.parameters:
        for key, value in node.parameters.items():
            parameters.add_row(str(key), repr(value))
    else:
        parameters.add_row("-", "-")

    ports = Table("Direction", "Port", "Peer", "Queue", title="Connections")
    for edge in manifest.edges:
        if edge.source.startswith(node_name + "."):
            ports.add_row(
                "out",
                edge.source.split(".", 1)[1],
                edge.target,
                f"{edge.queue.policy}:{edge.queue.capacity}",
            )
        if edge.target.startswith(node_name + "."):
            ports.add_row(
                "in",
                edge.target.split(".", 1)[1],
                edge.source,
                f"{edge.queue.policy}:{edge.queue.capacity}",
            )

    return Group(header, parameters, ports)


def render_startup_summary(manifest: Any) -> Group:
    header = Panel(
        f"[bold]{manifest.metadata.name}[/bold]\n"
        f"Profile: {manifest.runtime.profile or '-'} · "
        f"Mode: {manifest.runtime.mode} · "
        f"Engine: {manifest.runtime.engine}",
        title="Starting Nodrix pipeline",
    )

    nodes = Table("#", "Instance", "Node type", "State")
    for index, (name, config) in enumerate(manifest.nodes.items(), start=1):
        nodes.add_row(str(index), str(name), str(config.uses), "configured")

    streams = Table("Stream", "Source", "Access")
    exports = list(manifest.streams.exports)
    if exports:
        for export in exports:
            streams.add_row(
                str(export.name),
                str(export.source),
                str(export.access.mode),
            )
    else:
        streams.add_row("-", "-", "-")

    return Group(header, nodes, streams)


def render_top(data: dict[str, object]) -> Group:
    raw_nodes = dict(data.get("nodes", {}))

    process: dict[str, Any] = {}
    for raw in raw_nodes.values():
        resources = dict(dict(raw).get("resources", {}))
        if resources.get("scope") == "executor_shared":
            process = {
                "pid": resources.get("pid"),
                "cpu": resources.get("executor_cpu_percent", 0.0),
                "rss": resources.get("executor_rss_bytes", 0),
                "vms": resources.get("executor_vms_bytes", 0),
                "threads": resources.get("threads"),
            }
            break

    process_table = Table(
        "PID",
        "Process CPU",
        "RSS",
        "VMS",
        "Threads",
        title="Executor process",
    )
    process_table.add_row(
        str(process.get("pid") or "-"),
        f"{float(process.get('cpu', 0.0)):.1f}%",
        _format_bytes(process.get("rss")),
        _format_bytes(process.get("vms")),
        str(process.get("threads") or "-"),
    )

    nodes = Table(
        "Node",
        "Busy",
        "Rate",
        "P95",
        "Queue memory",
        "Drops",
        "Health",
        title="Nodes",
    )
    for name, raw in raw_nodes.items():
        node = dict(raw)
        resources = dict(node.get("resources", {}))
        health = dict(node.get("health", {}))
        busy = min(
            100.0,
            max(0.0, float(resources.get("cpu_percent", 0.0))),
        )
        nodes.add_row(
            str(name),
            f"{busy:.1f}%",
            f"{float(node.get('rate_hz', 0.0)):.1f} Hz",
            f"{float(node.get('p95_ms', 0.0)):.2f} ms",
            _format_bytes(resources.get("estimated_queue_bytes", 0)),
            str(resources.get("input_drops", 0)),
            str(health.get("status", "unknown")),
        )

    system = dict(data.get("system", {}))
    status: list[str] = []
    if system.get("memory_available_bytes") is not None:
        status.append(
            f"free {_format_bytes(system.get('memory_available_bytes'))}"
        )
    if system.get("temperature_c") is not None:
        status.append(f"temp {float(system['temperature_c']):.1f}°C")
    if system.get("load_average"):
        status.append(
            "load "
            + "/".join(
                f"{float(item):.2f}"
                for item in list(system["load_average"])[:3]
            )
        )

    footer = Text(
        " · ".join(status) if status else "system telemetry unavailable"
    )
    return Group(process_table, nodes, footer)
