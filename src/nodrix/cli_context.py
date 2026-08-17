from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .errors import NodrixError
from .manifest import load_manifest
from .hybrid_runtime import HybridPipelineRuntime
from .native_runtime import NativePipelineRuntime
from . import __version__
from .validation import validate_production
from .provider_cli import provider_app

app = typer.Typer(
    name="plyctl",
    help="Executable system architecture and operations for local and distributed systems.",
    no_args_is_help=False,
    invoke_without_command=True,
    rich_markup_mode=None,
)
node_app = typer.Typer(help="Inspect available node types.")
stream_app = typer.Typer(help="Discover, inspect, and subscribe to named streams.")
native_app = typer.Typer(help="Build and inspect the high-performance C++20 engine.")
type_app = typer.Typer(help="Inspect registered message contracts.")
media_app = typer.Typer(help="Probe, record, and relay media through FFmpeg.")
recording_app = typer.Typer(help="Inspect universal .ndrx recordings.")
data_app = typer.Typer(help="Inspect shared-memory and process data-plane capabilities.")
device_app = typer.Typer(help="Inspect DLPack, DMA-BUF, V4L2, CUDA and native device-I/O capabilities.")
package_app = typer.Typer(help="Build and manage local Plyctl packages.")
plugin_app = typer.Typer(help="Search, verify, install, inspect, and remove offline plugins.")
runs_app = typer.Typer(help="Inspect reproducible run artifacts.")
config_app = typer.Typer(help="Inspect resolved runtime presets and configuration values.")
block_app = typer.Typer(help="List and inspect reusable 2.x Pipeline YAML node blocks.")
fragment_app = typer.Typer(help="Create and validate reusable 2.x Pipeline typed subgraphs.")
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
    version: Annotated[bool, typer.Option("--version", help="Show the Plyctl version", is_eager=True)] = False,
) -> None:
    if version:
        console.print(f"Plyctl {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


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
            f"[bold]Plyctl {report['runtime']['plyctl']} doctor[/bold] "
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
            session_references=(
                session.uses for session in manifest.sessions.values()
            ),
            resource_references=(
                resource.uses for resource in manifest.resources.values()
            ),
            application_references=(
                application.uses
                for application in manifest.applications.values()
            ),
            transport_references=(
                edge.transport.uses
                for edge in manifest.edges
                if edge.transport is not None
            ),
            link_references=(link.uses for link in manifest.links),
        )
    native_only = bool(manifest.nodes) and all(
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

# Command modules use this explicit export list so shared private helpers remain
# available without duplicating CLI business logic.
