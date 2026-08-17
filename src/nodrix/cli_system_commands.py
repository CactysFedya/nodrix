"""CLI commands for the canonical Nodrix System Model."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Annotated

from rich.table import Table
import typer
import yaml

from .cli_context import app, console
from .local_dev import compile_local_project, reset_local_development_modules
from .manifest import load_manifest
from .presentation import render_system_plan as render_system_plan_view, render_validation
from .project_foundation import resolve_project_resource
from .project_system import (
    load_project_system_details,
    system_execution_context_from_project,
)
from .workspace import (
    find_workspace,
    resolve_project_execution_context,
)
from .sdk.definitions import MessageDefinition, NodeDefinition, ResourceDefinition
from .system import (
    BackendExecutionState,
    DefinitionCatalog,
    LocalBackend,
    dump_system,
    dump_system_schema,
    load_system,
    load_system_details,
    pipeline_manifest_to_system,
    plan_system,
    validate_system,
)


system_app = typer.Typer(
    help="Validate, inspect, plan, run, convert, and describe nodrix.system/v1 documents."
)
app.add_typer(system_app, name="system")


def _project_has_local_components(root: Path) -> bool:
    project_file = root / "nodrix.yaml"
    try:
        project = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(project, dict) or project.get("schema") != "nodrix.project/v1":
        return False
    components = root / "components"
    return components.is_dir() and any(
        path.is_file() and "__pycache__" not in path.parts
        for path in components.rglob("*.py")
    )


def _resolve_system_cli_inputs(
    path: Path | None,
    project: Path | None = None,
) -> tuple[Path, Path | None]:
    """Resolve an explicit System or the project's default registered System."""

    project_root: Path | None = None
    if path is None:
        resource = resolve_project_resource(
            "system",
            root=project if project is not None else Path.cwd(),
        )
        resolved_path = resource.path.resolve()
        project_root = resource.project_file.parent.resolve()
    else:
        resolved_path = path.expanduser().resolve()
        project_root = find_workspace(resolved_path.parent)

    effective_project = project.expanduser().resolve() if project is not None else None
    if (
        effective_project is None
        and project_root is not None
        and _project_has_local_components(project_root)
    ):
        effective_project = project_root
    return resolved_path, effective_project


def _load_system_cli_details(
    path: Path,
    *,
    profile: str | None = None,
):
    """Load one System with an optional explicit project Profile."""

    if profile is None:
        return load_system_details(
            path
        )

    project_root = find_workspace(
        path.parent
    )

    if project_root is None:
        raise LookupError(
            "--profile requires the System to belong to "
            "a Nodrix project containing nodrix.yaml"
        )

    return load_project_system_details(
        path,
        profile=profile,
        root=project_root,
    )


def _load_system_cli_planning_inputs(
    path: Path,
    *,
    profile: str | None = None,
):
    """Resolve System semantics and an optional explicit execution context."""

    details = _load_system_cli_details(
        path,
        profile=profile,
    )

    if profile is None:
        return details, None

    project_root = find_workspace(
        path.parent
    )

    if project_root is None:
        raise LookupError(
            "--profile requires the System to belong to "
            "a Nodrix project containing nodrix.yaml"
        )

    project_context = (
        resolve_project_execution_context(
            project_root,
            profile=profile,
        )
    )

    return (
        details,
        system_execution_context_from_project(
            project_context
        ),
    )


def _diagnostic_dict(item) -> dict[str, str]:
    return {
        "level": str(item.level),
        "code": str(item.code),
        "path": str(item.path),
        "message": str(item.message),
    }


def _resolution_payload(details) -> dict[str, object]:
    """Return machine-readable System authoring resolution diagnostics."""

    resolution = details.resolution

    return {
        "source": str(details.path),
        "sources": [
            str(path)
            for path in resolution.sources
        ],
        "moduleSources": [
            str(path)
            for path in resolution.module_sources
        ],
        "configSources": [
            str(path)
            for path in resolution.config_sources
        ],
        "configOverlaySources": [
            str(path)
            for path in resolution.config_overlay_sources
        ],
        "configProvenance": {
            key: str(value)
            for key, value in sorted(
                resolution.config_provenance.items()
            )
        },
    }


def _resolution_display_path(
    path: Path,
    *,
    root: Path,
) -> str:
    """Prefer paths relative to the root System source."""

    try:
        return str(
            path.relative_to(root)
        )
    except ValueError:
        return str(path)


