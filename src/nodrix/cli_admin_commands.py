from __future__ import annotations

import ctypes
import json
from pathlib import Path
import time
from typing import Annotated

from rich.live import Live
from rich.table import Table
import typer
import yaml

from .cli_context import (
    _config_value,
    _format_bytes,
    app,
    config_app,
    console,
    native_app,
    package_app,
    plugin_app,
    runs_app,
)
from .lockfile import verify_lock, write_lock
from .manifest import canonical_config_path, load_manifest_details
from .metrics import prometheus_text
from .packages import (
    build_package,
    install_package,
    list_packages,
    package_info,
    remove_package,
    verify_package,
)
from .profiles import profile_names
from .workspace import default_view, resolve_project_root
from .workspace_views import render_top_view
from .presentation import render_health, render_status
from .runs import (
    compare_runs,
    latest_run_id,
    list_runs,
    load_run,
    resolve_run,
    run_root,
)


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

def _format_status_memory(
    resources: dict[str, object],
    value: object,
) -> str:
    rendered = _format_bytes(value)
    if rendered != "-" and resources.get("scope") == "executor_shared":
        return f"{rendered} shared"
    return rendered


def _run_unavailable(
    label: str,
    project: Path,
    error: BaseException,
) -> None:
    typer.echo(f"{label} unavailable: {error}")
    typer.echo(f"Run root: {run_root(project)}")
    typer.echo("Start one with: plyctl run pipeline.yaml")
    raise typer.Exit(1)



@app.command("status")
def status_command(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the latest live status snapshot or final run summary."""
    project = resolve_project_root(project)
    try:
        selected = run_id or _latest_run_id(project)
        data = load_run(selected, project)
    except Exception as exc:
        _run_unavailable("Status", project, exc)
    if json_output:
        console.print_json(json.dumps(data))
        return
    console.print(render_status(data, run_id=selected))


@app.command("health")
def health_command(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    watch: Annotated[bool, typer.Option("--watch")] = False,
    interval: Annotated[float, typer.Option("--interval", min=0.1)] = 1.0,
) -> None:
    """Show node readiness and health; optionally watch a running pipeline."""
    project = resolve_project_root(project)
    while True:
        try:
            selected = run_id or _latest_run_id(project)
            data = load_run(selected, project)
        except Exception as exc:
            _run_unavailable("Health", project, exc)
        console.clear() if watch else None
        console.print(render_health(data))
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
    project = resolve_project_root(project)
    try:
        selected = run_id or _latest_run_id(project)
        data = load_run(selected, project)
    except Exception as exc:
        _run_unavailable("Metrics", project, exc)
    if format_name == "json":
        console.print_json(json.dumps(data))
    elif format_name == "prometheus":
        console.print(prometheus_text(data), markup=False, end="")
    else:
        raise typer.BadParameter("--format must be json or prometheus")


def _top_table(
    data: dict[str, object],
    *,
    view: str,
    project: Path | None = None,
):
    return render_top_view(data, view, project=project)


@app.command("top")
def top_command(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    project: Annotated[Path, typer.Option("--project", "-p")] = Path.cwd(),
    watch: Annotated[bool, typer.Option("--watch/--once")] = True,
    interval: Annotated[float, typer.Option("--interval", min=0.1)] = 1.0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    view: Annotated[str | None, typer.Option("--view", help="Workspace view name; built-ins: overview, performance, operations, debug (compact aliases overview)")] = None,
) -> None:
    "Show a semantic, borderless runtime dashboard."
    project = resolve_project_root(project)
    selected_view = view or default_view(project)

    def snapshot() -> dict[str, object]:
        # Explicit --run pins the dashboard. Otherwise follow the active run.
        selected = run_id or _latest_run_id(project)
        return load_run(selected, project)

    try:
        data = snapshot()
    except Exception as exc:
        _run_unavailable("Top", project, exc)
    if json_output:
        console.print_json(json.dumps(data))
        return
    if not watch or not console.is_terminal:
        console.print(_top_table(data, view=selected_view, project=project))
        return

    with Live(
        _top_table(data, view=selected_view, project=project),
        console=console,
        refresh_per_second=max(2, int(1.0 / interval)),
        screen=True,
        transient=True,
    ) as live_view:
        try:
            while True:
                time.sleep(interval)
                live_view.update(
                    _top_table(snapshot(), view=selected_view, project=project),
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


def _run_subject_label(item: dict[str, object]) -> str:
    """Return the primary human-readable subject of one indexed Run."""

    subject = item.get("subject")
    if isinstance(subject, str) and subject:
        prefix = "nodrix://"
        return subject[len(prefix):] if subject.startswith(prefix) else subject

    pipeline = item.get("pipeline")
    if isinstance(pipeline, str) and pipeline:
        return pipeline

    return "-"


def _run_operation_label(item: dict[str, object]) -> str:
    """Return a canonical Operation name or '-' for legacy Runs."""

    operation = item.get("operation")
    if isinstance(operation, str) and operation:
        return operation

    return "-"


def _run_subject_label(item: dict[str, object]) -> str:
    """Return the primary human-readable subject of one indexed Run."""

    subject = item.get("subject")
    if isinstance(subject, str) and subject:
        prefix = "nodrix://"
        if subject.startswith(prefix):
            return subject[len(prefix):]
        return subject

    pipeline = item.get("pipeline")
    if isinstance(pipeline, str) and pipeline:
        return pipeline

    return "-"


def _run_operation_label(item: dict[str, object]) -> str:
    """Return a canonical Operation name or '-' for legacy Runs."""

    operation = item.get("operation")
    if isinstance(operation, str) and operation:
        return operation

    return "-"


@runs_app.command("list")
def runs_list_command(
    project: Annotated[
        Path,
        typer.Option("--project", "-p"),
    ] = Path.cwd(),
    json_output: Annotated[
        bool,
        typer.Option("--json"),
    ] = False,
) -> None:
    """List legacy and canonical execution history."""

    items = list_runs(project)

    if json_output:
        console.print_json(
            json.dumps(
                items,
                ensure_ascii=False,
            )
        )
        return

    table = Table(
        box=None,
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("Run")
    table.add_column("Operation")
    table.add_column("Subject / Pipeline")
    table.add_column("Status")
    table.add_column("Seconds")

    for item in items:
        duration = item.get("duration_seconds")

        table.add_row(
            str(item["id"]),
            _run_operation_label(item),
            _run_subject_label(item),
            str(item["status"]),
            (
                "-"
                if duration is None
                else str(duration)
            ),
        )

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
