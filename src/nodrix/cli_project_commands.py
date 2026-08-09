from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
from typing import Annotated

from rich.live import Live
from rich.table import Table
import typer
import yaml

from . import __version__
from .benchmarking import replay_plan
from .cli_context import _format_bytes, _runtime, app, console
from .errors import NodrixError
from .execution_plan import compile_execution_plan, write_execution_plan
from .hybrid_runtime import HybridPipelineRuntime
from .manifest import load_manifest_details
from .manifest_schema import write_manifest_schema
from .metrics import MetricsServer
from .migration import migrate_manifest
from .project_templates import TEMPLATES, create_project
from .presentation import render_run_active_info, render_run_summary
from .runs import resolve_run
from .ux import (
    render_node_details,
    render_pipeline_graph,
    render_runtime_event,
    render_startup_summary,
)
from .validation import ValidationIssue, validate_production
from .lockfile import verify_lock

def _effective_run_root(value: Path | None) -> Path:
    # Run artifacts belong to the project that invoked Plyctl.
    selected = value or (Path.cwd() / ".nodrix" / "runs")
    return selected.expanduser().resolve()


def _format_node_memory(stats: dict[str, object]) -> str:
    resources = dict(stats.get("resources", {}))
    value = (
        resources.get("rss_bytes")
        or resources.get("shared_buffer_bytes")
        or resources.get("executor_rss_bytes")
    )
    rendered = _format_bytes(value)
    if rendered != "-" and resources.get("scope") == "executor_shared":
        return f"{rendered} shared"
    return rendered



