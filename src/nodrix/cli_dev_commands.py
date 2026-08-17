"""Local development commands for typing-first SDK components."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from .cli_context import _runtime, app, console
from .local_dev import activate_local_project, compile_local_project


dev_app = typer.Typer(
    help="Discover, inspect, and run local typing-first SDK components.",
)
app.add_typer(dev_app, name="dev")


def _pipeline_for(path: Path, root: Path) -> Path | None:
    candidate = path.expanduser().resolve()
    if candidate.is_file() and candidate.name != "nodrix.yaml":
        return candidate
    default = root / "pipeline.yaml"
    return default if default.is_file() else None


def _summary(project) -> dict[str, object]:
    manifest = project.compiled.provider_manifest
    return {
        "root": str(project.root),
        "namespace": project.namespace,
        "mode": "package" if project.package_mode else "local",
        "modules": list(project.module_names),
        "nodes": [item.id for item in manifest.nodes],
        "resources": [item.id for item in manifest.resources],
        "messages": [item.id for item in project.compiled.messages],
    }


@app.command("check")
def check_command(
    path: Annotated[
        Path,
        typer.Argument(help="Project directory, nodrix.yaml, or pipeline.yaml"),
    ] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Compile local SDK metadata and validate an adjacent pipeline when present."""

    try:
        project = compile_local_project(path)
        pipeline = _pipeline_for(path, project.root)
        pipeline_description = None
        if pipeline is not None:
            with activate_local_project(project):
                pipeline_description = _runtime(pipeline, production=False).describe()
        payload = _summary(project)
        payload["pipeline"] = pipeline_description
    except Exception as exc:
        if json_output:
            console.print_json(json.dumps({"ok": False, "error": str(exc)}))
        else:
            console.print(f"[red]Check failed:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        console.print_json(json.dumps({"ok": True, **payload}))
        return
    console.print(
        f"[green]OK[/green] {project.namespace}: "
        f"{len(payload['nodes'])} nodes, "
        f"{len(payload['resources'])} resources, "
        f"{len(payload['messages'])} messages"
    )
    if pipeline_description is not None:
        console.print(
            f"Pipeline [bold]{pipeline_description['name']}[/bold] is resolvable "
            "with local components."
        )


@dev_app.command("inspect")
def inspect_local_command(
    path: Annotated[
        Path,
        typer.Argument(help="Project directory or nodrix.yaml"),
    ] = Path("."),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show decorators discovered from a package or local components directory."""

    try:
        project = compile_local_project(path)
    except Exception as exc:
        console.print(f"[red]Inspection failed:[/red] {exc}")
        raise typer.Exit(1)
    payload = _summary(project)
    if json_output:
        console.print_json(json.dumps(payload))
        return

    console.print(
        f"Project {project.root} · namespace [bold]{project.namespace}[/bold] · "
        f"{'package' if project.package_mode else 'local components'}"
    )
    table = Table("Kind", "ID", "Inputs", "Outputs/Factory")
    for item in project.compiled.provider_manifest.nodes:
        table.add_row(
            "node",
            item.id,
            ", ".join(item.inputs) or "-",
            ", ".join(item.outputs) or item.factory,
        )
    for item in project.compiled.provider_manifest.resources:
        table.add_row("resource", item.id, "-", item.factory)
    for item in project.compiled.messages:
        table.add_row("message", item.id, "-", item.python_ref)
    console.print(table)


@dev_app.command("run")
def run_local_command(
    pipeline: Annotated[
        Path,
        typer.Argument(help="Pipeline using local/package SDK component ids"),
    ] = Path("pipeline.yaml"),
    run_root: Annotated[
        Path | None,
        typer.Option("--run-root", help="Directory for run artifacts"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the complete run report as JSON"),
    ] = False,
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="Override the 2.x Pipeline RuntimePreset (compatibility option --profile)"),
    ] = None,
    set_values: Annotated[
        list[str] | None,
        typer.Option("--set", help="Override a resolved value: path=value"),
    ] = None,
) -> None:
    """Run a pipeline with transient local SDK providers enabled."""

    from .cli_project_commands import run as run_pipeline

    pipeline = pipeline.expanduser().resolve()
    try:
        project = compile_local_project(pipeline.parent)
    except Exception as exc:
        console.print(f"[red]Local discovery failed:[/red] {exc}")
        raise typer.Exit(1)
    with activate_local_project(project):
        run_pipeline(
            pipeline=str(pipeline),
            run_root=run_root,
            json_output=json_output,
            locked=False,
            metrics_listen=None,
            profile=profile,
            set_values=set_values,
            block_values=None,
            production=False,
        )