def _render_system_resolution(details) -> None:
    """Render authoring sources without changing canonical System output."""

    resolution = details.resolution
    root = details.path.parent

    console.print()
    console.print("[bold]Resolution[/bold]")

    sources = Table(
        box=None,
        show_edge=False,
        pad_edge=False,
    )
    sources.add_column("TYPE")
    sources.add_column("SOURCE")

    sources.add_row(
        "SYSTEM",
        _resolution_display_path(
            details.path,
            root=root,
        ),
    )

    for source in resolution.module_sources:
        sources.add_row(
            "MODULE",
            _resolution_display_path(
                source,
                root=root,
            ),
        )

    for source in resolution.config_sources:
        sources.add_row(
            "CONFIG",
            _resolution_display_path(
                source,
                root=root,
            ),
        )

    for source in resolution.config_overlay_sources:
        sources.add_row(
            "CONFIG OVERLAY",
            _resolution_display_path(
                source,
                root=root,
            ),
        )

    console.print(sources)

    if resolution.config_provenance:
        provenance = Table(
            box=None,
            show_edge=False,
            pad_edge=False,
        )
        provenance.add_column("CONFIG PATH")
        provenance.add_column("SOURCE")

        for config_path, source in sorted(
            resolution.config_provenance.items()
        ):
            provenance.add_row(
                config_path,
                _resolution_display_path(
                    source,
                    root=root,
                ),
            )

        console.print(provenance)


def _catalog_for_project(path: Path) -> DefinitionCatalog:
    """Resolve neutral SDK definitions without leaking local modules.

    Typer's CliRunner executes multiple CLI invocations in one Python process
    during tests and embedding. Implicit local projects all use module names
    such as ``components.nodes``. Always reset the reserved local-development
    module set before and after compilation so one project cannot poison the
    next command.
    """

    reset_local_development_modules()
    try:
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

        # Read MessageDefinitions while the compiled modules are still
        # available; the Definition objects remain valid after cleanup.
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
    finally:
        reset_local_development_modules()