@app.command()
def init(
    directory: Annotated[Path, typer.Argument(help="Directory for a new Plyctl project")] = Path("plyctl-project"),
    template: Annotated[str | None, typer.Option("--template", "-t", help="Built-in or installed provider template id")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite generated files")] = False,
) -> None:
    """Create an empty project skeleton, or a runnable project from a template."""
    from .providers import create_provider_project, provider_template_ids

    selected = template.lower() if template else None
    provider_templates = (
        ()
        if selected is None or selected in TEMPLATES
        else provider_template_ids()
    )
    available = tuple(sorted(set(TEMPLATES) | set(provider_templates)))
    if selected is not None and selected not in available:
        raise typer.BadParameter(
            f"Unknown template {selected!r}; choose: {', '.join(available)}"
        )
    try:
        if selected in provider_templates:
            created = create_provider_project(
                directory,
                selected,
                force=force,
            )
        else:
            created = create_project(directory, selected, force=force)
    except (FileExistsError, OSError, ValueError, NodrixError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    label = f"{selected} template" if selected else "empty skeleton"
    console.print(f"[green]Created[/green] {directory.resolve()} ({label}, {len(created)} files)")
    if selected == "package":
        console.print("Build: [bold]cd %s && plyctl package build .[/bold]" % directory)
    elif selected:
        console.print("Run: [bold]cd %s && plyctl validate && plyctl run[/bold]" % directory)
    else:
        console.print("Add nodes to pipeline.yaml, or create a runnable example with: "
                      f"[bold]plyctl init {directory} --template vision --force[/bold]")


def _manifest_graph_counts(manifest) -> dict[str, int]:
    internal_edges = sum(
        1 for edge in manifest.edges if edge.transport is None
    )
    transported_edges = sum(
        1 for edge in manifest.edges if edge.transport is not None
    )
    external_edges = transported_edges + len(manifest.links)

    return {
        "nodes": len(manifest.nodes),
        "data_plane_edges": internal_edges,
        "external_edges": external_edges,
        "applications": len(manifest.applications),
        "total_edges": internal_edges + external_edges,
    }


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
        details = load_manifest_details(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        issues.extend(
            ValidationIssue(
                severity=(
                    "error"
                    if strict or production
                    else diagnostic.severity
                ),
                code=diagnostic.code,
                message=diagnostic.message,
                location=diagnostic.location,
            )
            for diagnostic in details.diagnostics
        )
    except Exception as exc:
        if json_output:
            console.print_json(json.dumps({"valid": False, "error": str(exc), "issues": []}))
        else:
            console.print(f"[red]Invalid:[/red] {exc}")
        raise typer.Exit(1)
    failed = any(item.severity == "error" for item in issues)
    counts = _manifest_graph_counts(details.manifest)
    if json_output:
        console.print_json(json.dumps({
            "valid": not failed,
            "pipeline": desc["name"],
            **counts,
            "issues": [item.as_dict() for item in issues],
        }))
    else:
        console.print(
            f"[{'red' if failed else 'green'}]{'Invalid' if failed else 'Valid'}[/{'red' if failed else 'green'}] "
            f"{desc['name']}: {counts['nodes']} nodes, "
            f"{counts['data_plane_edges']} data edges, "
            f"{counts['external_edges']} external edges, "
            f"{counts['applications']} applications"
        )
        if issues:
            table = Table("Severity", "Code", "Location", "Message")
            for item in issues:
                table.add_row(item.severity, item.code, item.location or "-", item.message)
            console.print(table)
    if failed:
        raise typer.Exit(1)


@app.command("schema")
def schema_command(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Destination for the canonical pipeline JSON Schema",
        ),
    ] = Path(".plyctl-schema.json"),
) -> None:
    """Write the canonical Plyctl pipeline JSON Schema for editor tooling."""

    try:
        destination = write_manifest_schema(output)
    except Exception as exc:
        console.print(f"[red]Schema generation failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Written[/green] {destination}")


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
    pipeline: Annotated[str | None, typer.Argument(help="Pipeline path or workspace alias")] = None,
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
    from .workspace import (
        activate_workspace_environment,
        resolve_pipeline_reference,
    )

    workspace = resolve_pipeline_reference(pipeline)
    pipeline = workspace.pipeline
    activate_workspace_environment(workspace)
    if run_root is None:
        run_root = workspace.root / ".nodrix" / "runs"
    if profile is None:
        profile = workspace.runtime_profile

    effective_run_root = _effective_run_root(run_root)
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
            rendered = render_runtime_event(event, indexes, len(indexes))
            if rendered.plain:
                console.print(rendered)
            if (
                not json_output
                and str(event.get("kind", "")) == "pipeline_running"
            ):
                console.print(
                    render_run_active_info(
                        effective_run_root,
                        monitor_command="plyctl top",
                    )
                )

        if production:
            runtime = _runtime(
                pipeline,
                run_root=effective_run_root,
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
        console.print(render_startup_summary(details.manifest, __version__, workspace=workspace))
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
                run_root=effective_run_root,
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
        console.print(render_run_summary(report))


@app.command()
def record(
    streams: Annotated[list[str], typer.Argument(help="One or more named streams or nodrix:// URIs")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Output .ndrx file")] = Path("recording.ndrx"),
    duration: Annotated[float, typer.Option("--duration", min=0.0, help="Stop after N seconds; 0 disables")] = 0.0,
    count: Annotated[int, typer.Option("--count", min=0, help="Stop after N total messages; 0 disables")] = 0,
) -> None:
    """Record any typed Plyctl streams into one indexed .ndrx file."""
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
    """Replay an .ndrx recording as discoverable Plyctl streams."""
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
    write: Annotated[
        bool,
        typer.Option(
            "--write",
            help="Canonicalize the source in place and create a backup",
        ),
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show changes without writing")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Migrate a 1.x manifest to stable v2 without overwriting it by default."""
    if target_version != "v2":
        console.print(f"[red]Unsupported migration target:[/red] {target_version}")
        raise typer.Exit(2)
    try:
        if write and (in_place or output is not None):
            raise ValueError("--write cannot be combined with --in-place or --output")
        result = migrate_manifest(
            pipeline,
            output=output,
            in_place=in_place or write,
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
