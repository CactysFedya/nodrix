from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
import ctypes
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.live import Live
import yaml

from .errors import NodrixError
from .cv_types import TYPE_REGISTRY
from .manifest import canonical_config_path, load_block, load_manifest, load_manifest_details
from .hybrid_runtime import HybridPipelineRuntime
from .native_runtime import NATIVE_BUILTINS, NativePipelineRuntime, NativeToolchain
from .registry import BUILTINS, load_node_class
from . import __version__
from .discovery import discover_streams, resolve_stream
from .project_templates import TEMPLATES, create_project
from .streams import StreamClient
from .type_codegen import generate_type
from .media import MediaError, media_doctor, probe_media, run_ffmpeg_relay, select_encoder
from .recording import NdrxReader, play_recording, record_streams
from .lockfile import write_lock, verify_lock
from .packages import build_package, install_package, list_packages, package_info, remove_package
from .runs import list_runs, load_run, compare_runs, resolve_run
from .validation import validate_production
from .metrics import MetricsServer, prometheus_text
from .profiles import profile_names

app = typer.Typer(
    name="nodrix",
    help="High-performance runtime for typed local and distributed streaming graphs.",
    no_args_is_help=False,
    invoke_without_command=True,
)
node_app = typer.Typer(help="Inspect available node types.")
stream_app = typer.Typer(help="Discover, inspect, and subscribe to named streams.")
native_app = typer.Typer(help="Build and inspect the high-performance C++20 engine.")
type_app = typer.Typer(help="Inspect registered message contracts.")
media_app = typer.Typer(help="Probe, record, and relay media through FFmpeg.")
recording_app = typer.Typer(help="Inspect universal .ndrx recordings.")
data_app = typer.Typer(help="Inspect shared-memory and process data-plane capabilities.")
device_app = typer.Typer(help="Inspect DLPack, DMA-BUF, V4L2, CUDA and native device-I/O capabilities.")
package_app = typer.Typer(help="Build and manage local Nodrix packages.")
runs_app = typer.Typer(help="Inspect reproducible run artifacts.")
config_app = typer.Typer(help="Inspect resolved profiles and configuration values.")
block_app = typer.Typer(help="List and inspect reusable YAML node blocks.")
app.add_typer(node_app, name="node")
app.add_typer(stream_app, name="stream")
app.add_typer(native_app, name="native")
app.add_typer(type_app, name="type")
app.add_typer(media_app, name="media")
app.add_typer(recording_app, name="recording")
app.add_typer(data_app, name="data-plane")
app.add_typer(device_app, name="device")
app.add_typer(package_app, name="package")
app.add_typer(runs_app, name="runs")
app.add_typer(config_app, name="config")
app.add_typer(block_app, name="block")
console = Console()


def _format_bytes(value: object) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    index = 0
    while abs(number) >= 1024 and index < len(units) - 1:
        number /= 1024.0
        index += 1
    return f"{number:.1f} {units[index]}"