@system_app.command("validate")
def system_validate(
    path: Annotated[
        Path | None,
        typer.Argument(help="System YAML/JSON document"),
    ] = None,
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
        resolved_path, effective_project = _resolve_system_cli_inputs(
            path,
            project,
        )
        system = load_system(
            resolved_path
        )
        catalog = (
            _catalog_for_project(effective_project)
            if effective_project is not None
            else None
        )
        report = validate_system(system, catalog=catalog)
    except Exception as exc:
        if json_output:
            console.print_json(
                json.dumps(
                    {
                        "ok": False,
                        "path": str(path) if path is not None else "<project-default>",
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
        "path": str(resolved_path),
        "system": system.name,
        "catalog": effective_project is not None,
        "errors": [_diagnostic_dict(item) for item in report.errors],
        "warnings": [_diagnostic_dict(item) for item in report.warnings],
    }

    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
    else:
        mode = "definitions resolved" if project is not None else "structural"
        console.print(
            render_validation(
                name=system.name,
                valid=bool(payload["ok"]),
                mode=mode,
                diagnostics=report.diagnostics,
                noun="SYSTEM",
            )
        )

    if not payload["ok"]:
        raise typer.Exit(1)


def _plan_backend_names(plan) -> tuple[str, ...]:
    names: list[str] = []

    def add(value: str | None) -> None:
        if value and value not in names:
            names.append(value)

    for target in plan.targets:
        add(target.backend)
    for resource in plan.resources:
        add(resource.backend)
    for application in plan.applications:
        add(application.backend)
    for graph in plan.graphs:
        for backend in graph.backends:
            add(backend)
    for link in plan.links:
        add(link.source_backend)
        add(link.target_backend)
    for artifact in plan.artifacts:
        add(artifact.backend)
    return tuple(names)


def _plan_jsonable(plan) -> dict:
    return plan.model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
    )


def _render_system_plan(plan) -> None:
    console.print(render_system_plan_view(plan))


@system_app.command("plan")
def system_plan(
    path: Annotated[
        Path | None,
        typer.Argument(help="System YAML/JSON document"),
    ] = None,
    project: Annotated[
        Path | None,
        typer.Option(
            "--project",
            "-p",
            help="Optional local/package SDK project used to resolve typed definitions",
        ),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help=(
                "Project Profile (nodrix.profile/v1) used for System Config "
                "and execution context; not a RuntimePreset"
            ),
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable execution plan JSON"),
    ] = False,
    warnings_as_errors: Annotated[
        bool,
        typer.Option(
            "--warnings-as-errors",
            help="Return a non-zero exit code when planner warnings are present",
        ),
    ] = False,
) -> None:
    """Resolve a System document into nodrix.system-execution-plan/v1."""

    try:
        resolved_path, effective_project = _resolve_system_cli_inputs(
            path,
            project,
        )
        details, execution_context = (
            _load_system_cli_planning_inputs(
                resolved_path,
                profile=profile,
            )
        )
        system = details.system
        catalog = (
            _catalog_for_project(effective_project)
            if effective_project is not None
            else None
        )
        plan = plan_system(
            system,
            catalog=catalog,
            execution_context=execution_context,
        )
    except Exception as exc:
        if json_output:
            console.print_json(
                json.dumps(
                    {
                        "ok": False,
                        "path": str(path) if path is not None else "<project-default>",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            console.print(f"[red]System planning failed:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        console.print_json(
            json.dumps(
                _plan_jsonable(plan),
                ensure_ascii=False,
            )
        )
    else:
        _render_system_plan(plan)

    if warnings_as_errors and plan.diagnostics:
        raise typer.Exit(1)


def _render_backend_validation(report) -> None:
    if not report.diagnostics:
        return

    table = Table(
        title=f"BACKEND {report.backend.upper()} DIAGNOSTICS",
        box=None,
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("LEVEL")
    table.add_column("CODE")
    table.add_column("PATH")
    table.add_column("MESSAGE")
    for item in report.diagnostics:
        table.add_row(
            item.level.upper(),
            item.code,
            item.path or "-",
            item.message,
            style="red" if item.level == "error" else "yellow",
        )
    console.print(table)


def _render_run_status(system_name: str, status) -> None:
    state = status.state.value.upper()
    color = (
        "green"
        if status.state in {
            BackendExecutionState.COMPLETED,
            BackendExecutionState.STOPPED,
        }
        else "red"
        if status.state is BackendExecutionState.FAILED
        else "yellow"
    )
    suffix = f" · {status.message}" if status.message else ""
    console.print(
        f"[{color}]{state}[/{color}] "
        f"[bold]{system_name}[/bold] · "
        f"{status.backend}:{status.execution_id}{suffix}"
    )


@system_app.command("run")
def system_run(
    path: Annotated[
        Path | None,
        typer.Argument(help="System YAML/JSON document"),
    ] = None,
    project: Annotated[
        Path | None,
        typer.Option(
            "--project",
            "-p",
            help=(
                "Optional local/package SDK project used for typed "
                "definitions and execution"
            ),
        ),
    ] = None,
    run_root: Annotated[
        Path | None,
        typer.Option(
            "--run-root",
            help="Optional runtime output root passed to the LocalBackend",
        ),
    ] = None,
    stop_timeout: Annotated[
        float,
        typer.Option(
            "--stop-timeout",
            min=0.0,
            help="Seconds to wait for a local runtime to stop after Ctrl+C",
        ),
    ] = 10.0,
    warnings_as_errors: Annotated[
        bool,
        typer.Option(
            "--warnings-as-errors",
            help="Refuse execution when planner warnings are present",
        ),
    ] = False,
) -> None:
    """Plan and execute a System through the local execution backend.

    Nodrix 2.6 intentionally runs one backend scope here. Systems that resolve
    to non-local or multiple backends are rejected until a multi-backend
    orchestrator is introduced.
    """

    try:
        resolved_path, effective_project = _resolve_system_cli_inputs(path, project)
        system = load_system(resolved_path)
        catalog = (
            _catalog_for_project(effective_project)
            if effective_project is not None
            else None
        )
        plan = plan_system(system, catalog=catalog)
    except Exception as exc:
        console.print(f"[red]System run failed:[/red] {exc}")
        raise typer.Exit(1)

    backend_names = _plan_backend_names(plan)
    if backend_names != ("local",):
        found = ", ".join(backend_names) if backend_names else "<none>"
        console.print(
            "[red]System run failed:[/red] "
            "RUN101: Nodrix 2.6 system run supports exactly one 'local' "
            f"backend; plan resolves to: {found}"
        )
        raise typer.Exit(1)

    if warnings_as_errors and plan.diagnostics:
        console.print(
            "[red]System run refused:[/red] "
            "RUN102: planner warnings are present and "
            "--warnings-as-errors was set"
        )
        _render_system_plan(plan)
        raise typer.Exit(1)

    if plan.diagnostics:
        console.print(
            f"[yellow]Planner warnings:[/yellow] {len(plan.diagnostics)}"
        )
        for item in plan.diagnostics:
            console.print(
                f"[yellow]{item.code}[/yellow] "
                f"{item.path or '-'} · {item.message}"
            )

    execution_root = find_workspace(resolved_path.parent) or resolved_path.parent
    backend = LocalBackend(
        project=effective_project,
        working_directory=execution_root,
        run_root=run_root,
        stop_timeout_seconds=stop_timeout,
    )

    report = backend.validate_plan(plan)
    if report.diagnostics:
        _render_backend_validation(report)

    if not report.valid:
        console.print(
            "[red]System run failed:[/red] "
            "RUN103: LocalBackend rejected the execution plan"
        )
        raise typer.Exit(1)

    try:
        prepared = backend.prepare_plan(plan)
    except Exception as exc:
        console.print(f"[red]System prepare failed:[/red] {exc}")
        raise typer.Exit(1)

    manifest_path = prepared.metadata.get("manifest_path")
    console.print(
        f"[green]PREPARED[/green] [bold]{system.name}[/bold] · backend=local"
        + (f" · {manifest_path}" if manifest_path else "")
    )

    handle = None
    try:
        handle = backend.start(prepared)
        console.print(
            f"[green]STARTED[/green] [bold]{system.name}[/bold] · "
            f"local:{handle.execution_id}"
        )

        previous_state = None
        while True:
            status = backend.inspect(handle)
            if status.state is not previous_state:
                _render_run_status(system.name, status)
                previous_state = status.state

            if status.terminal:
                if status.state is BackendExecutionState.FAILED:
                    raise typer.Exit(1)
                return

            time.sleep(0.1)

    except KeyboardInterrupt:
        if handle is None:
            console.print("[yellow]Interrupted before execution started.[/yellow]")
            raise typer.Exit(130)

        console.print(
            f"[yellow]Stopping[/yellow] [bold]{system.name}[/bold] · "
            f"local:{handle.execution_id}"
        )
        try:
            status = backend.stop(
                handle,
                timeout_seconds=stop_timeout,
            )
        except Exception as exc:
            console.print(f"[red]System stop failed:[/red] {exc}")
            raise typer.Exit(130)

        _render_run_status(system.name, status)
        if status.state is BackendExecutionState.STOPPING:
            console.print(
                "[yellow]Runtime is still stopping after the requested "
                "timeout.[/yellow]"
            )
        raise typer.Exit(130)

    except typer.Exit:
        raise

    except Exception as exc:
        console.print(f"[red]System execution failed:[/red] {exc}")
        if handle is not None:
            try:
                backend.stop(handle, timeout_seconds=stop_timeout)
            except Exception:
                pass
        raise typer.Exit(1)


@system_app.command("show")
def system_show(
    path: Annotated[
        Path | None,
        typer.Argument(help="System YAML/JSON document"),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help=(
                "Project Profile (nodrix.profile/v1) applied as a "
                "System Config overlay; not a RuntimePreset"
            ),
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print canonical System JSON"),
    ] = False,
    document: Annotated[
        bool,
        typer.Option("--document", help="Print canonical System YAML instead of a summary"),
    ] = False,
    resolution: Annotated[
        bool,
        typer.Option(
            "--resolution",
            help=(
                "Show System Module, Config, Config overlay, "
                "and provenance inputs"
            ),
        ),
    ] = False,
) -> None:
    """Show the canonical System document or a concise architecture summary."""

    if json_output and document:
        console.print("[red]Use either --json or --document, not both.[/red]")
        raise typer.Exit(2)

    if document and resolution:
        console.print(
            "[red]--resolution cannot be combined with --document; "
            "use the summary view or --json --resolution.[/red]"
        )
        raise typer.Exit(2)

    try:
        resolved_path, _ = _resolve_system_cli_inputs(
            path
        )
        details = _load_system_cli_details(
            resolved_path,
            profile=profile,
        )
        system = details.system
    except Exception as exc:
        console.print(f"[red]Cannot load System:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        payload = (
            {
                "system": details.canonical,
                "resolution": _resolution_payload(
                    details
                ),
            }
            if resolution
            else details.canonical
        )

        console.print_json(
            json.dumps(
                payload,
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

    if resolution:
        _render_system_resolution(
            details
        )


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
