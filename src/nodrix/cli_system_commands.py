"""CLI commands for the canonical Nodrix System Model."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Annotated

from rich.table import Table
import typer

from .cli_context import app, console
from .local_dev import compile_local_project
from .manifest import load_manifest
from .sdk.definitions import MessageDefinition, NodeDefinition, ResourceDefinition
from .system import (
    DefinitionCatalog,
    dump_system,
    dump_system_schema,
    load_system,
    pipeline_manifest_to_system,
    system_to_canonical,
    validate_system,
)


system_app = typer.Typer(
    help="Validate, inspect, convert, and describe nodrix.system/v1 documents."
)
app.add_typer(system_app, name="system")


def _diagnostic_dict(item) -> dict[str, str]:
    return {
        "level": str(item.level),
        "code": str(item.code),
        "path": str(item.path),
        "message": str(item.message),
    }


def _catalog_for_project(path: Path) -> DefinitionCatalog:
    """Resolve neutral SDK definitions from one local/package project."""

    project = compile_local_project(path)

    nodes: dict[str, NodeDefinition] = {}
    resources: dict[str, ResourceDefinition] = {}
    messages: dict[str, MessageDefinition] = {}

    for cls in project.compiled.provider_runtime.nodes.values():
        definition = getattr(cls, "__plyctl_definition__", None)
        if isinstance(definition, NodeDefinition):
            nodes[definition.name] = definition

    for cls in project.compiled.provider_runtime.resources.values():
        definition = getattr(cls, "__plyctl_definition__", None)
        if isinstance(definition, ResourceDefinition):
            resources[definition.name] = definition

    # Package/local compilation imports the source modules into this process.
    # MessageDefinitions are intentionally read from decorator metadata rather
    # than reverse-engineered from Provider API 2 MessageContract objects.
    for module_name in project.module_names:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for value in vars(module).values():
            definition = getattr(value, "__plyctl_definition__", None)
            if isinstance(definition, MessageDefinition):
                messages[definition.type_id] = definition

    return DefinitionCatalog(
        nodes=nodes,
        resources=resources,
        messages=messages,
    )


@system_app.command("validate")
def system_validate(
    path: Annotated[
        Path,
        typer.Argument(help="System YAML/JSON document"),
    ],
    project: Annotated[
        Path | None,
        typer.Option(
            "--project",
            "-p",
            help="Optional local/package SDK project used for full contract validation",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON"),
    ] = False,
    warnings_as_errors: Annotated[
        bool,
        typer.Option(
            "--warnings-as-errors",
            help="Return a non-zero exit code when warnings are present",
        ),
    ] = False,
) -> None:
    """Validate a nodrix.system/v1 document.

    Without --project, structural System references are validated. With
    --project, Node/Resource/Message definitions are also resolved so parameter,
    port, message-version, and Resource[T] contracts can be checked.
    """

    try:
        system = load_system(path)
        catalog = _catalog_for_project(project) if project is not None else None
        report = validate_system(system, catalog=catalog)
    except Exception as exc:
        if json_output:
            console.print_json(
                json.dumps(
                    {
                        "ok": False,
                        "path": str(path),
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            console.print(f"[red]System validation failed:[/red] {exc}")
        raise typer.Exit(1)

    payload = {
        "ok": report.valid and not (warnings_as_errors and report.warnings),
        "path": str(path.expanduser().resolve()),
        "system": system.name,
        "catalog": project is not None,
        "errors": [_diagnostic_dict(item) for item in report.errors],
        "warnings": [_diagnostic_dict(item) for item in report.warnings],
    }

    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
    else:
        status = "VALID" if payload["ok"] else "INVALID"
        color = "green" if payload["ok"] else "red"
        mode = "definitions resolved" if project is not None else "structural"
        console.print(
            f"[{color}]{status}[/{color}] "
            f"[bold]{system.name}[/bold] · {mode}"
        )

        if report.diagnostics:
            table = Table(box=None, show_edge=False, pad_edge=False)
            table.add_column("LEVEL")
            table.add_column("CODE")
            table.add_column("PATH")
            table.add_column("MESSAGE")
            for item in report.diagnostics:
                style = "red" if item.level == "error" else "yellow"
                table.add_row(
                    item.level.upper(),
                    item.code,
                    item.path or "-",
                    item.message,
                    style=style,
                )
            console.print(table)
        else:
            console.print("No diagnostics.")

    if not payload["ok"]:
        raise typer.Exit(1)


@system_app.command("show")
def system_show(
    path: Annotated[
        Path,
        typer.Argument(help="System YAML/JSON document"),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print canonical System JSON"),
    ] = False,
    document: Annotated[
        bool,
        typer.Option("--document", help="Print canonical System YAML instead of a summary"),
    ] = False,
) -> None:
    """Show the canonical System document or a concise architecture summary."""

    if json_output and document:
        console.print("[red]Use either --json or --document, not both.[/red]")
        raise typer.Exit(2)

    try:
        system = load_system(path)
    except Exception as exc:
        console.print(f"[red]Cannot load System:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        console.print_json(
            json.dumps(
                system_to_canonical(system),
                ensure_ascii=False,
            )
        )
        return

    if document:
        from .system import dumps_system

        console.print(dumps_system(system, format="yaml").rstrip())
        return

    console.print(
        f"[bold]{system.name}[/bold] · {system.api_version} · {system.kind}"
    )
    if system.description:
        console.print(system.description)

    counts = Table(box=None, show_edge=False, pad_edge=False)
    counts.add_column("RESOURCES", justify="right")
    counts.add_column("APPLICATIONS", justify="right")
    counts.add_column("GRAPHS", justify="right")
    counts.add_column("LINKS", justify="right")
    counts.add_column("TARGETS", justify="right")
    counts.add_column("ARTIFACTS", justify="right")
    counts.add_row(
        str(len(system.resources)),
        str(len(system.applications)),
        str(len(system.graphs)),
        str(len(system.links)),
        str(len(system.targets)),
        str(len(system.artifacts)),
    )
    console.print(counts)

    if system.graphs:
        graphs = Table(box=None, show_edge=False, pad_edge=False)
        graphs.add_column("GRAPH")
        graphs.add_column("NODES", justify="right")
        graphs.add_column("CONNECTIONS", justify="right")
        for graph in system.graphs:
            graphs.add_row(
                graph.name,
                str(len(graph.nodes)),
                str(len(graph.connections)),
            )
        console.print(graphs)

    if system.targets:
        targets = Table(box=None, show_edge=False, pad_edge=False)
        targets.add_column("TARGET")
        targets.add_column("KIND")
        for target in system.targets:
            targets.add_row(target.name, target.kind)
        console.print(targets)

    if system.artifacts:
        artifacts = Table(box=None, show_edge=False, pad_edge=False)
        artifacts.add_column("ARTIFACT")
        artifacts.add_column("KIND")
        artifacts.add_column("PRODUCER")
        for artifact in system.artifacts:
            artifacts.add_row(
                artifact.name,
                artifact.kind,
                artifact.producer or "-",
            )
        console.print(artifacts)


def _default_system_output(pipeline: Path) -> Path:
    pipeline = pipeline.expanduser().resolve()
    suffix = pipeline.suffix.lower()
    if suffix in {".yaml", ".yml", ".json"}:
        return pipeline.with_name(f"{pipeline.stem}.system.yaml")
    return pipeline.with_name(f"{pipeline.name}.system.yaml")


@system_app.command("convert")
def system_convert(
    pipeline: Annotated[
        Path,
        typer.Argument(help="Legacy 2.x Pipeline manifest"),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Destination System file; defaults to <pipeline>.system.yaml",
        ),
    ] = None,
    graph_name: Annotated[
        str,
        typer.Option("--graph-name", help="Graph name used for the legacy Pipeline"),
    ] = "main",
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing output file"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable conversion summary"),
    ] = False,
) -> None:
    """Convert a legacy PipelineManifest into nodrix.system/v1."""

    pipeline_path = pipeline.expanduser().resolve()
    destination = (
        output.expanduser().resolve()
        if output is not None
        else _default_system_output(pipeline_path)
    )

    if destination.exists() and not force:
        message = (
            f"output already exists: {destination}; pass --force to overwrite"
        )
        if json_output:
            console.print_json(
                json.dumps({"ok": False, "error": message}, ensure_ascii=False)
            )
        else:
            console.print(f"[red]Conversion failed:[/red] {message}")
        raise typer.Exit(1)

    try:
        manifest = load_manifest(pipeline_path)
        converted = pipeline_manifest_to_system(
            manifest,
            graph_name=graph_name,
        )
        dump_system(converted.system, destination)
    except Exception as exc:
        if json_output:
            console.print_json(
                json.dumps(
                    {
                        "ok": False,
                        "pipeline": str(pipeline_path),
                        "output": str(destination),
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            console.print(f"[red]Conversion failed:[/red] {exc}")
        raise typer.Exit(1)

    payload = {
        "ok": True,
        "pipeline": str(pipeline_path),
        "output": str(destination),
        "system": converted.system.name,
        "lossless": converted.lossless,
        "reversible": converted.reversible,
        "counts": converted.report.counts,
        "warnings": [
            {"code": item.code, "message": item.message}
            for item in converted.warnings
        ],
    }

    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    color = "green" if converted.lossless else "yellow"
    console.print(
        f"[{color}]Converted[/{color}] {pipeline_path.name} "
        f"→ [bold]{destination}[/bold]"
    )
    console.print(
        "Compatibility: "
        f"lossless={converted.lossless} "
        f"reversible={converted.reversible} · "
        f"transformed={converted.report.counts['transformed']} "
        f"deferred={converted.report.counts['deferred']} "
        f"unsupported={converted.report.counts['unsupported']}"
    )
    for warning in converted.warnings:
        console.print(f"[yellow]{warning.code}[/yellow] {warning.message}")


@system_app.command("schema")
def system_schema(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write schema to this path"),
    ] = None,
) -> None:
    """Print or write the JSON Schema for nodrix.system/v1."""

    try:
        if output is not None:
            destination = output.expanduser().resolve()
            dump_system_schema(destination)
            console.print(f"[green]Written[/green] {destination}")
            return

        from .system import system_json_schema

        console.print_json(
            json.dumps(
                system_json_schema(),
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        console.print(f"[red]Cannot produce System schema:[/red] {exc}")
        raise typer.Exit(1)