def _config_value(data: object, dotted: str) -> object:
    current = data
    for part in dotted.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(dotted)
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            raise KeyError(dotted)
    return current


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show the Nodrix version", is_eager=True)] = False,
) -> None:
    if version:
        console.print(f"Nodrix {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


def _runtime(
    path: Path,
    run_root: Path | None = None,
    *,
    profile: str | None = None,
    overrides: list[str] | None = None,
    block_overrides: list[str] | None = None,
):
    manifest = load_manifest(
        path,
        profile=profile,
        overrides=overrides,
        block_overrides=block_overrides,
    )
    native_only = all(
        config.uses.startswith("native.") or config.uses.startswith("native:")
        for config in manifest.nodes.values()
    )
    use_native = manifest.runtime.engine == "native" or (
        manifest.runtime.engine == "auto" and native_only
    )
    if use_native:
        if manifest.streams.exports:
            raise NodrixError(
                "Named LAN stream exports require engine: unified; "
                "the fully native executor does not yet expose network streams."
            )
        runtime = NativePipelineRuntime(manifest, path, run_root=run_root)
    else:
        runtime = HybridPipelineRuntime(manifest, path, run_root=run_root)
    runtime.build()
    return runtime


@app.command()
def init(
    directory: Annotated[Path, typer.Argument(help="Directory for a new Nodrix project")] = Path("nodrix-project"),
    template: Annotated[str | None, typer.Option("--template", "-t", help="Optional: core, vision, media, network, data-plane, device, benchmark, or package")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite generated files")] = False,
) -> None:
    """Create an empty project skeleton, or a runnable project from a template."""
    selected = template.lower() if template else None
    if selected is not None and selected not in TEMPLATES:
        raise typer.BadParameter(f"Unknown template {selected!r}; choose: {', '.join(sorted(TEMPLATES))}")
    try:
        created = create_project(directory, selected, force=force)
    except (FileExistsError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    label = f"{selected} template" if selected else "empty skeleton"
    console.print(f"[green]Created[/green] {directory.resolve()} ({label}, {len(created)} files)")
    if selected == "package":
        console.print("Build: [bold]cd %s && nodrix package build .[/bold]" % directory)
    elif selected:
        console.print("Run: [bold]cd %s && nodrix validate && nodrix run[/bold]" % directory)
    else:
        console.print("Add nodes to pipeline.yaml, or create a runnable example with: "
                      f"[bold]nodrix init {directory} --template vision --force[/bold]")


@app.command()
def validate(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    strict: Annotated[bool, typer.Option("--strict", help="Treat production safety warnings as errors where applicable")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    profile: Annotated[str | None, typer.Option("--profile", help="Override the manifest performance profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set", help="Override a resolved value: path=value")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block", help="Replace a reusable block: name=path.yaml")] = None,
) -> None:
    """Validate manifest, plugins, memory paths, security, and graph safety."""
    try:
        runtime = _runtime(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        desc = runtime.describe()
        issues = validate_production(runtime.manifest, desc, strict=strict)
    except Exception as exc:
        if json_output:
            console.print_json(json.dumps({"valid": False, "error": str(exc), "issues": []}))
        else:
            console.print(f"[red]Invalid:[/red] {exc}")
        raise typer.Exit(1)
    failed = any(item.severity == "error" for item in issues)
    if json_output:
        console.print_json(json.dumps({
            "valid": not failed,
            "pipeline": desc["name"],
            "nodes": len(desc["nodes"]),
            "edges": len(desc["edges"]),
            "issues": [item.as_dict() for item in issues],
        }))
    else:
        console.print(
            f"[{'red' if failed else 'green'}]{'Invalid' if failed else 'Valid'}[/{'red' if failed else 'green'}] "
            f"{desc['name']}: {len(desc['nodes'])} nodes, {len(desc['edges'])} edges"
        )
        if issues:
            table = Table("Severity", "Code", "Location", "Message")
            for item in issues:
                table.add_row(item.severity, item.code, item.location or "-", item.message)
            console.print(table)
    if failed:
        raise typer.Exit(1)


def _live_table(snapshot: dict[str, object]) -> Table:
    table = Table(
        "Node", "Isolation", "CPU", "Memory", "Messages", "Rate Hz", "P95 ms", "E2E P95",
        "Input copies", "Output copies", "Restarts",
    )
    for name, raw in dict(snapshot.get("nodes", {})).items():
        stats = dict(raw)
        transport = dict(stats.get("transport", {}))
        input_copies = int(transport.get("input_payload_copies", 0))
        output_copies = int(transport.get("output_payload_copies", 0))
        resources = dict(stats.get("resources", {}))
        memory_value = resources.get("rss_bytes") or resources.get("shared_buffer_bytes") or resources.get("executor_rss_bytes")
        table.add_row(
            str(name), str(transport.get("isolation", "in_process")),
            f"{float(resources.get('cpu_percent', 0.0)):.1f}%", _format_bytes(memory_value),
            str(stats.get("messages", 0)), f"{float(stats.get('rate_hz', 0.0)):.1f}",
            f"{float(stats.get('p95_ms', 0.0)):.3f}",
            f"{float(dict(stats.get('end_to_end', {})).get('p95_ms', 0.0)):.3f}",
            str(input_copies), str(output_copies), str(transport.get("restarts", 0)),
        )
    return table


async def _inspect_live(runtime, interval: float) -> dict[str, object]:
    started = __import__("time").perf_counter()
    task = asyncio.create_task(runtime.run())
    with Live(_live_table(runtime.snapshot(0.0)), console=console, refresh_per_second=max(2, int(1 / interval))) as live:
        while not task.done():
            elapsed = max(__import__("time").perf_counter() - started, 1e-9)
            live.update(_live_table(runtime.snapshot(elapsed)))
            await asyncio.sleep(interval)
        report = await task
        live.update(_live_table(runtime.snapshot(float(report.get("duration_seconds", 0.0)))))
    return report


@app.command()
def inspect(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    live: Annotated[bool, typer.Option("--live", help="Run the graph and display live node/data-plane telemetry")] = False,
    memory: Annotated[bool, typer.Option("--memory", help="Show the static memory-domain and copy plan")] = False,
    resolved: Annotated[bool, typer.Option("--resolved", help="Print the canonical manifest after profiles and overrides")] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write resolved YAML to a file")] = None,
    profile: Annotated[str | None, typer.Option("--profile", help="Override the manifest performance profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set", help="Override a resolved value: path=value")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block", help="Replace a reusable block: name=path.yaml")] = None,
    interval: Annotated[float, typer.Option("--interval", min=0.1, max=10.0)] = 0.5,
) -> None:
    """Show a static graph, or execute it with live telemetry."""
    try:
        details = load_manifest_details(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        if resolved:
            rendered = yaml.safe_dump(details.manifest.model_dump(by_alias=True, exclude_none=True), sort_keys=False)
            if output is not None:
                output.write_text(rendered, encoding="utf-8")
                console.print(f"[green]Written[/green] {output.resolve()}")
            else:
                console.print(rendered, markup=False, end="")
            return
        runtime = _runtime(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        if live:
            report = asyncio.run(_inspect_live(runtime, interval))
            console.print(f"[green]Completed[/green] {report['pipeline']} in {report['duration_seconds']:.3f}s")
            return
        desc = runtime.describe()
    except Exception as exc:
        console.print(f"[red]Cannot inspect:[/red] {exc}")
        raise typer.Exit(1)
    profile_text = f" profile={desc.get('profile')}" if desc.get("profile") else ""
    console.print(f"[bold]{desc['name']}[/bold]  mode={desc['mode']} engine={desc.get('engine', 'unified')}{profile_text}")
    if memory:
        table = Table("From", "To", "Type", "Memory", "Copies", "Transfers", "Adapter", "Ready")
        for edge in desc["edges"]:
            plan = dict(edge.get("memory") or {})
            table.add_row(
                edge["from"], edge["to"], edge["type"],
                str(plan.get("selected_memory", "dynamic")),
                str(plan.get("planned_copies", 0)),
                ", ".join(plan.get("transfers", [])) or "-",
                str(plan.get("adapter") or "-"),
                "yes" if plan.get("runtime_supported", True) else "no",
            )
        console.print(table)
        return
    table = Table("From", "To", "Type", "Queue")
    for edge in desc["edges"]:
        q = edge["queue"]
        table.add_row(edge["from"], edge["to"], edge["type"], f"{q['policy']}:{q['capacity']}")
    console.print(table)


@app.command()
def run(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    run_root: Annotated[Path | None, typer.Option("--run-root", help="Directory for run artifacts")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print the complete run report as JSON")] = False,
    locked: Annotated[bool, typer.Option("--locked", help="Require exact nodrix.lock checksums and runtime version")] = False,
    metrics_listen: Annotated[str | None, typer.Option("--metrics-listen", help="Prometheus endpoint, for example 127.0.0.1:9464")] = None,
    profile: Annotated[str | None, typer.Option("--profile", help="Override the manifest performance profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set", help="Override a resolved value: path=value")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block", help="Replace a reusable block: name=path.yaml")] = None,
) -> None:
    """Execute a pipeline with reproducibility and optional Prometheus metrics."""
    if locked and (profile is not None or set_values or block_values):
        console.print("[red]--locked cannot be combined with --profile, --set, or --block.[/red] Create or verify the lock for the exact manifest you intend to run.")
        raise typer.Exit(2)
    if locked:
        try:
            result = verify_lock(pipeline)
        except Exception as exc:
            console.print(f"[red]Lock verification failed:[/red] {exc}")
            raise typer.Exit(1)
        if not result["ok"]:
            for issue in result["issues"]:
                console.print(f"[red]- {issue}[/red]")
            raise typer.Exit(1)
    metrics_server = None
    try:
        runtime = _runtime(
            pipeline,
            run_root=run_root,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        if metrics_listen:
            if not hasattr(runtime, "snapshot"):
                raise NodrixError("--metrics-listen currently requires engine: unified")
            host, port_text = metrics_listen.rsplit(":", 1)
            metrics_server = MetricsServer(lambda: runtime.snapshot(), host, int(port_text))
            metrics_server.start()
            host, port = metrics_server.address
            console.print(f"Metrics: http://{host}:{port}/metrics")
        report = runtime.run_sync() if isinstance(runtime, HybridPipelineRuntime) else asyncio.run(runtime.run())
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted; Nodrix requested graceful shutdown.[/yellow]")
        raise typer.Exit(130)
    except (NodrixError, Exception) as exc:
        console.print(f"[red]Run failed:[/red] {exc}")
        raise typer.Exit(1)
    finally:
        if metrics_server is not None:
            metrics_server.close()
    if json_output:
        console.print_json(json.dumps(report))
    else:
        console.print(
            f"[green]Completed[/green] {report['pipeline']} in {report['duration_seconds']:.3f}s\n"
            f"Artifacts: {report['run_dir']}"
        )
        table = Table("Node", "State", "Health", "CPU", "Memory", "Messages", "Rate Hz", "P95 ms", "E2E P95 ms", "Errors")
        for name, stats in report["nodes"].items():
            health = dict(stats.get("health", {}))
            table.add_row(
                name,
                str(health.get("state", "-")),
                str(health.get("status", "-")),
                f"{float(dict(stats.get('resources', {})).get('cpu_percent', 0.0)):.1f}%",
                _format_bytes(dict(stats.get('resources', {})).get('rss_bytes') or dict(stats.get('resources', {})).get('shared_buffer_bytes') or dict(stats.get('resources', {})).get('executor_rss_bytes')),
                str(stats["messages"]),
                f"{stats.get('rate_hz', 0.0):.1f}",
                f"{stats.get('p95_ms', stats['max_ms']):.3f}",
                f"{stats.get('end_to_end', {}).get('p95_ms', 0.0):.3f}",
                str(stats["errors"]),
            )
        console.print(table)


@app.command()
def record(
    streams: Annotated[list[str], typer.Argument(help="One or more named streams or nodrix:// URIs")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Output .ndrx file")] = Path("recording.ndrx"),
    duration: Annotated[float, typer.Option("--duration", min=0.0, help="Stop after N seconds; 0 disables")] = 0.0,
    count: Annotated[int, typer.Option("--count", min=0, help="Stop after N total messages; 0 disables")] = 0,
) -> None:
    """Record any typed Nodrix streams into one indexed .ndrx file."""
    if duration <= 0 and count <= 0:
        console.print("[yellow]Recording until interrupted; use --duration or --count for an automatic stop.[/yellow]")
    try:
        info = record_streams(streams, output, duration=duration, count=count)
    except (OSError, EOFError, LookupError, ValueError) as exc:
        console.print(f"[red]Recording failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Recorded[/green] {info['messages']} messages to {info['path']}")


@app.command()
def play(
    recording: Annotated[Path, typer.Argument(exists=True, readable=True)],
    speed: Annotated[float, typer.Option("--speed", min=0.01)] = 1.0,
    as_fast_as_possible: Annotated[bool, typer.Option("--as-fast-as-possible")] = False,
    prefix: Annotated[str, typer.Option("--prefix", help="Prefix exported stream names")] = "",
    loop: Annotated[bool, typer.Option("--loop")] = False,
    startup_delay: Annotated[float, typer.Option("--startup-delay", min=0.0, help="Discovery window before playback starts")] = 1.0,
) -> None:
    """Replay an .ndrx recording as discoverable Nodrix streams."""
    try:
        report = play_recording(
            recording, speed=speed, as_fast_as_possible=as_fast_as_possible,
            stream_prefix=prefix, loop=loop, startup_delay=startup_delay,
        )
    except (OSError, ValueError) as exc:
        console.print(f"[red]Playback failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Played[/green] {report['messages']} messages")


@recording_app.command("info")
def recording_info(recording: Annotated[Path, typer.Argument(exists=True, readable=True)]) -> None:
    """Show streams, types, counts, and size of an .ndrx file."""
    try:
        with NdrxReader(recording) as reader:
            info = reader.info()
    except (OSError, ValueError) as exc:
        console.print(f"[red]Cannot read recording:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[bold]{info['path']}[/bold]  messages={info['messages']} size={info['size_bytes']} bytes")
    table = Table("Stream", "Type", "Messages")
    for name, spec in info.get("streams", {}).items():
        table.add_row(name or "(unnamed)", str(spec.get("type", "core.any")), str(spec.get("messages", 0)))
    console.print(table)


@data_app.command("doctor")
def data_plane_doctor() -> None:
    """Verify POSIX shared memory and report the active IPC capabilities."""
    from .shared_memory import SharedBufferPool
    try:
        with SharedBufferPool(4096, 2) as pool:
            value = pool.acquire(16)
            value.memoryview()[:4] = b"NDRX"
            ok = bytes(value.memoryview()[:4]) == b"NDRX"
            stats = pool.stats()
            value.release()
    except Exception as exc:
        console.print(f"[red]Shared memory unavailable:[/red] {exc}")
        raise typer.Exit(1)
    table = Table("Capability", "Status")
    table.add_row("POSIX shared memory", "yes" if ok else "no")
    table.add_row("Process isolation", "yes")
    table.add_row("Descriptor-only transfer", "yes for SharedBufferPool payloads")
    table.add_row("Pool segment", str(stats.get("name")))
    console.print(table)


@device_app.command("doctor")
def device_memory_doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON")] = False,
) -> None:
    """Report native device-memory, DLPack, V4L2 and libav capabilities."""
    from .device import device_doctor

    info = device_doctor()
    if json_output:
        console.print_json(json.dumps(info))
        return
    table = Table("Capability", "Status")
    labels = {
        "native_extension": "Native device extension",
        "v4l2_headers": "V4L2 native API",
        "dma_heap": "Linux DMA heap",
        "dri": "DRM render devices",
        "libavformat": "Native libavformat",
        "libavcodec": "Native libavcodec",
        "cuda_runtime": "CUDA runtime",
        "opencl_runtime": "OpenCL runtime",
        "vulkan_runtime": "Vulkan runtime",
        "dlpack_numpy": "NumPy DLPack",
        "dlpack_torch": "PyTorch DLPack",
        "dlpack_cupy": "CuPy DLPack",
        "dma_buf_descriptor": "DMA-BUF descriptors",
        "cuda_ipc_descriptor": "CUDA IPC descriptors",
    }
    for key, label in labels.items():
        value = info.get(key, False)
        table.add_row(label, "yes" if value is True else "no" if value is False else str(value))
    console.print(table)


@device_app.command("v4l2-probe")
def device_v4l2_probe(
    device: Annotated[str, typer.Argument(help="Linux V4L2 path")] = "/dev/video0",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Query a V4L2 device through the native extension without starting capture."""
    from .device import probe_v4l2

    try:
        info = probe_v4l2(device)
    except Exception as exc:
        console.print(f"[red]V4L2 probe failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(info))
        return
    table = Table("Field", "Value")
    for key, value in info.items():
        table.add_row(str(key), str(value))
    console.print(table)


@app.command()
def benchmark(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    repeat: Annotated[int, typer.Option("--repeat", min=1)] = 3,
    warmup: Annotated[int, typer.Option("--warmup", min=0)] = 1,
    output: Annotated[Path | None, typer.Option("--output", help="Write benchmark summary JSON")] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block")] = None,
) -> None:
    """Run the same pipeline repeatedly and aggregate runtime/node latency."""
    for _ in range(warmup):
        asyncio.run(_runtime(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        ).run())
    reports = [asyncio.run(_runtime(
        pipeline,
        profile=profile,
        overrides=set_values,
        block_overrides=block_values,
    ).run()) for _ in range(repeat)]
    durations = [r["duration_seconds"] for r in reports]
    node_names = reports[0]["nodes"].keys()
    nodes = {}
    for name in node_names:
        means = [r["nodes"][name]["mean_ms"] for r in reports]
        p95 = [r["nodes"][name].get("p95_ms", r["nodes"][name]["max_ms"]) for r in reports]
        e2e_p95 = [r["nodes"][name].get("end_to_end", {}).get("p95_ms", 0.0) for r in reports]
        nodes[name] = {
            "mean_ms": statistics.fmean(means),
            "min_mean_ms": min(means),
            "max_mean_ms": max(means),
            "p95_ms": statistics.fmean(p95),
            "end_to_end_p95_ms": statistics.fmean(e2e_p95),
        }
    summary = {
        "pipeline": reports[0]["pipeline"],
        "repeat": repeat,
        "warmup": warmup,
        "duration_seconds": {
            "mean": statistics.fmean(durations),
            "min": min(durations),
            "max": max(durations),
        },
        "nodes": nodes,
        "runs": [r["run_dir"] for r in reports],
    }
    table = Table("Metric", "Mean", "Min", "Max")
    d = summary["duration_seconds"]
    table.add_row("Pipeline seconds", f"{d['mean']:.4f}", f"{d['min']:.4f}", f"{d['max']:.4f}")
    for name, stats in nodes.items():
        table.add_row(
            f"{name} mean ms",
            f"{stats['mean_ms']:.4f}",
            f"{stats['min_mean_ms']:.4f}",
            f"{stats['max_mean_ms']:.4f}",
        )
        table.add_row(
            f"{name} P95 / E2E P95 ms",
            f"{stats['p95_ms']:.4f}",
            f"{stats['end_to_end_p95_ms']:.4f}",
            "-",
        )
    console.print(table)
    if output:
        output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        console.print(f"Saved: {output}")


@app.command("view")
def view(
    source: Annotated[str, typer.Argument(help="Stream name, nodrix:// URI, RTSP/HTTP URL, camera, or video path")],
    fps: Annotated[float, typer.Option("--fps", min=0.0)] = 0.0,
    overlay: Annotated[bool, typer.Option("--overlay/--no-overlay")] = True,
    fullscreen: Annotated[bool, typer.Option("--fullscreen")] = False,
    scale: Annotated[float, typer.Option("--scale", min=0.05, max=8.0)] = 1.0,
    decoder: Annotated[str, typer.Option("--decoder", help="auto, opencv, or ffmpeg")] = "auto",
    rtsp_transport: Annotated[str, typer.Option("--rtsp-transport", help="tcp or udp")] = "tcp",
    headless: Annotated[bool, typer.Option("--headless")] = False,
    max_frames: Annotated[int, typer.Option("--max-frames", min=0)] = 0,
) -> None:
    """Open the low-latency Nodrix Viewer."""
    from .viewer import ViewerError, run_viewer

    try:
        report = run_viewer(
            source,
            max_fps=fps,
            overlay=overlay,
            fullscreen=fullscreen,
            scale=scale,
            decoder=decoder,
            rtsp_transport=rtsp_transport,
            headless=headless,
            max_frames=max_frames,
        )
    except (ViewerError, OSError, LookupError, ValueError) as exc:
        console.print(f"[red]Viewer failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"Displayed {report['displayed']} frames at {report['display_fps']:.1f} FPS; "
        f"overwritten={report['overwritten']}"
    )


@media_app.command("doctor")
def media_doctor_command(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check FFmpeg/FFprobe and available software/hardware encoders."""
    try:
        report = media_doctor()
    except MediaError as exc:
        console.print(f"[red]Media doctor failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(report))
        return
    console.print(report["ffmpeg"])
    table = Table("Encoder", "Available")
    for name, available in report["encoders"].items():
        table.add_row(name, "yes" if available else "no")
    console.print(table)


@media_app.command("select-encoder")
def media_select_encoder_command(
    codec: Annotated[str, typer.Argument(help="h264 or h265")] = "h264",
    requested: Annotated[str, typer.Option("--encoder", help="auto or an explicit FFmpeg encoder")] = "auto",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Probe FFmpeg encoders and select the fastest working backend."""
    try:
        result = select_encoder(codec, requested)
    except Exception as exc:
        console.print(f"[red]Encoder selection failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(result))
        return
    console.print(f"Selected: [bold]{result.get('selected')}[/bold]")
    console.print(f"Reason: {result.get('reason')}")
    if result.get("fallback"):
        console.print(f"Fallback: {result['fallback']}")
    attempts = list(result.get("attempts") or [])
    if attempts:
        table = Table("Encoder", "Probe", "Detail")
        for item in attempts:
            table.add_row(str(item.get("encoder")), "pass" if item.get("ok") else "fail", str(item.get("reason")))
        console.print(table)


@media_app.command("probe")
def media_probe_command(
    source: Annotated[str, typer.Argument(help="File, RTSP/HTTP/SRT URL, or FFmpeg input")],
    input_format: Annotated[str | None, typer.Option("--format", help="Optional FFmpeg input format")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect media streams with ffprobe."""
    try:
        report = probe_media(source, input_format=input_format)
    except MediaError as exc:
        console.print(f"[red]Probe failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(report))
        return
    video = report.get("video") or {}
    audio = report.get("audio") or {}
    table = Table("Kind", "Codec", "Details")
    if video:
        table.add_row("video", str(video.get("codec")), f"{video.get('width')}x{video.get('height')} @ {video.get('fps', 0):.3f} FPS")
    if audio:
        table.add_row("audio", str(audio.get("codec")), f"{audio.get('sample_rate')} Hz, {audio.get('channels')} ch")
    console.print(table)


@media_app.command("record")
def media_record_command(
    source: Annotated[str, typer.Argument(help="Input URL or file")],
    output: Annotated[str, typer.Argument(help="Output media file")],
    copy: Annotated[bool, typer.Option("--copy/--transcode", help="Copy encoded packets when possible")] = True,
    codec: Annotated[str, typer.Option("--codec", help="h264 or h265 when transcoding")] = "h264",
    encoder: Annotated[str | None, typer.Option("--encoder", help="Explicit FFmpeg encoder name")] = None,
    duration: Annotated[float, typer.Option("--duration", min=0.0)] = 0.0,
    rtsp_transport: Annotated[str, typer.Option("--rtsp-transport")] = "tcp",
) -> None:
    """Record a media source with stream copy or low-latency transcoding."""
    code = run_ffmpeg_relay(source, output, copy=copy, codec=codec, encoder=encoder, duration=duration, rtsp_transport=rtsp_transport)
    if code != 0:
        raise typer.Exit(code)
    console.print(f"[green]Recorded[/green] {output}")


@media_app.command("relay")
def media_relay_command(
    source: Annotated[str, typer.Argument(help="Input URL or file")],
    output: Annotated[str, typer.Argument(help="RTSP/SRT/UDP URL or file")],
    copy: Annotated[bool, typer.Option("--copy/--transcode")] = True,
    codec: Annotated[str, typer.Option("--codec")] = "h264",
    encoder: Annotated[str | None, typer.Option("--encoder")] = None,
    rtsp_transport: Annotated[str, typer.Option("--rtsp-transport")] = "tcp",
) -> None:
    """Relay media directly through FFmpeg without entering the Python frame path."""
    code = run_ffmpeg_relay(source, output, copy=copy, codec=codec, encoder=encoder, rtsp_transport=rtsp_transport)
    raise typer.Exit(code)


@node_app.command("list")
def node_list() -> None:
    """List built-in nodes."""
    from . import builtin_nodes  # noqa: F401
    table = Table("Node id", "Inputs", "Outputs")
    for node_id, cls in sorted(BUILTINS.items()):
        table.add_row(node_id, json.dumps(cls.input_types), json.dumps(cls.output_types))
    console.print(table)


@node_app.command("create")
def node_create(
    name: Annotated[str, typer.Argument(help="Node name, for example custom-detector")],
    directory: Annotated[Path, typer.Option("--directory", "-d")] = Path("nodes"),
    inputs: Annotated[list[str] | None, typer.Option("--input", help="Port as name:type; repeatable")] = None,
    outputs: Annotated[list[str] | None, typer.Option("--output", help="Port as name:type; repeatable")] = None,
    language: Annotated[str, typer.Option("--language", "-l", help="python or cpp")] = "python",
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Generate a Python-first high-performance node or a native C++ node."""
    def parse_ports(values: list[str] | None, default: dict[str, str]) -> dict[str, str]:
        if not values:
            return default
        result: dict[str, str] = {}
        for value in values:
            if ":" not in value:
                raise typer.BadParameter(f"Port must use name:type syntax: {value!r}")
            port, type_name = value.split(":", 1)
            if not port or not type_name:
                raise typer.BadParameter(f"Invalid port: {value!r}")
            result[port] = type_name
        return result

    language = language.lower()
    if language not in {"cpp", "python"}:
        raise typer.BadParameter("--language must be cpp or python")
    input_ports = parse_ports(inputs, {"input": "core.any"})
    output_ports = parse_ports(outputs, {"output": "core.any"})
    class_name = "".join(
        part.capitalize() for part in name.replace("_", "-").split("-") if part
    ) + "Node"
    directory.mkdir(parents=True, exist_ok=True)

    if language == "python":
        path = directory / f"{name.replace('-', '_')}.py"
        if path.exists() and not force:
            raise typer.BadParameter(f"File exists: {path}; use --force")
        template_lines = [
            "from nodrix import Message, Node",
            "",
            "",
            f"class {class_name}(Node):",
            f"    input_types = {input_ports!r}",
            f"    output_types = {output_ports!r}",
            "",
            "    def open(self, context):",
            "        super().open(context)",
            "        # Load the model once here. ONNX/OpenCV/PyTorch native calls may release the GIL.",
            "",
            "    def process(self, inputs):",
            "        source = next(iter(inputs.values()))",
            "        output_port = next(iter(self.output_types))",
            "        output_type = self.output_types[output_port]",
            "        return {output_port: Message(type=output_type, payload=source.payload,",
            "            sequence=source.sequence, timestamp_ns=source.timestamp_ns,",
            "            trace_id=source.trace_id, metadata=dict(source.metadata),",
            "            created_ns=source.created_ns)}",
            "",
        ]
        path.write_text("\n".join(template_lines), encoding="utf-8")
        console.print(f"[green]Created[/green] {path}")
        console.print(f"Use in YAML: [bold]{path.as_posix()}:{class_name}[/bold]")
        return

    project = directory / name.replace("_", "-")
    if project.exists() and any(project.iterdir()) and not force:
        raise typer.BadParameter(f"Directory is not empty: {project}; use --force")
    project.mkdir(parents=True, exist_ok=True)
    cpp_inputs = ", ".join(f'{{"{port}", "{type_name}"}}' for port, type_name in input_ports.items())
    cpp_outputs = ", ".join(f'{{"{port}", "{type_name}"}}' for port, type_name in output_ports.items())
    node_type = name.replace("_", ".").replace("-", ".")
    source_lines = [
        "#include <span>",
        "#include <string_view>",
        "#include <vector>",
        "",
        '#include "nodrix/plugin.hpp"',
        "",
        f"class {class_name} final : public nodrix::Node {{",
        " public:",
        "  const std::vector<nodrix::PortSpec>& input_ports() const noexcept override { return inputs_; }",
        "  const std::vector<nodrix::PortSpec>& output_ports() const noexcept override { return outputs_; }",
        "",
        "  void process(std::span<const nodrix::Message> inputs, nodrix::Emitter& emitter) override {",
        "    // Replace with the detector/filter/tracker implementation.",
        "    // Message payloads are intrusive zero-copy Buffer handles.",
        "    if (!outputs_.empty() && !inputs.empty()) emitter.emit(0, inputs.front());",
        "  }",
        "",
        " private:",
        f"  const std::vector<nodrix::PortSpec> inputs_{{{cpp_inputs}}};",
        f"  const std::vector<nodrix::PortSpec> outputs_{{{cpp_outputs}}};",
        "};",
        "",
        "NODRIX_DECLARE_PLUGIN(",
        f'  if (std::string_view(node_type ? node_type : "") == "{node_type}") {{',
        f"    return new {class_name}();",
        "  }",
        "  return nullptr;",
        ")",
        "",
    ]
    target = name.replace("-", "_")
    cmake_lines = [
        "cmake_minimum_required(VERSION 3.20)",
        f"project({target} LANGUAGES CXX)",
        "set(CMAKE_CXX_STANDARD 20)",
        "set(CMAKE_CXX_STANDARD_REQUIRED ON)",
        "find_package(Python3 REQUIRED COMPONENTS Interpreter)",
        "execute_process(",
        '  COMMAND "${Python3_EXECUTABLE}" -c "from pathlib import Path; import nodrix; print(Path(nodrix.__file__).with_name(\'native\'))"',
        "  OUTPUT_VARIABLE NODRIX_NATIVE_DIR OUTPUT_STRIP_TRAILING_WHITESPACE",
        ")",
        f"add_library({target} SHARED node.cpp)",
        f'target_include_directories({target} PRIVATE "${{NODRIX_NATIVE_DIR}}/include")',
        f"target_compile_options({target} PRIVATE $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-O3;-DNDEBUG;-fvisibility=hidden>)",
        f'set_target_properties({target} PROPERTIES OUTPUT_NAME "{target}")',
        "",
    ]
    (project / "node.cpp").write_text("\n".join(source_lines), encoding="utf-8")
    (project / "CMakeLists.txt").write_text("\n".join(cmake_lines), encoding="utf-8")
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    prefix = "" if sys.platform == "win32" else "lib"
    manifest = {
        "uses": f"native:./build/{prefix}{target}{suffix}#{node_type}",
        "inputs": input_ports,
        "outputs": output_ports,
        "parameters": {},
    }
    (project / "manifest-snippet.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    console.print(f"[green]Created C++ node[/green] {project}")
    console.print(
        f"Build: cmake -S {project} -B {project / 'build'} -DCMAKE_BUILD_TYPE=Release "
        f"&& cmake --build {project / 'build'}"
    )


@node_app.command("info")
def node_info(reference: str, base_dir: Path = Path.cwd()) -> None:
    """Show ports for a built-in or custom node."""
    try:
        cls = load_node_class(reference, base_dir=base_dir)
    except NodrixError as exc:
        console.print(f"[red]Cannot load node:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[bold]{reference}[/bold]\nClass: {cls.__module__}.{cls.__name__}")
    console.print("Inputs:", cls.input_types)
    console.print("Outputs:", cls.output_types)


@block_app.command("list")
def block_list_command(
    project: Annotated[Path, typer.Option("--project", "-p", help="Project directory containing blocks/")] = Path.cwd(),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List reusable block YAML files under blocks/."""
    project = project.expanduser().resolve()
    root = project / "blocks"
    if not root.is_dir():
        if json_output:
            console.print_json("[]")
        else:
            console.print(f"[yellow]No blocks directory:[/yellow] {root}")
        return
    rows: list[dict[str, object]] = []
    for path in sorted((*root.rglob("*.yaml"), *root.rglob("*.yml"))):
        try:
            config = load_block(path)
            rows.append({
                "name": path.stem,
                "category": str(path.parent.relative_to(root)) if path.parent != root else "-",
                "path": str(path.relative_to(project)),
                "uses": config.uses,
                "parameters": config.parameters,
            })
        except Exception as exc:
            rows.append({
                "name": path.stem,
                "category": str(path.parent.relative_to(root)) if path.parent != root else "-",
                "path": str(path.relative_to(project)),
                "uses": f"ERROR: {exc}",
                "parameters": {},
            })
    if json_output:
        console.print_json(json.dumps(rows, default=str))
        return
    table = Table("Category", "Block", "Implementation", "Path")
    for row in rows:
        table.add_row(str(row["category"]), str(row["name"]), str(row["uses"]), str(row["path"]))
    console.print(table)
    if not rows:
        console.print("[yellow]No YAML blocks found.[/yellow]")


@block_app.command("inspect")
def block_inspect_command(
    block: Annotated[Path, typer.Argument(exists=True, readable=True, help="Block YAML file")],
    project: Annotated[Path, typer.Option("--project", "-p", help="Base directory for custom node paths")] = Path.cwd(),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show one block implementation, ports, and configured parameters."""
    try:
        config = load_block(block)
        inputs = dict(config.inputs)
        outputs = dict(config.outputs)
        class_name = None
        if not inputs or not outputs:
            cls = load_node_class(config.uses, base_dir=project.expanduser().resolve())
            class_name = f"{cls.__module__}.{cls.__name__}"
            inputs = inputs or dict(cls.input_types)
            outputs = outputs or dict(cls.output_types)
    except Exception as exc:
        console.print(f"[red]Cannot inspect block:[/red] {exc}")
        raise typer.Exit(1)
    payload = {
        "path": str(block.expanduser().resolve()),
        "uses": config.uses,
        "class": class_name,
        "inputs": inputs,
        "outputs": outputs,
        "parameters": config.parameters,
        "execution": config.execution.model_dump(exclude_none=True),
        "health": config.health.model_dump(exclude_none=True),
    }
    if json_output:
        console.print_json(json.dumps(payload, default=str))
        return
    console.print(f"[bold]{block.stem}[/bold]")
    console.print(f"Implementation: {config.uses}")
    if class_name:
        console.print(f"Class: {class_name}")
    ports = Table("Direction", "Port", "Type")
    for name, message_type in inputs.items():
        ports.add_row("input", str(name), str(message_type))
    for name, message_type in outputs.items():
        ports.add_row("output", str(name), str(message_type))
    console.print(ports)
    params = Table("Parameter", "Value")
    for name, value in sorted(config.parameters.items()):
        params.add_row(str(name), yaml.safe_dump(value, sort_keys=False).strip())
    console.print(params)


@stream_app.command("list")
def stream_list(
    pipeline: Annotated[Path | None, typer.Option("--pipeline", "-p", help="Show exports declared by a local manifest")] = None,
    timeout: Annotated[float, typer.Option("--timeout", min=0.05, help="LAN discovery window in seconds")] = 1.2,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List named streams visible on the LAN; no agent or IP address is required."""
    if pipeline is not None:
        try:
            desc = _runtime(pipeline).describe()
        except Exception as exc:
            console.print(f"[red]Cannot inspect streams:[/red] {exc}")
            raise typer.Exit(1)
        streams = desc.get("streams", [])
        if json_output:
            console.print_json(json.dumps(streams))
            return
        table = Table("Name", "Source", "Type", "Queue")
        for item in streams:
            table.add_row(item["name"], item["source"], item["type"], f"{item['policy']}:{item['capacity']}")
        console.print(table)
        return

    streams = discover_streams(timeout=timeout)
    if json_output:
        console.print_json(json.dumps([{
            "name": item.name,
            "type": item.type,
            "host": item.host,
            "pipeline": item.pipeline,
            "endpoint": item.endpoint,
        } for item in streams]))
        return
    table = Table("Stream", "Type", "Host", "Pipeline", "Endpoint")
    for item in streams:
        table.add_row(item.name, item.type, item.host, item.pipeline, item.endpoint)
    console.print(table)
    if not streams:
        console.print("[yellow]No Nodrix streams discovered during the selected window.[/yellow]")


@stream_app.command("info")
def stream_info(
    name: Annotated[str, typer.Argument(help="Named stream, for example /camera/front")],
    timeout: Annotated[float, typer.Option("--timeout", min=0.05)] = 1.2,
) -> None:
    """Resolve one named LAN stream and display its endpoint and type."""
    try:
        item = resolve_stream(name, timeout=timeout)
    except LookupError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    table = Table("Field", "Value")
    for key, value in (
        ("name", item.name), ("type", item.type), ("host", item.host),
        ("pipeline", item.pipeline), ("endpoint", item.endpoint), ("codec", item.codec),
    ):
        table.add_row(key, str(value))
    console.print(table)


@stream_app.command("echo")
def stream_echo(
    target: Annotated[str, typer.Argument(help="Stream name or nodrix:// URI")],
    count: Annotated[int, typer.Option("--count", "-n", min=1)] = 1,
    discovery_timeout: Annotated[float, typer.Option("--discovery-timeout", min=0.05)] = 3.0,
    token: Annotated[str | None, typer.Option("--token", help="Stream access token")] = None,
) -> None:
    """Subscribe directly to a stream and print message headers/payload summaries."""
    client = StreamClient(target, discovery_timeout=discovery_timeout, token=token)
    try:
        client.connect()
        for _ in range(count):
            message = client.receive()
            payload = message.payload
            summary = {
                "stream": message.stream_id,
                "type": message.type,
                "sequence": message.sequence,
                "timestamp_ns": message.timestamp_ns,
                "payload_class": type(payload).__name__,
            }
            if hasattr(payload, "buffer") and hasattr(payload.buffer, "nbytes"):
                summary["payload_bytes"] = payload.buffer.nbytes
            elif hasattr(payload, "nbytes"):
                summary["payload_bytes"] = int(payload.nbytes)
            else:
                summary["payload"] = payload
            console.print_json(json.dumps(summary, default=str))
    except (OSError, EOFError, LookupError, ValueError) as exc:
        console.print(f"[red]Stream failed:[/red] {exc}")
        raise typer.Exit(1)
    finally:
        client.close()


@stream_app.command("view")
def stream_view(
    target: Annotated[str, typer.Argument(help="Stream name or nodrix:// URI")],
    fps: Annotated[float, typer.Option("--fps", min=0.0)] = 0.0,
    overlay: Annotated[bool, typer.Option("--overlay/--no-overlay")] = True,
    fullscreen: Annotated[bool, typer.Option("--fullscreen")] = False,
    scale: Annotated[float, typer.Option("--scale", min=0.05, max=8.0)] = 1.0,
) -> None:
    """Open a named frame stream in Nodrix Viewer."""
    from .viewer import ViewerError, run_viewer

    try:
        report = run_viewer(
            target,
            max_fps=fps,
            overlay=overlay,
            fullscreen=fullscreen,
            scale=scale,
        )
    except (ViewerError, OSError, LookupError, ValueError) as exc:
        console.print(f"[red]Viewer failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"Displayed {report['displayed']} frames at {report['display_fps']:.1f} FPS; "
        f"overwritten={report['overwritten']}"
    )


@type_app.command("list")
def type_list() -> None:
    """List standard and user-registered message types."""
    table = Table("Message type", "Version", "Compatible", "Payload", "Description")
    for name in TYPE_REGISTRY.names():
        definition = TYPE_REGISTRY.definition(name)
        payload = "any"
        if definition and definition.payload_type is not None:
            payload_type = definition.payload_type
            payload = (
                " | ".join(item.__name__ for item in payload_type)
                if isinstance(payload_type, tuple)
                else payload_type.__name__
            )
        table.add_row(
            name,
            str(definition.version if definition else 1),
            ",".join(str(item) for item in definition.compatible_versions) if definition else "1",
            payload,
            definition.description if definition else "",
        )
    console.print(table)


@type_app.command("info")
def type_info(name: str) -> None:
    """Show a registered message contract."""
    definition = TYPE_REGISTRY.definition(name)
    if definition is None:
        console.print(f"[yellow]Unregistered user type:[/yellow] {name}")
        return
    console.print(f"[bold]{name}[/bold]")
    console.print(f"Version: {definition.version}; compatible: {definition.compatible_versions}")
    console.print(f"Payload: {definition.payload_type or 'any'}")
    if definition.description:
        console.print(definition.description)


@type_app.command("build")
def type_build(
    schema: Annotated[Path, typer.Argument(exists=True, readable=True, help="YAML type schema")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Generated package directory")] = Path("generated_types"),
) -> None:
    """Generate matching Python/C++ fixed-layout types and a binary wire codec."""
    try:
        generated = generate_type(schema, output)
    except (OSError, ValueError, TypeError) as exc:
        console.print(f"[red]Type generation failed:[/red] {exc}")
        raise typer.Exit(1)
    table = Table("Artifact", "Path")
    for kind, path in generated.items():
        table.add_row(kind, str(path))
    console.print(table)


@native_app.command("build")
def native_build(
    directory: Annotated[Path, typer.Option("--directory", "-d", help="Project directory for build cache")] = Path.cwd(),
    clean: Annotated[bool, typer.Option("--clean", help="Remove the previous native build")] = False,
    portable: Annotated[bool, typer.Option("--portable", help="Do not tune binaries for the current CPU")] = False,
) -> None:
    """Build the C++20 runner with Release, LTO, and native CPU tuning."""
    toolchain = NativeToolchain(directory)
    try:
        runner = toolchain.build(clean=clean, portable=portable)
    except (subprocess.CalledProcessError, NodrixError, OSError) as exc:
        console.print(f"[red]Native build failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Built[/green] {runner}")


@native_app.command("doctor")
def native_doctor(
    directory: Annotated[Path, typer.Option("--directory", "-d")] = Path.cwd(),
) -> None:
    """Check the local compiler and native runner."""
    data = NativeToolchain(directory).doctor()
    table = Table("Component", "Value")
    for key, value in data.items():
        table.add_row(key, "not found" if value is None else str(value))
    console.print(table)


@native_app.command("nodes")
def native_nodes() -> None:
    """List built-in C++ nodes."""
    table = Table("Node", "Inputs", "Outputs")
    for name, spec in sorted(NATIVE_BUILTINS.items()):
        table.add_row(name, json.dumps(spec.inputs), json.dumps(spec.outputs))
    console.print(table)


@config_app.command("profiles")
def config_profiles_command() -> None:
    """List built-in performance profiles."""
    table = Table("Profile", "Purpose")
    descriptions = {
        "realtime-low-latency": "Latest-frame queues and zero-latency media defaults",
        "realtime-balanced": "Realtime operation with small bounded queues",
        "lossless-recording": "Blocking queues and graceful lossless draining",
        "maximum-throughput": "Large queues for offline throughput",
        "debug": "Always validate types and collect dense telemetry",
    }
    for name in profile_names():
        table.add_row(name, descriptions.get(name, ""))
    console.print(table)


@config_app.command("show")
def config_show_command(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Show the fully resolved canonical manifest."""
    try:
        details = load_manifest_details(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
    except Exception as exc:
        console.print(f"[red]Cannot resolve configuration:[/red] {exc}")
        raise typer.Exit(1)
    rendered = yaml.safe_dump(details.manifest.model_dump(by_alias=True, exclude_none=True), sort_keys=False)
    if output is not None:
        output.write_text(rendered, encoding="utf-8")
        console.print(f"[green]Written[/green] {output.resolve()}")
    else:
        console.print(rendered, markup=False, end="")


@config_app.command("explain")
def config_explain_command(
    path: Annotated[str, typer.Argument(help="Resolved dotted path")],
    pipeline: Annotated[Path, typer.Option("--pipeline", "-p", exists=True, readable=True)] = Path("pipeline.yaml"),
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block")] = None,
) -> None:
    """Explain the final value and where it came from."""
    try:
        details = load_manifest_details(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        canonical_path = canonical_config_path(path, details.manifest.nodes.keys())
        value = _config_value(details.canonical, canonical_path)
    except Exception as exc:
        console.print(f"[red]Cannot explain {path!r}:[/red] {exc}")
        raise typer.Exit(1)
    source = details.sources.get(canonical_path, "built-in schema default")
    console.print(f"Path: [bold]{canonical_path}[/bold]")
    if isinstance(value, (dict, list)):
        rendered_value = yaml.safe_dump(value, sort_keys=False).strip()
    else:
        rendered_value = json.dumps(value, ensure_ascii=False)
    console.print(f"Value: {rendered_value}")
    console.print(f"Source: {source}")


@app.command("lock")
def lock_command(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    check: Annotated[bool, typer.Option("--check", help="Verify the existing lock instead of rewriting it")] = False,
) -> None:
    """Create or verify the reproducible nodrix.lock file."""
    try:
        if check:
            result = verify_lock(pipeline, output)
            if not result["ok"]:
                for issue in result["issues"]:
                    console.print(f"[red]- {issue}[/red]")
                raise typer.Exit(1)
            console.print(f"[green]Lock verified[/green] {result['path']}")
            return
        target = write_lock(pipeline, output)
    except (OSError, ValueError, LookupError) as exc:
        console.print(f"[red]Lock failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Created[/green] {target}")


def _latest_run_id(project: Path) -> str:
    items = list_runs(project)
    if not items:
        raise LookupError("No Nodrix runs found")
    return str(items[0]["id"])


@app.command("status")
def status_command(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the latest live status snapshot or final run summary."""
    try:
        selected = run_id or _latest_run_id(project)
        directory = resolve_run(selected, project)
        status_path = directory / "status.json"
        data = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else load_run(selected, project)
    except Exception as exc:
        console.print(f"[red]Status unavailable:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(data))
        return
    console.print(f"[bold]{data.get('pipeline', selected)}[/bold]")
    table = Table("Node", "State", "Health", "CPU", "Memory", "Ready", "Messages", "Rate Hz", "Last error")
    for name, raw in dict(data.get("nodes", {})).items():
        stats = dict(raw)
        health = dict(stats.get("health", {}))
        resources = dict(stats.get("resources", {}))
        memory_value = resources.get("rss_bytes") or resources.get("shared_buffer_bytes") or resources.get("executor_rss_bytes")
        table.add_row(
            name, str(health.get("state", "-")), str(health.get("status", "-")),
            f"{float(resources.get('cpu_percent', 0.0)):.1f}%", _format_bytes(memory_value),
            "yes" if health.get("ready") else "no", str(stats.get("messages", 0)),
            f"{float(stats.get('rate_hz', 0.0)):.1f}", str(health.get("last_error") or "-"),
        )
    console.print(table)


@app.command("health")
def health_command(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    watch: Annotated[bool, typer.Option("--watch")] = False,
    interval: Annotated[float, typer.Option("--interval", min=0.1)] = 1.0,
) -> None:
    """Show node readiness and health; optionally watch a running pipeline."""
    selected = run_id or _latest_run_id(project)
    while True:
        directory = resolve_run(selected, project)
        status_path = directory / "status.json"
        data = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else load_run(selected, project)
        table = Table("Node", "Alive", "Ready", "Health", "Queue pressure", "Restarts", "Last error")
        for name, raw in dict(data.get("nodes", {})).items():
            health = dict(dict(raw).get("health", {}))
            table.add_row(
                name, "yes" if health.get("alive") else "no", "yes" if health.get("ready") else "no",
                str(health.get("status", "unknown")), f"{float(health.get('queue_pressure', 0.0)):.2f}",
                str(health.get("restart_count", 0)), str(health.get("last_error") or "-"),
            )
        console.clear() if watch else None
        console.print(table)
        if not watch:
            return
        time.sleep(interval)


@app.command("metrics")
def metrics_command(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    format_name: Annotated[str, typer.Option("--format", help="json or prometheus")] = "prometheus",
) -> None:
    """Print metrics from a live snapshot or completed run."""
    selected = run_id or _latest_run_id(project)
    directory = resolve_run(selected, project)
    status_path = directory / "status.json"
    data = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else load_run(selected, project)
    if format_name == "json":
        console.print_json(json.dumps(data))
    elif format_name == "prometheus":
        console.print(prometheus_text(data), markup=False, end="")
    else:
        raise typer.BadParameter("--format must be json or prometheus")


def _top_table(data: dict[str, object]) -> Table:
    table = Table("Node", "Scope", "CPU", "Memory", "Rate", "P95", "Queue", "Drops", "Health")
    for name, raw in dict(data.get("nodes", {})).items():
        node = dict(raw)
        resources = dict(node.get("resources", {}))
        health = dict(node.get("health", {}))
        memory_value = resources.get("rss_bytes")
        if not memory_value:
            memory_value = resources.get("shared_buffer_bytes") or resources.get("executor_rss_bytes")
        table.add_row(
            str(name),
            str(resources.get("scope", "-")),
            f"{float(resources.get('cpu_percent', 0.0)):.1f}%",
            _format_bytes(memory_value),
            f"{float(node.get('rate_hz', 0.0)):.1f} Hz",
            f"{float(node.get('p95_ms', 0.0)):.2f} ms",
            _format_bytes(resources.get("estimated_queue_bytes", 0)),
            str(resources.get("input_drops", 0)),
            str(health.get("status", "unknown")),
        )
    system = dict(data.get("system", {}))
    if system:
        footer = []
        if system.get("memory_available_bytes") is not None:
            footer.append(f"free {_format_bytes(system.get('memory_available_bytes'))}")
        if system.get("temperature_c") is not None:
            footer.append(f"temp {float(system['temperature_c']):.1f}°C")
        if system.get("load_average"):
            footer.append("load " + "/".join(f"{float(item):.2f}" for item in list(system["load_average"])[:3]))
        table.caption = " | ".join(footer)
    return table


@app.command("top")
def top_command(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    watch: Annotated[bool, typer.Option("--watch/--once")] = True,
    interval: Annotated[float, typer.Option("--interval", min=0.1)] = 1.0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show CPU, memory, queues, rates and latency for every node."""
    selected = run_id or _latest_run_id(project)
    while True:
        directory = resolve_run(selected, project)
        status_path = directory / "status.json"
        data = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else load_run(selected, project)
        if json_output:
            console.print_json(json.dumps(data))
            return
        if watch:
            console.clear()
        console.print(_top_table(data))
        if not watch:
            return
        time.sleep(interval)


@package_app.command("build")
def package_build_command(
    directory: Annotated[Path, typer.Argument(exists=True, file_okay=False)] = Path.cwd(),
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Build a checksummed .ndpkg archive."""
    try:
        target = build_package(directory, output)
    except Exception as exc:
        console.print(f"[red]Package build failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Built[/green] {target}")


@package_app.command("install")
def package_install_command(package: Annotated[Path, typer.Argument(exists=True, readable=True)]) -> None:
    """Install a local .ndpkg after path and checksum verification."""
    try:
        info = install_package(package)
    except Exception as exc:
        console.print(f"[red]Package installation failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Installed[/green] {info['name']} {info['version']} -> {info['path']}")


@package_app.command("list")
def package_list_command() -> None:
    table = Table("Package", "Version", "Nodes", "Path")
    for item in list_packages():
        table.add_row(item["name"], item["version"], ", ".join(item["nodes"]), item["path"])
    console.print(table)


@package_app.command("info")
def package_info_command(name: str) -> None:
    try:
        info = package_info(name)
    except Exception as exc:
        console.print(f"[red]Package not found:[/red] {exc}")
        raise typer.Exit(1)
    console.print_json(json.dumps(info))


@package_app.command("remove")
def package_remove_command(name: str) -> None:
    if not remove_package(name):
        console.print(f"[yellow]Package not installed:[/yellow] {name}")
        raise typer.Exit(1)
    console.print(f"[green]Removed[/green] {name}")


@runs_app.command("list")
def runs_list_command(project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd()) -> None:
    table = Table("Run", "Pipeline", "Status", "Seconds")
    for item in list_runs(project):
        table.add_row(item["id"], str(item.get("pipeline") or "-"), item["status"], str(item.get("duration_seconds") or "-"))
    console.print(table)


@runs_app.command("show")
def runs_show_command(run_id: str, project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd()) -> None:
    try:
        console.print_json(json.dumps(load_run(run_id, project)))
    except Exception as exc:
        console.print(f"[red]Cannot load run:[/red] {exc}")
        raise typer.Exit(1)


@runs_app.command("logs")
def runs_logs_command(run_id: str, project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd()) -> None:
    directory = resolve_run(run_id, project)
    found = False
    for path in sorted(directory.rglob("*.log")):
        found = True
        console.rule(str(path.relative_to(directory)))
        console.print(path.read_text(encoding="utf-8", errors="replace"))
    if not found:
        console.print("No log files")


@runs_app.command("compare")
def runs_compare_command(first: str, second: str, project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd()) -> None:
    console.print_json(json.dumps(compare_runs(first, second, project)))


@native_app.command("inspect")
def native_inspect_command(library: Annotated[Path, typer.Argument(exists=True, readable=True)]) -> None:
    """Inspect plugin ABI and mandatory exported symbols without creating a node."""
    try:
        lib = ctypes.CDLL(str(library.resolve()))
        abi_fn = lib.nodrix_plugin_abi_version
        abi_fn.restype = ctypes.c_uint32
        abi = int(abi_fn())
        features = 0
        if hasattr(lib, "nodrix_plugin_features"):
            features_fn = lib.nodrix_plugin_features
            features_fn.restype = ctypes.c_uint64
            features = int(features_fn())
        symbols = {
            "nodrix_plugin_abi_version": True,
            "nodrix_plugin_features": hasattr(lib, "nodrix_plugin_features"),
            "nodrix_create_node": hasattr(lib, "nodrix_create_node"),
            "nodrix_destroy_node": hasattr(lib, "nodrix_destroy_node"),
        }
    except Exception as exc:
        console.print(f"[red]Cannot inspect plugin:[/red] {exc}")
        raise typer.Exit(1)
    runtime_abi = 0x00010000
    table = Table("Field", "Value")
    table.add_row("Plugin ABI", f"{abi >> 16}.{abi & 0xffff} ({abi})")
    table.add_row("Runtime ABI", "1.0 (65536)")
    table.add_row("Compatible", "yes" if abi == runtime_abi and all(symbols.values()) else "no")
    table.add_row("Features", f"0x{features:016x}")
    table.add_row("Symbols", json.dumps(symbols))
    console.print(table)
    if abi != runtime_abi or not all(symbols.values()):
        raise typer.Exit(1)

def main() -> None:
    app()


if __name__ == "__main__":
    main()
