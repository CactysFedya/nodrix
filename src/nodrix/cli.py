from __future__ import annotations

import asyncio
import json
from pathlib import Path
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
from .execution_plan import compile_execution_plan, write_execution_plan
from .manifest import (
    canonical_config_path,
    load_block,
    load_fragment,
    load_manifest,
    load_manifest_details,
)
from .migration import migrate_manifest
from .hybrid_runtime import HybridPipelineRuntime
from .native_runtime import NATIVE_BUILTINS, NativePipelineRuntime, NativeToolchain
from .registry import BUILTINS, load_builtin_providers, load_node_class
from . import __version__
from .discovery import discover_streams, resolve_stream
from .project_templates import TEMPLATES, create_project
from .streams import StreamClient
from .type_codegen import generate_type
from .lockfile import write_lock, verify_lock
from .packages import (
    build_package,
    install_package,
    list_packages,
    package_info,
    remove_package,
    verify_package,
)
from .runs import compare_runs, latest_run_id, list_runs, load_run, resolve_run
from .benchmarking import direct_benchmark_plan, load_benchmark_plan, replay_plan, run_benchmark_suite
from .planning import (
    build_static_plan,
    diagnose_report,
    explain_target,
    select_optimization_variant,
    write_optimization_bundle,
)
from .validation import validate_production
from .metrics import MetricsServer, prometheus_text
from .profiles import profile_names
from .node_docs import parameter_schema
from .ux import (
    render_node_details,
    render_pipeline_graph,
    render_startup_summary,
    render_runtime_event,
    render_top,
)

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
plugin_app = typer.Typer(help="Search, verify, install, inspect, and remove offline plugins.")
runs_app = typer.Typer(help="Inspect reproducible run artifacts.")
config_app = typer.Typer(help="Inspect resolved profiles and configuration values.")
block_app = typer.Typer(help="List and inspect reusable YAML node blocks.")
fragment_app = typer.Typer(help="Create and validate reusable typed subgraphs.")
provider_app = typer.Typer(help="Discover and verify installed Provider API 1 distributions.")
app.add_typer(node_app, name="node")
app.add_typer(stream_app, name="stream")
app.add_typer(native_app, name="native")
app.add_typer(type_app, name="type")
app.add_typer(media_app, name="media")
app.add_typer(recording_app, name="recording")
app.add_typer(data_app, name="data-plane")
app.add_typer(device_app, name="device")
app.add_typer(package_app, name="package")
app.add_typer(plugin_app, name="plugin")
app.add_typer(runs_app, name="runs")
app.add_typer(config_app, name="config")
app.add_typer(block_app, name="block")
app.add_typer(fragment_app, name="fragment")
app.add_typer(provider_app, name="provider")
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


def _provider_policy(
    *,
    production: bool,
    trust_store: Path | None,
    allow: list[str] | None,
):
    from .providers import ProviderPolicy

    return ProviderPolicy.from_environment(
        production=production,
        trust_store=trust_store,
        allowlist=allow,
    )


