from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text

from .ux import render_top


def _bytes(value: object) -> str:
    number = float(value or 0)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    index = 0
    while abs(number) >= 1024 and index < len(units) - 1:
        number /= 1024.0
        index += 1
    return f"{number:.1f} {units[index]}"


def _heading(value: str) -> Text:
    return Text(value, style="bold cyan")


def _applications(data: dict[str, object]) -> dict[str, dict[str, Any]]:
    raw = (
        data.get("applications")
        or data.get("managed_applications")
        or {}
    )
    return {
        str(name): dict(value)
        for name, value in dict(raw).items()
    }


def _compact(data: dict[str, object], *, operations: bool) -> Group:
    nodes = {
        str(name): dict(value)
        for name, value in dict(data.get("nodes", {})).items()
    }
    system = dict(data.get("system", {}))
    status = str(data.get("status", "running")).upper()
    duration = float(data.get("duration_seconds", 0.0) or 0.0)

    header = Text()
    header.append(str(data.get("pipeline", "-")), style="bold")
    header.append(f"  {status}", style="bold green")
    header.append(f"  {duration:,.1f}s", style="dim")

    machine = Text()
    machine.append(
        f"CPU {float(system.get('process_cpu_percent', system.get('cpu_percent', 0.0))):.1f}%"
    )
    machine.append(
        f"   RAM {_bytes(system.get('process_rss_bytes', system.get('rss_bytes', 0)))}"
    )
    if system.get("temperature_c") is not None:
        machine.append(
            f"   TEMP {float(system['temperature_c']):.1f}°C"
        )
    load = list(system.get("load_average") or [])
    if load:
        machine.append(
            "   LOAD " + " ".join(f"{float(item):.2f}" for item in load[:3])
        )

    application_table = Table(
        box=None,
        show_edge=False,
        pad_edge=False,
        header_style="bold",
        expand=False,
    )
    application_table.add_column("APPLICATION")
    application_table.add_column("STATE")
    application_table.add_column("CPU", justify="right")
    application_table.add_column("MEMORY", justify="right")
    application_table.add_column("PID", justify="right")
    if operations:
        application_table.add_column("PROCESSES", justify="right")
        application_table.add_column("THREADS", justify="right")
        application_table.add_column("RESTARTS", justify="right")

    applications = _applications(data)
    if applications:
        for name, raw in applications.items():
            resources = dict(raw.get("resources", raw))
            health = str(raw.get("health", raw.get("status", "unknown")))
            application_table.add_row(
                name,
                health,
                f"{float(resources.get('cpu_percent', raw.get('cpu_percent', 0.0))):.1f}%",
                _bytes(resources.get("rss_bytes", raw.get("rss_bytes", 0))),
                str(raw.get("pid", "-")),
                *(
                    [
                        str(raw.get("process_count", raw.get("proc", "-"))),
                        str(raw.get("thread_count", raw.get("threads", "-"))),
                        str(raw.get("restarts", 0)),
                    ]
                    if operations
                    else []
                ),
            )
    else:
        application_table.add_row("-", "none", "-", "-", "-")

    monitor_table = Table(
        box=None,
        show_edge=False,
        pad_edge=False,
        header_style="bold",
        expand=False,
    )
    monitor_table.add_column("MONITOR")
    monitor_table.add_column("STATE")
    monitor_table.add_column("LOOP RATE", justify="right")
    monitor_table.add_column("P95", justify="right")
    if operations:
        monitor_table.add_column("MESSAGES", justify="right")
        monitor_table.add_column("MEMORY", justify="right")

    monitors = {
        name: raw
        for name, raw in nodes.items()
        if name.endswith("_health")
        or "topic_monitor" in str(raw.get("uses", ""))
    }
    for name, raw in monitors.items():
        health = dict(raw.get("health", {}))
        resources = dict(raw.get("resources", {}))
        memory = (
            resources.get("rss_bytes")
            or resources.get("executor_rss_bytes")
            or 0
        )
        scope = " shared" if resources.get("scope") == "executor_shared" else ""
        monitor_table.add_row(
            name.removesuffix("_health"),
            str(health.get("status", "unknown")),
            f"{float(raw.get('rate_hz', 0.0)):.1f} Hz",
            f"{float(raw.get('p95_ms', 0.0)):.2f} ms",
            *(
                [
                    str(raw.get("messages", 0)),
                    _bytes(memory) + scope,
                ]
                if operations
                else []
            ),
        )
    if not monitors:
        monitor_table.add_row("-", "none", "-", "-")

    edges = Text()
    active = 0
    for raw in list(data.get("edges") or []):
        edge = dict(raw)
        depth = int(edge.get("depth", 0))
        stale = int(edge.get("stale_skips", 0))
        overflow = int(edge.get("overflow_drops", 0))
        if not (depth or stale or overflow):
            continue
        active += 1
        edges.append(
            f"{edge.get('source')} → {edge.get('target')} "
            f"queue={depth}/{int(edge.get('capacity', 0))}"
        )
        if stale:
            edges.append(f" stale={stale}", style="yellow")
        if overflow:
            edges.append(f" overflow={overflow}", style="red")
        edges.append("\n")
    if active == 0:
        edges.append("No queue pressure or overflow", style="dim")

    return Group(
        header,
        machine,
        Text(""),
        _heading("APPLICATIONS"),
        application_table,
        Text(""),
        _heading("MONITORS"),
        monitor_table,
        Text(""),
        _heading("EDGES"),
        edges,
    )


def render_top_view(
    data: dict[str, object],
    view: str = "compact",
):
    selected = view.strip().lower()
    if selected == "debug":
        return render_top(data)
    if selected == "operations":
        return _compact(data, operations=True)
    if selected == "compact":
        return _compact(data, operations=False)
    raise ValueError(
        f"Unknown top view {view!r}; choose compact, operations, or debug"
    )
