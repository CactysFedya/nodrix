"""CLI commands for the canonical Nodrix System Model."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Annotated

import typer
import yaml

from .cli_context import app, console
from .local_dev import compile_local_project, reset_local_development_modules
from .manifest import load_manifest
from .project_foundation import resolve_project_resource
from .workspace import find_workspace
from .sdk.definitions import MessageDefinition, NodeDefinition, ResourceDefinition
from .system import (
    BackendExecutionState,
    DefinitionCatalog,
    LocalBackend,
    dump_system,
    dump_system_schema,
    load_system,
    pipeline_manifest_to_system,
    plan_system,
    system_to_canonical,
    validate_system,
)
from .system_presentation import (
    render_backend_validation,
    render_schema_written,
    render_system_conversion,
    render_system_error,
    render_system_overview,
    render_system_plan_result,
    render_system_prepared,
    render_system_run_intro,
    render_system_running,
    render_system_started,
    render_system_stopping,
    render_system_terminal,
    render_system_validation_result,
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


def _diagnostic_dict(item) -> dict[str, str]:
    return {
        "level": str(item.level),
        "code": str(item.code),
        "path": str(item.path),
        "message": str(item.message),
    }


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
        resolved_path, effective_project = _resolve_system_cli_inputs(path, project)
        system = load_system(resolved_path)
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
            console.print(render_system_error("validation", exc))
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
        mode = "definitions resolved" if effective_project is not None else "structural"
        console.print(
            render_system_validation_result(
                name=system.name,
                valid=bool(payload["ok"]),
                mode=mode,
                path=resolved_path,
                diagnostics=report.diagnostics,
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
        resolved_path, effective_project = _resolve_system_cli_inputs(path, project)
        system = load_system(resolved_path)
        catalog = (
            _catalog_for_project(effective_project)
            if effective_project is not None
            else None
        )
        plan = plan_system(system, catalog=catalog)
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
            console.print(render_system_error("planning", exc))
        raise typer.Exit(1)

    if json_output:
        console.print_json(
            json.dumps(
                _plan_jsonable(plan),
                ensure_ascii=False,
            )
        )
    else:
        console.print(render_system_plan_result(plan))

    if warnings_as_errors and plan.diagnostics:
        raise typer.Exit(1)


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
        console.print(render_system_error("run", exc))
        raise typer.Exit(1)

    backend_names = _plan_backend_names(plan)
    if backend_names != ("local",):
        found = ", ".join(backend_names) if backend_names else "<none>"
        console.print(
            render_system_error(
                "run",
                f"execution plan resolves to backend(s): {found}",
                code="RUN101",
                hint="Nodrix 2.6 system run supports exactly one local backend scope.",
            )
        )
        raise typer.Exit(1)

    if warnings_as_errors and plan.diagnostics:
        console.print(
            render_system_error(
                "run",
                "planner warnings are present and --warnings-as-errors was set",
                code="RUN102",
            )
        )
        console.print(render_system_plan_result(plan))
        raise typer.Exit(1)

    console.print(render_system_run_intro(system, plan, resolved_path))

    execution_root = find_workspace(resolved_path.parent) or resolved_path.parent
    backend = LocalBackend(
        project=effective_project,
        working_directory=execution_root,
        run_root=run_root,
        stop_timeout_seconds=stop_timeout,
    )

    report = backend.validate_plan(plan)
    if report.diagnostics:
        console.print()
        console.print(render_backend_validation(report))

    if not report.valid:
        console.print()
        console.print(
            render_system_error(
                "run",
                "LocalBackend rejected the execution plan",
                code="RUN103",
            )
        )
        raise typer.Exit(1)

    try:
        prepared = backend.prepare_plan(plan)
    except Exception as exc:
        console.print()
        console.print(render_system_error("prepare", exc))
        raise typer.Exit(1)

    manifest_path = prepared.metadata.get("manifest_path")
    console.print()
    console.print(
        render_system_prepared(
            system.name,
            manifest_path=manifest_path,
        )
    )

    handle = None
    started_at = time.monotonic()
    try:
        handle = backend.start(prepared)
        started_at = time.monotonic()
        console.print(
            render_system_started(
                system.name,
                backend="local",
                execution_id=handle.execution_id,
            )
        )

        previous_state = None
        while True:
            status = backend.inspect(handle)
            if status.state is not previous_state:
                if status.state is BackendExecutionState.RUNNING:
                    console.print(
                        render_system_running(
                            system.name,
                            status,
                            plan,
                        )
                    )
                elif status.state is BackendExecutionState.STOPPING:
                    console.print(
                        render_system_stopping(
                            system.name,
                            backend=status.backend,
                            execution_id=status.execution_id,
                        )
                    )
                previous_state = status.state

            if status.terminal:
                console.print()
                console.print(
                    render_system_terminal(
                        system.name,
                        status,
                        plan,
                        elapsed_seconds=time.monotonic() - started_at,
                    )
                )
                if status.state is BackendExecutionState.FAILED:
                    raise typer.Exit(1)
                return

            time.sleep(0.1)

    except KeyboardInterrupt:
        if handle is None:
            console.print(render_system_error("run", "interrupted before execution started"))
            raise typer.Exit(130)

        console.print()
        console.print(
            render_system_stopping(
                system.name,
                backend="local",
                execution_id=handle.execution_id,
            )
        )
        try:
            status = backend.stop(
                handle,
                timeout_seconds=stop_timeout,
            )
        except Exception as exc:
            console.print(render_system_error("stop", exc))
            raise typer.Exit(130)

        console.print()
        console.print(
            render_system_terminal(
                system.name,
                status,
                plan,
                elapsed_seconds=time.monotonic() - started_at,
                stop_requested=True,
            )
        )
        if status.state is BackendExecutionState.STOPPING:
            console.print(
                render_system_error(
                    "stop",
                    status.message or "runtime is still stopping",
                    code="STOP_TIMEOUT",
                    hint=f"The requested stop timeout was {stop_timeout:g}s.",
                )
            )
        raise typer.Exit(130)

    except typer.Exit:
        raise

    except Exception as exc:
        console.print()
        console.print(render_system_error("execution", exc))
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
        console.print(
            render_system_error(
                "show",
                "use either --json or --document, not both",
                code="SHOW101",
            )
        )
        raise typer.Exit(2)

    try:
        resolved_path, _ = _resolve_system_cli_inputs(path)
        system = load_system(resolved_path)
    except Exception as exc:
        console.print(render_system_error("show", exc))
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

    console.print(render_system_overview(system, resolved_path))


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
            console.print(render_system_error("conversion", message, code="CONVERT101"))
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
            console.print(render_system_error("conversion", exc))
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

    console.print(
        render_system_conversion(
            pipeline=pipeline_path,
            destination=destination,
            converted=converted,
        )
    )


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
            console.print(render_schema_written(destination))
            return

        from .system import system_json_schema

        console.print_json(
            json.dumps(
                system_json_schema(),
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        console.print(render_system_error("schema", exc))
        raise typer.Exit(1)