@provider_app.command("list")
def provider_list_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON"),
    ] = False,
    production: Annotated[
        bool,
        typer.Option("--production", help="Apply production trust policy"),
    ] = False,
    trust_store: Annotated[
        Path | None,
        typer.Option("--trust-store", help="Directory containing trusted Ed25519 public keys"),
    ] = None,
    allow: Annotated[
        list[str] | None,
        typer.Option("--allow", help="Production provider id; repeatable"),
    ] = None,
) -> None:
    """List provider metadata without importing provider packages."""
    from .providers import provider_records

    try:
        records = provider_records(
            policy=_provider_policy(
                production=production,
                trust_store=trust_store,
                allow=allow,
            )
        )
    except Exception as exc:
        console.print(f"[red]Provider discovery failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(records))
        return
    table = Table("Provider", "Version", "Source", "Status", "Features")
    for item in records:
        table.add_row(
            item["id"],
            str(item["version"]),
            item["source"],
            item["verification"]["status"],
            ", ".join(item["features"]) or "-",
        )
    console.print(table)


@provider_app.command("info")
def provider_info_command(
    provider_id: Annotated[str, typer.Argument(help="Provider id or unambiguous suffix")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
    production: Annotated[bool, typer.Option("--production")] = False,
    trust_store: Annotated[Path | None, typer.Option("--trust-store")] = None,
    allow: Annotated[list[str] | None, typer.Option("--allow")] = None,
) -> None:
    """Show one provider's metadata and trust state without importing it."""
    from .providers import provider_record, resolve_provider

    try:
        candidate = resolve_provider(provider_id)
        record = provider_record(
            candidate,
            policy=_provider_policy(
                production=production,
                trust_store=trust_store,
                allow=allow,
            ),
        )
    except Exception as exc:
        console.print(f"[red]Provider info failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(record))
        return
    console.print(f"[bold]{record['id']}[/bold] {record['version']}")
    console.print(f"Distribution: {record['distribution']} ({record['source']})")
    console.print(f"Provider API: {record['provider_api']}")
    console.print(f"Requires Nodrix: {record['requires_nodrix']}")
    console.print(f"Trust status: {record['verification']['status']}")
    if record["verification"]["errors"]:
        for error in record["verification"]["errors"]:
            console.print(f"[red]- {error}[/red]")
    table = Table("Kind", "Id", "Implementation")
    for node in record["nodes"]:
        table.add_row("node", node["id"], node["factory"])
    for probe in record["probes"]:
        table.add_row("probe", probe["id"], probe["callable"])
    for template in record["templates"]:
        table.add_row("template", template["id"], template["source"])
    console.print(table)


@provider_app.command("verify")
def provider_verify_command(
    provider_id: Annotated[str, typer.Argument(help="Provider id or unambiguous suffix")],
    production: Annotated[bool, typer.Option("--production")] = False,
    trust_store: Annotated[Path | None, typer.Option("--trust-store")] = None,
    allow: Annotated[list[str] | None, typer.Option("--allow")] = None,
) -> None:
    """Verify metadata, compatibility, features, signature, and trust policy."""
    from .providers import verify_provider

    try:
        result = verify_provider(
            provider_id,
            policy=_provider_policy(
                production=production,
                trust_store=trust_store,
                allow=allow,
            ),
        )
    except Exception as exc:
        console.print(f"[red]Provider verification failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print_json(json.dumps(result.to_dict()))
    if result.errors:
        raise typer.Exit(1)


@app.command("doctor")
def doctor_command(
    deep: Annotated[
        bool,
        typer.Option("--deep", help="Allow deep/device-acquiring provider probes"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON"),
    ] = False,
    provider_id: Annotated[
        str | None,
        typer.Option("--provider", help="Limit diagnostics to one provider"),
    ] = None,
    production: Annotated[
        bool,
        typer.Option("--production", help="Apply production provider trust policy"),
    ] = False,
    trust_store: Annotated[Path | None, typer.Option("--trust-store")] = None,
    allow: Annotated[list[str] | None, typer.Option("--allow")] = None,
) -> None:
    """Run unified Core and provider diagnostics."""
    from .doctor import doctor_report

    try:
        report = doctor_report(
            deep=deep,
            provider_id=provider_id,
            production=production,
            trust_store=trust_store,
            allowlist=allow,
        )
    except Exception as exc:
        console.print(f"[red]Doctor failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(report))
    else:
        console.print(
            f"[bold]Nodrix {report['runtime']['nodrix']} doctor[/bold] "
            f"mode={report['mode']} status={report['status']}"
        )
        core_table = Table("Core check", "Status")
        for item in report["core"]:
            core_table.add_row(item["id"], item["status"])
        console.print(core_table)
        provider_table = Table("Provider", "Source", "Trust", "Diagnostics")
        for item in report["providers"]:
            diagnostic_status = ", ".join(
                f"{probe['id']}={probe['status']}"
                for probe in item["diagnostics"]
            ) or "-"
            provider_table.add_row(
                item["id"],
                item["source"],
                item["verification"]["status"],
                diagnostic_status,
            )
        console.print(provider_table)
    if report["status"] == "error":
        raise typer.Exit(1)


def _runtime(
    path: Path,
    run_root: Path | None = None,
    *,
    profile: str | None = None,
    overrides: list[str] | None = None,
    block_overrides: list[str] | None = None,
    event_callback=None,
    production: bool = False,
):
    manifest = load_manifest(
        path,
        profile=profile,
        overrides=overrides,
        block_overrides=block_overrides,
    )
    if production:
        preflight = validate_production(
            manifest,
            {"edges": []},
            strict=True,
            production=True,
        )
        failures = [
            issue for issue in preflight if issue.severity == "error"
        ]
        if failures:
            rendered = "; ".join(
                f"{issue.code} {issue.location}: {issue.message}"
                for issue in failures
            )
            raise NodrixError(
                f"Production preflight failed before loading plugins: "
                f"{rendered}"
            )
        from .providers import (
            ProviderPolicy,
            verify_provider_nodes,
        )

        references = [
            reference
            for config in manifest.nodes.values()
            for reference in (
                config.uses,
                config.failure.fallback_uses,
            )
            if reference is not None
        ]
        verify_provider_nodes(
            references,
            policy=ProviderPolicy.from_environment(production=True),
        )
    native_only = all(
        config.uses.startswith("native.") or config.uses.startswith("native:")
        for config in manifest.nodes.values()
    )
    use_native = manifest.runtime.engine == "native" or (
        manifest.runtime.engine == "auto" and native_only
    )
    if use_native:
        if manifest.streams.exports or manifest.recording.enabled:
            raise NodrixError(
                "Named LAN streams and automatic recording require engine: unified; "
                "the standalone native executor does not expose those control-plane services."
            )
        runtime = NativePipelineRuntime(manifest, path, run_root=run_root)
    else:
        runtime = HybridPipelineRuntime(
            manifest,
            path,
            run_root=run_root,
            event_callback=event_callback,
        )
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
    production: Annotated[bool, typer.Option("--production", help="Apply the complete Manifest v2 production gate")] = False,
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
            production=production,
        )
        desc = runtime.describe()
        issues = validate_production(
            runtime.manifest,
            desc,
            strict=strict or production,
            production=production,
        )
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
    plan: Annotated[bool, typer.Option("--plan", help="Print the deterministic resolved execution plan as JSON")] = False,
    node_name: Annotated[str | None, typer.Option("--node", help="Inspect one node instance")] = None,
    details_view: Annotated[bool, typer.Option("--details", help="Include resolved block parameters in the graph")] = False,
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
        if plan:
            runtime = _runtime(
                pipeline,
                profile=profile,
                overrides=set_values,
                block_overrides=block_values,
            )
            execution_plan = compile_execution_plan(details.manifest, runtime.describe())
            if output is not None:
                write_execution_plan(execution_plan, output)
                console.print(f"[green]Written[/green] {output.resolve()}")
            else:
                console.print_json(json.dumps(execution_plan, ensure_ascii=False))
            return
        if node_name is not None:
            console.print(
                render_node_details(details.manifest, node_name)
            )
            return
        if not live and not memory:
            console.print(render_pipeline_graph(details.manifest, details=details_view))
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
    production: Annotated[bool, typer.Option("--production", help="Enforce the Manifest v2 production safety gate")] = False,
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
    runtime = None
    try:
        details = load_manifest_details(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        indexes = {
            name: index
            for index, name in enumerate(details.manifest.nodes, start=1)
        }

        def runtime_event(event: dict[str, object]) -> None:
            console.print(
                render_runtime_event(event, indexes, len(indexes))
            )

        if production:
            runtime = _runtime(
                pipeline,
                run_root=run_root,
                profile=profile,
                overrides=set_values,
                block_overrides=block_values,
                event_callback=runtime_event,
                production=True,
            )
            production_issues = validate_production(
                details.manifest,
                runtime.describe(),
                strict=True,
                production=True,
            )
            failures = [
                item for item in production_issues if item.severity == "error"
            ]
            if failures:
                rendered = "; ".join(
                    f"{item.code} {item.location}: {item.message}"
                    for item in failures
                )
                raise NodrixError(f"Production validation failed: {rendered}")
        console.print(render_startup_summary(details.manifest, __version__))
        media_encoders = [
            (instance, config)
            for instance, config in details.manifest.nodes.items()
            if config.uses == "media.ffmpeg_encoder"
        ]
        if media_encoders:
            from .media import MediaError, select_encoder

            for instance, config in media_encoders:
                selection = select_encoder(
                    str(config.parameters.get("codec", "h264")),
                    str(config.parameters.get("encoder", "auto")),
                    str(config.parameters.get("acceleration", "preferred")),
                )
                if not selection.get("ok"):
                    attempts = "; ".join(
                        f"{item.get('encoder')}: {item.get('reason')}"
                        for item in selection.get("attempts", [])
                    )
                    raise MediaError(
                        f"Encoder {instance} cannot start: "
                        f"{selection.get('reason')}"
                        + (f" ({attempts})" if attempts else "")
                    )

        if runtime is None:
            runtime = _runtime(
                pipeline,
                run_root=run_root,
                profile=profile,
                overrides=set_values,
                block_overrides=block_values,
                event_callback=runtime_event,
                production=production,
            )
        metrics_target = metrics_listen or details.manifest.runtime.metrics.listen
        if metrics_target:
            if not hasattr(runtime, "snapshot"):
                raise NodrixError("HTTP metrics currently require engine: unified")
            host, port_text = metrics_target.rsplit(":", 1)
            metrics_server = MetricsServer(lambda: runtime.snapshot(), host, int(port_text))
            metrics_server.start()
            host, port = metrics_server.address
            console.print(f"Metrics READY · http://{host}:{port}/metrics")
        report = runtime.run_sync() if isinstance(runtime, HybridPipelineRuntime) else asyncio.run(runtime.run())
    except KeyboardInterrupt:
        console.print("[yellow]Shutdown requested; stopping pipeline gracefully.[/yellow]")
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
    from .recording import record_streams

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
    start: Annotated[int, typer.Option("--start", min=0, help="Seek to zero-based message index")] = 0,
    count: Annotated[int, typer.Option("--count", min=0, help="Play at most N messages; 0 means all")] = 0,
    fixed_fps: Annotated[float, typer.Option("--fixed-fps", min=0.0, help="Use a fixed replay rate; 0 preserves timing")] = 0.0,
) -> None:
    """Replay an .ndrx recording as discoverable Nodrix streams."""
    from .recording import RecordingError, play_recording

    try:
        report = play_recording(
            recording, speed=speed, as_fast_as_possible=as_fast_as_possible,
            stream_prefix=prefix, loop=loop, startup_delay=startup_delay,
            start=start, count=count, fixed_fps=fixed_fps,
        )
    except (OSError, ValueError, RecordingError) as exc:
        console.print(f"[red]Playback failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Played[/green] {report['messages']} messages")


@app.command()
def replay(
    run_id: Annotated[str, typer.Argument(help="Run id or unique run-id fragment")],
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    execute: Annotated[bool, typer.Option("--execute", help="Execute replay when a captured .ndrx input is available")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect whether a run is reproducible and replay captured .ndrx input."""
    try:
        directory = resolve_run(run_id, project)
        plan = replay_plan(directory)
    except Exception as exc:
        console.print(f"[red]Replay inspection failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(plan))
    else:
        console.print(f"Replayable: {'yes' if plan['replayable'] else 'no'}")
        console.print(f"Mode: {plan['mode']}")
        console.print(f"Reason: {plan['reason']}")
        if plan.get("command"):
            console.print("Command: " + " ".join(str(item) for item in plan["command"]))
    if not execute:
        if not plan["replayable"]:
            raise typer.Exit(2)
        return
    if plan.get("mode") != "recording":
        console.print("[red]Automatic execution is restricted to captured .ndrx recordings.[/red]")
        raise typer.Exit(2)
    completed = subprocess.run([str(item) for item in plan["command"]], check=False)
    if completed.returncode:
        raise typer.Exit(completed.returncode)


@app.command("migrate")
def migrate_command(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)],
    target_version: Annotated[str, typer.Option("--to")] = "v2",
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    in_place: Annotated[bool, typer.Option("--in-place", help="Replace source after creating a backup")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show changes without writing")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Migrate a 1.x manifest to stable v2 without overwriting it by default."""
    if target_version != "v2":
        console.print(f"[red]Unsupported migration target:[/red] {target_version}")
        raise typer.Exit(2)
    try:
        result = migrate_manifest(
            pipeline,
            output=output,
            in_place=in_place,
            write=not dry_run,
        )
    except Exception as exc:
        console.print(f"[red]Migration failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        return
    table = Table("Path", "Before", "After", "Reason")
    for change in result["changes"]:
        table.add_row(
            change["path"],
            change["from"],
            change["to"],
            change["reason"],
        )
    console.print(table)
    if result["incompatibilities"]:
        for incompatibility in result["incompatibilities"]:
            console.print(f"[red]- {incompatibility}[/red]")
    if dry_run:
        console.print("[yellow]Dry run: no files were written.[/yellow]")
    else:
        console.print(f"[green]Written[/green] {result['destination']}")
        if result.get("backup"):
            console.print(f"Backup: {result['backup']}")


@recording_app.command("info")
def recording_info(recording: Annotated[Path, typer.Argument(exists=True, readable=True)]) -> None:
    """Show streams, types, counts, and size of an .ndrx file."""
    from .recording import NdrxReader, RecordingError

    try:
        with NdrxReader(recording) as reader:
            info = reader.info()
    except (OSError, ValueError, RecordingError) as exc:
        console.print(f"[red]Cannot read recording:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[bold]{info['path']}[/bold]  messages={info['messages']} size={info['size_bytes']} bytes")
    table = Table("Stream", "Type", "Messages")
    for name, spec in info.get("streams", {}).items():
        table.add_row(name or "(unnamed)", str(spec.get("type", "core.any")), str(spec.get("messages", 0)))
    console.print(table)


@recording_app.command("repair")
def recording_repair(
    recording: Annotated[Path, typer.Argument(exists=True, readable=True)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    checkpoint_records: Annotated[int, typer.Option("--checkpoint-records", min=1)] = 1024,
) -> None:
    """Recover complete records and write a finalized NDRX2 file."""
    from .recording import RecordingError, repair_recording

    try:
        info = repair_recording(
            recording,
            output,
            checkpoint_records=checkpoint_records,
        )
    except (OSError, ValueError, RecordingError) as exc:
        console.print(f"[red]Cannot repair recording:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"[green]Repaired[/green] {info['messages']} messages to {info['path']}"
    )


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


def _execute_benchmark_run(
    pipeline: Path,
    run_root: Path,
    profile: str | None,
    set_values: list[str],
    block_values: list[str],
) -> dict[str, object]:
    runtime = _runtime(
        pipeline,
        run_root=run_root,
        profile=profile,
        overrides=set_values,
        block_overrides=block_values,
    )
    return runtime.run_sync() if isinstance(runtime, HybridPipelineRuntime) else asyncio.run(runtime.run())


@app.command()
def benchmark(
    pipeline: Annotated[Path | None, typer.Argument(help="Pipeline manifest; defaults to pipeline.yaml")] = None,
    spec: Annotated[Path | None, typer.Option("--spec", help="Versioned benchmark YAML specification")] = None,
    repeat: Annotated[int | None, typer.Option("--repeat", min=1)] = None,
    warmup: Annotated[int | None, typer.Option("--warmup", min=0)] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Benchmark artifact root or legacy summary .json path")] = None,
    variants: Annotated[list[str] | None, typer.Option("--variant", help="Run only a named variant from --spec")] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run a reproducible benchmark suite with warm-up, variants, artifacts and percentiles."""
    try:
        if spec is not None:
            plan = load_benchmark_plan(
                spec,
                pipeline_override=pipeline,
                repeat_override=repeat,
                warmup_override=warmup,
                selected_variants=variants,
            )
            if profile is not None or set_values or block_values:
                raise ValueError("--profile, --set and --block belong in benchmark variants when --spec is used")
        else:
            plan = direct_benchmark_plan(
                pipeline or Path("pipeline.yaml"),
                repeat=repeat if repeat is not None else 3,
                warmup=warmup if warmup is not None else 1,
                profile=profile,
                set_values=set_values,
                block_values=block_values,
            )
        legacy_json = output if output is not None and output.suffix.lower() == ".json" else None
        root = output.parent if legacy_json is not None else output
        summary = run_benchmark_suite(plan, _execute_benchmark_run, output_root=root)
        if legacy_json is not None:
            legacy_json.parent.mkdir(parents=True, exist_ok=True)
            legacy_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        console.print(f"[red]Benchmark failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(summary))
        return
    table = Table("Variant", "Runs", "Source Hz", "Sink Hz", "E2E P95 ms", "Drops", "Memory")
    for name, raw in dict(summary.get("variants", {})).items():
        item = dict(raw)
        table.add_row(
            str(name),
            str(item.get("runs", 0)),
            f"{float(dict(item.get('source_rate_hz') or {}).get('mean', 0.0)):.2f}",
            f"{float(dict(item.get('sink_rate_hz') or {}).get('mean', 0.0)):.2f}",
            f"{float(dict(item.get('end_to_end_p95_ms') or {}).get('mean', 0.0)):.3f}",
            f"{float(dict(item.get('dropped_messages') or {}).get('mean', 0.0)):.1f}",
            _format_bytes(dict(item.get("estimated_memory_bytes") or {}).get("mean")),
        )
    console.print(table)
    console.print(f"Artifacts: {summary['suite_dir']}")


@app.command("plan")
def plan_command(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Plan rates, memory paths, queues, and probed hardware without running the graph."""
    try:
        details = load_manifest_details(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        runtime = _runtime(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        result = build_static_plan(details.manifest, runtime.describe())
    except Exception as exc:
        console.print(f"[red]Planning failed:[/red] {exc}")
        raise typer.Exit(1)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        console.print(f"[green]Written[/green] {output.resolve()}")
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
        return
    table = Table("Node", "Configured estimate", "Basis")
    for name, raw in result["rates"].items():
        rate = raw.get("estimated_hz")
        table.add_row(
            name,
            f"{float(rate):.2f} Hz" if rate is not None else "unknown",
            str(raw.get("basis", "")),
        )
    console.print(table)
    expected = result.get("expected_output_hz")
    console.print(
        "Expected output: "
        + (f"{float(expected):.2f} Hz" if expected is not None else "unknown until measured")
    )
    for decision in result["backend_decisions"]:
        console.print(
            f"{decision['target']}: {decision.get('selected') or 'unavailable'}"
            f" · {decision.get('reason')}"
        )
    for recommendation in result["recommendations"]:
        console.print(
            f"[yellow]{recommendation['code']}[/yellow] "
            f"{recommendation['target']}: {recommendation['message']}"
        )


def _latest_run_report(root: Path) -> Path:
    candidates = [
        path
        for base in (root / ".nodrix" / "runs", root / "runs")
        if base.is_dir()
        for path in base.rglob("summary.json")
    ]
    if not candidates:
        raise FileNotFoundError(
            "No completed run was found; pass a run directory/report or use --run with a pipeline."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


@app.command("diagnose")
def diagnose_command(
    target: Annotated[Path | None, typer.Argument(help="Run directory, summary JSON, or pipeline")] = None,
    run_pipeline: Annotated[bool, typer.Option("--run", help="Execute a pipeline before diagnosis")] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Diagnose measured bottlenecks, queue pressure, copies, fallbacks, and thermals."""
    try:
        if target is None:
            report_path = _latest_run_report(Path.cwd())
            report = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            resolved = target.expanduser().resolve()
            if resolved.is_dir():
                report_path = resolved / "summary.json"
                report = json.loads(report_path.read_text(encoding="utf-8"))
            elif resolved.suffix.lower() in {".yaml", ".yml"}:
                if not run_pipeline:
                    raise ValueError(
                        "Diagnosing a pipeline requires measurements; add --run or pass a completed run."
                    )
                runtime = _runtime(resolved)
                report = (
                    runtime.run_sync()
                    if isinstance(runtime, HybridPipelineRuntime)
                    else asyncio.run(runtime.run())
                )
            else:
                report = json.loads(resolved.read_text(encoding="utf-8"))
        result = diagnose_report(report)
    except Exception as exc:
        console.print(f"[red]Diagnosis failed:[/red] {exc}")
        raise typer.Exit(1)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        console.print(f"[green]Written[/green] {output.resolve()}")
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
        return
    table = Table("Severity", "Code", "Target", "Finding", "Evidence")
    for finding in result["findings"]:
        table.add_row(
            str(finding["severity"]),
            str(finding["code"]),
            str(finding["target"]),
            str(finding["message"]),
            json.dumps(finding.get("evidence"), ensure_ascii=False, default=str),
        )
    console.print(table)
    if not result["findings"]:
        console.print("[green]No measured bottleneck or pressure finding.[/green]")


@app.command("explain")
def explain_command(
    target: Annotated[list[str], typer.Argument(help="Node, dotted config path, backend, or edge SOURCE:TARGET")],
    pipeline: Annotated[Path, typer.Option("--pipeline", "-p", exists=True, readable=True)] = Path("pipeline.yaml"),
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Explain a resolved value, node, edge, or backend selection."""
    rendered_target = " ".join(target)
    try:
        details = load_manifest_details(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        runtime = _runtime(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        result = explain_target(details, runtime.describe(), rendered_target)
    except Exception as exc:
        console.print(f"[red]Cannot explain {rendered_target!r}:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        return
    console.print(f"Target: [bold]{result.get('target')}[/bold]")
    console.print(
        "Value: "
        + yaml.safe_dump(result.get("value", result.get("selected")), sort_keys=False).strip()
    )
    console.print(f"Source: {result.get('source', result.get('evidence', '-'))}")
    console.print(f"Reason: {result.get('reason', '-')}")
    rejected = result.get("rejected") or []
    if rejected:
        console.print("Rejected: " + json.dumps(rejected, ensure_ascii=False, default=str))


@app.command("optimize")
def optimize_command(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")] = Path(".nodrix/optimization"),
    max_variants: Annotated[int, typer.Option("--max-variants", min=1, max=100)] = 12,
    latency_p95_ms: Annotated[float | None, typer.Option("--latency-p95-ms", min=0.0)] = None,
    temperature_c: Annotated[float | None, typer.Option("--temperature-c", min=0.0)] = None,
    memory_mb: Annotated[float | None, typer.Option("--memory-mb", min=0.0)] = None,
    run_benchmarks: Annotated[bool, typer.Option("--benchmark", help="Evaluate generated variants now")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate separate tuning variants; never modify the production pipeline."""
    try:
        details = load_manifest_details(pipeline)
        constraints = {
            key: value
            for key, value in {
                "latency_p95_ms": latency_p95_ms,
                "temperature_c": temperature_c,
                "memory_mb": memory_mb,
            }.items()
            if value is not None
        }
        spec_path, report_path, result = write_optimization_bundle(
            pipeline,
            details.manifest,
            output_dir.expanduser().resolve(),
            max_variants=max_variants,
            constraints=constraints,
        )
        if run_benchmarks:
            benchmark_plan = load_benchmark_plan(spec_path)
            benchmark_result = run_benchmark_suite(
                benchmark_plan,
                _execute_benchmark_run,
                output_root=output_dir.expanduser().resolve() / "benchmarks",
            )
            result = {**result, "benchmark": benchmark_result}
            result["recommendation"] = select_optimization_variant(
                benchmark_result,
                constraints=constraints,
            )
            report_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except Exception as exc:
        console.print(f"[red]Optimization planning failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        return
    console.print(f"[green]Generated[/green] {len(result['variants'])} variants")
    console.print(f"Benchmark spec: {spec_path}")
    console.print(f"Decision report: {report_path}")
    if result.get("recommendation"):
        console.print(
            "Recommended measured variant: "
            f"{result['recommendation'].get('selected') or 'none'}"
        )
    console.print("Source pipeline was not modified.")

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
    from .media import MediaError, media_doctor

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
    acceleration: Annotated[str, typer.Option("--acceleration", help="required, preferred, or disabled")] = "required",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Probe encoder backends using an explicit hardware policy."""
    from .media import select_encoder

    try:
        result = select_encoder(codec, requested, acceleration)
    except Exception as exc:
        console.print(f"[red]Encoder selection failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(result))
        return
    selected = result.get("selected") or "none"
    style = "green" if result.get("hardware") else "yellow"
    console.print(f"Selected: [{style}]{selected}[/{style}]")
    console.print(f"Policy: {result.get('acceleration')}")
    console.print(f"Hardware: {'yes' if result.get('hardware') else 'no'}")
    console.print(f"Reason: {result.get('reason')}")
    for attempt in result.get("attempts", []):
        marker = "✓" if attempt.get("ok") else "×"
        console.print(f"  {marker} {attempt.get('encoder')}: {attempt.get('reason')}")
    if not result.get("ok"):
        raise typer.Exit(1)


@media_app.command("probe")
def media_probe_command(
    source: Annotated[str, typer.Argument(help="File, RTSP/HTTP/SRT URL, or FFmpeg input")],
    input_format: Annotated[str | None, typer.Option("--format", help="Optional FFmpeg input format")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect media streams with ffprobe."""
    from .media import MediaError, probe_media

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
    from .media import run_ffmpeg_relay

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
    from .media import run_ffmpeg_relay

    code = run_ffmpeg_relay(source, output, copy=copy, codec=codec, encoder=encoder, rtsp_transport=rtsp_transport)
    raise typer.Exit(code)


@node_app.command("list")
def node_list(
    pipeline: Annotated[Path | None, typer.Option("--pipeline", "-p", help="Show only node types used by a pipeline")] = None,
) -> None:
    """List available node types, or only the types used by one pipeline."""
    load_builtin_providers()
    selected: dict[str, type] = dict(BUILTINS)
    title = f"Available node types ({len(selected)})"
    if pipeline is not None:
        manifest = load_manifest(pipeline)
        used = {config.uses for config in manifest.nodes.values()}
        selected = {name: cls for name, cls in BUILTINS.items() if name in used}
        title = f"Node types used by {manifest.metadata.name} ({len(selected)})"
    console.print(f"[bold]{title}[/bold]")
    groups: dict[str, list[tuple[str, type]]] = {}
    for node_id, cls in sorted(selected.items()):
        group = node_id.split(".", 1)[0].upper()
        groups.setdefault(group, []).append((node_id, cls))
    for group, items in groups.items():
        console.print(f"\n[cyan]{group}[/cyan]")
        for node_id, cls in items:
            optional = set(getattr(cls, "optional_inputs", ()))
            inputs = ", ".join(
                f"{name}{'?' if name in optional else ''}:{kind}"
                for name, kind in cls.input_types.items()
            ) or "source"
            outputs = ", ".join(f"{name}:{kind}" for name, kind in cls.output_types.items()) or "sink"
            console.print(f"  [bold]{node_id:<30}[/bold] {inputs} → {outputs}")


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
    cpp_inputs = ", ".join(
        f'{{sizeof(nodrix_port_v2), "{port}", "{type_name}", "any"}}'
        for port, type_name in input_ports.items()
    )
    cpp_outputs = ", ".join(
        f'{{sizeof(nodrix_port_v2), "{port}", "{type_name}", "any"}}'
        for port, type_name in output_ports.items()
    )
    node_type = name.replace("_", ".").replace("-", ".")
    source_lines = [
        "#include <array>",
        "#include <cstring>",
        "",
        '#include "nodrix/cpp_plugin.hpp"',
        "",
        f"class {class_name} final : public nodrix::c_api::Node {{",
        " public:",
        "  std::span<const nodrix_port_v2> input_ports() const noexcept override { return inputs_; }",
        "  std::span<const nodrix_port_v2> output_ports() const noexcept override { return outputs_; }",
        "",
        "  nodrix_status_v2 process(std::span<const nodrix_message_v2> inputs,",
        "                           const nodrix::c_api::Emitter& emitter) override {",
        "    // Replace with the detector/filter/tracker implementation.",
        "    // The host retains owned payloads emitted synchronously here.",
        "    if (!outputs_.empty() && !inputs.empty()) emitter.emit(0, inputs.front());",
        "    return NODRIX_STATUS_OK;",
        "  }",
        "",
        " private:",
        f"  const std::array<nodrix_port_v2, {len(input_ports)}> inputs_{{{{{cpp_inputs}}}}};",
        f"  const std::array<nodrix_port_v2, {len(output_ports)}> outputs_{{{{{cpp_outputs}}}}};",
        "};",
        "",
        'extern "C" NODRIX_C_EXPORT uint32_t nodrix_plugin_abi_version_v2() {',
        "  return NODRIX_C_ABI_VERSION;",
        "}",
        'extern "C" NODRIX_C_EXPORT uint64_t nodrix_plugin_features_v2() {',
        "  return NODRIX_C_FEATURE_TYPED_PORTS | NODRIX_C_FEATURE_MEMORY_DOMAINS |",
        "         NODRIX_C_FEATURE_ZERO_COPY_BUFFERS;",
        "}",
        'extern "C" NODRIX_C_EXPORT nodrix_status_v2 nodrix_plugin_create_v2(',
        "    uint32_t host_abi, const char* node_type, const char*,",
        "    nodrix_node_api_v2* output) {",
        "  if (host_abi != NODRIX_C_ABI_VERSION) return NODRIX_STATUS_ABI_MISMATCH;",
        f'  if (!node_type || std::strcmp(node_type, "{node_type}") != 0)',
        "    return NODRIX_STATUS_UNSUPPORTED;",
        f"  return nodrix::c_api::export_node(new {class_name}(), output);",
        "}",
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
    rows = parameter_schema(reference)
    if rows:
        table = Table(
            "Parameter",
            "Type",
            "Default",
            "Range / values",
            "Description",
        )
        for row in rows:
            table.add_row(
                str(row.get("name", "")),
                str(row.get("type", "")),
                str(row.get("default", "")),
                str(row.get("values", "")),
                str(row.get("description", "")),
            )
        console.print(table)


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


@fragment_app.command("validate")
def fragment_validate_command(
    fragment: Annotated[Path, typer.Argument(exists=True, readable=True)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a Fragment SDK manifest and show its public contracts."""
    try:
        config = load_fragment(fragment)
    except Exception as exc:
        console.print(f"[red]Invalid fragment:[/red] {exc}")
        raise typer.Exit(1)
    result = {
        "valid": True,
        "version": config.version,
        "inputs": config.inputs,
        "outputs": config.outputs,
        "nodes": sorted(config.nodes),
        "nested_fragments": sorted(config.fragments),
        "hardware_requirements": config.hardware_requirements,
    }
    if json_output:
        console.print_json(json.dumps(result))
        return
    console.print(f"[green]Valid fragment[/green] {fragment} v{config.version}")
    console.print(f"Inputs: {json.dumps(config.inputs)}")
    console.print(f"Outputs: {json.dumps(config.outputs)}")
    console.print(f"Nodes: {', '.join(sorted(config.nodes))}")


@fragment_app.command("init")
def fragment_init_command(
    name: Annotated[str, typer.Argument()],
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Create a minimal documented Fragment SDK package."""
    target = (output or Path(name)).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        console.print(f"[red]Directory is not empty:[/red] {target}")
        raise typer.Exit(1)
    target.mkdir(parents=True, exist_ok=True)
    fragment = {
        "version": "1.0.0",
        "description": f"Reusable {name} subgraph",
        "documentation": "README.md",
        "tests": ["tests/test_contract.py"],
        "inputs": {"input": "processor.input"},
        "outputs": {"output": "processor.output"},
        "nodes": {
            "processor": {
                "uses": "core.delay",
                "parameters": {"milliseconds": 0},
            }
        },
        "edges": [],
        "hardware_requirements": [],
    }
    (target / "fragment.yaml").write_text(
        yaml.safe_dump(fragment, sort_keys=False),
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        f"# {name}\n\nValidate with `nodrix fragment validate fragment.yaml`.\n",
        encoding="utf-8",
    )
    tests_dir = target / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_contract.py").write_text(
        "from nodrix import load_fragment\n\n"
        "def test_contract():\n"
        "    fragment = load_fragment('fragment.yaml')\n"
        "    assert fragment.inputs and fragment.outputs\n",
        encoding="utf-8",
    )
    console.print(f"[green]Created fragment SDK[/green] {target}")


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
    target: Annotated[str, typer.Argument(help="Stream name or nodrix:// or nodrix+tls:// URI")],
    count: Annotated[int, typer.Option("--count", "-n", min=1)] = 1,
    discovery_timeout: Annotated[float, typer.Option("--discovery-timeout", min=0.05)] = 3.0,
    token: Annotated[str | None, typer.Option("--token", help="Stream access token")] = None,
    ca_file: Annotated[Path | None, typer.Option("--ca", help="Trusted CA for TLS")] = None,
    certificate: Annotated[Path | None, typer.Option("--cert", help="Client certificate for mTLS")] = None,
    private_key: Annotated[Path | None, typer.Option("--key", help="Client private key for mTLS")] = None,
    server_hostname: Annotated[str | None, typer.Option("--server-name", help="Expected TLS server name")] = None,
    reconnect_attempts: Annotated[int, typer.Option("--reconnect-attempts", min=0, max=100)] = 0,
) -> None:
    """Subscribe directly to a stream and print message headers/payload summaries."""
    client = StreamClient(
        target,
        discovery_timeout=discovery_timeout,
        token=token,
        ca_file=str(ca_file) if ca_file else None,
        certificate=str(certificate) if certificate else None,
        private_key=str(private_key) if private_key else None,
        server_hostname=server_hostname,
        reconnect_attempts=reconnect_attempts,
    )
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
    return latest_run_id(project)


@app.command("status")
def status_command(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the latest live status snapshot or final run summary."""
    try:
        selected = run_id or _latest_run_id(project)
        data = load_run(selected, project)
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
    while True:
        selected = run_id or _latest_run_id(project)
        data = load_run(selected, project)
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
    data = load_run(selected, project)
    if format_name == "json":
        console.print_json(json.dumps(data))
    elif format_name == "prometheus":
        console.print(prometheus_text(data), markup=False, end="")
    else:
        raise typer.BadParameter("--format must be json or prometheus")


def _top_table(data: dict[str, object]):
    return render_top(data)


@app.command("top")
def top_command(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    watch: Annotated[bool, typer.Option("--watch/--once")] = True,
    interval: Annotated[float, typer.Option("--interval", min=0.1)] = 1.0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    "Show a compact htop-style runtime dashboard."

    def snapshot() -> dict[str, object]:
        # Explicit --run pins the dashboard. Otherwise follow the active run.
        selected = run_id or _latest_run_id(project)
        return load_run(selected, project)

    data = snapshot()
    if json_output:
        console.print_json(json.dumps(data))
        return
    if not watch or not console.is_terminal:
        console.print(_top_table(data))
        return

    with Live(
        _top_table(data),
        console=console,
        refresh_per_second=max(2, int(1.0 / interval)),
        screen=True,
        transient=True,
    ) as live_view:
        try:
            while True:
                time.sleep(interval)
                live_view.update(
                    _top_table(snapshot()),
                    refresh=True,
                )
        except KeyboardInterrupt:
            return


@package_app.command("build")
def package_build_command(
    directory: Annotated[Path, typer.Argument(exists=True, file_okay=False)] = Path.cwd(),
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    signing_key: Annotated[Path | None, typer.Option("--sign-key", help="Ed25519 private PEM key")] = None,
) -> None:
    """Build a checksummed .ndpkg archive."""
    try:
        target = build_package(directory, output, signing_key=signing_key)
    except Exception as exc:
        console.print(f"[red]Package build failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Built[/green] {target}")


@package_app.command("install")
def package_install_command(
    package: Annotated[Path, typer.Argument(exists=True, readable=True)],
    public_key: Annotated[Path | None, typer.Option("--public-key", help="Trusted Ed25519 public PEM key")] = None,
    require_signature: Annotated[bool, typer.Option("--require-signature")] = False,
) -> None:
    """Install a local .ndpkg after path and checksum verification."""
    try:
        info = install_package(
            package,
            public_key=public_key,
            require_signature=require_signature,
        )
    except Exception as exc:
        console.print(f"[red]Package installation failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Installed[/green] {info['name']} {info['version']} -> {info['path']}")


@package_app.command("verify")
def package_verify_command(
    package: Annotated[Path, typer.Argument(exists=True, readable=True)],
    public_key: Annotated[Path | None, typer.Option("--public-key")] = None,
    require_signature: Annotated[bool, typer.Option("--require-signature")] = False,
) -> None:
    """Verify archive checksums and an optional trusted Ed25519 signature."""
    try:
        result = verify_package(
            package,
            public_key=public_key,
            require_signature=require_signature,
        )
    except Exception as exc:
        console.print(f"[red]Package verification failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print_json(json.dumps(result))


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


@plugin_app.command("search")
def plugin_search_command(query: str = "") -> None:
    """Search the installed offline plugin registry."""
    items = [
        item
        for item in list_packages()
        if not query or query.lower() in item["name"].lower()
    ]
    console.print_json(json.dumps(items))


@plugin_app.command("install")
def plugin_install_command(
    package: Annotated[Path, typer.Argument(exists=True, readable=True)],
    public_key: Annotated[Path | None, typer.Option("--public-key")] = None,
    require_signature: Annotated[bool, typer.Option("--require-signature")] = False,
) -> None:
    """Install an offline plugin after checksum/signature verification."""
    package_install_command(package, public_key, require_signature)


@plugin_app.command("info")
def plugin_info_command(name: str) -> None:
    package_info_command(name)


@plugin_app.command("verify")
def plugin_verify_command(
    package: Annotated[Path, typer.Argument(exists=True, readable=True)],
    public_key: Annotated[Path | None, typer.Option("--public-key")] = None,
    require_signature: Annotated[bool, typer.Option("--require-signature")] = False,
) -> None:
    package_verify_command(package, public_key, require_signature)


@plugin_app.command("remove")
def plugin_remove_command(name: str) -> None:
    package_remove_command(name)


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
def runs_logs_command(
    run_id: str,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
) -> None:
    directory = resolve_run(run_id, project)
    found = False
    for path in sorted(directory.rglob("*.log")):
        found = True
        console.rule(str(path.relative_to(directory)))
        console.print(path.read_text(encoding="utf-8", errors="replace"))
    if not found:
        console.print("No separate log files were produced.")
        if (directory / "events.jsonl").is_file():
            console.print("Structured events are available in events.jsonl.")


@runs_app.command("compare")
def runs_compare_command(
    first: str,
    second: str,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    table_output: Annotated[bool, typer.Option("--table", help="Render the principal metrics as a table")] = False,
) -> None:
    comparison = compare_runs(first, second, project)
    if not table_output:
        console.print_json(json.dumps(comparison))
        return
    table = Table("Metric", "First", "Second", "Delta", "Change")
    for name, raw in dict(comparison.get("metrics", {})).items():
        item = dict(raw)
        percent = item.get("percent")
        table.add_row(
            name,
            f"{float(item.get('first', 0.0)):.3f}",
            f"{float(item.get('second', 0.0)):.3f}",
            f"{float(item.get('delta', 0.0)):+.3f}",
            "-" if percent is None else f"{float(percent):+.1f}%",
        )
    console.print(table)


@native_app.command("inspect")
def native_inspect_command(library: Annotated[Path, typer.Argument(exists=True, readable=True)]) -> None:
    """Inspect plugin ABI and mandatory exported symbols without creating a node."""
    try:
        lib = ctypes.CDLL(str(library.resolve()))
        abi_fn = lib.nodrix_plugin_abi_version_v2
        abi_fn.restype = ctypes.c_uint32
        abi = int(abi_fn())
        features = 0
        if hasattr(lib, "nodrix_plugin_features_v2"):
            features_fn = lib.nodrix_plugin_features_v2
            features_fn.restype = ctypes.c_uint64
            features = int(features_fn())
        symbols = {
            "nodrix_plugin_abi_version_v2": True,
            "nodrix_plugin_features_v2": hasattr(lib, "nodrix_plugin_features_v2"),
            "nodrix_plugin_create_v2": hasattr(lib, "nodrix_plugin_create_v2"),
        }
    except Exception as exc:
        console.print(f"[red]Cannot inspect plugin:[/red] {exc}")
        raise typer.Exit(1)
    runtime_abi = 0x00020000
    table = Table("Field", "Value")
    table.add_row("Plugin ABI", f"{abi >> 16}.{abi & 0xffff} ({abi})")
    table.add_row("Runtime ABI", "2.0 (131072)")
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
