from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from rich.table import Table
import typer
import yaml

from .build_recipes import available_build_recipes
from .cli_context import app, console
from .project_foundation import (
    add_project_resource,
    create_progressive_project,
    list_project_resources,
)
from .workflow_execution import list_workflows, load_workflow, run_workflow
from .workflow_planning import WorkflowPlanResult, plan_workflow


project_app = typer.Typer(
    help="Create a project progressively and add resources only when needed."
)
workflow_app = typer.Typer(
    help="Inspect and run finite prepare, build, test and deployment workflows."
)

app.add_typer(project_app, name="project")
app.add_typer(workflow_app, name="workflow")


@project_app.command("init")
def project_init(
    directory: Annotated[Path, typer.Argument()] = Path.cwd(),
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Create nodrix.yaml without eagerly creating architecture directories."""

    try:
        created = create_progressive_project(directory, force=force)
    except Exception as exc:
        console.print(f"[red]Project init failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Created[/green] {directory.expanduser().resolve()}")
    for path in created:
        console.print(f"  {path}")
    console.print("Add a System: [bold]plyctl project add system main --default[/bold]")


@project_app.command("add")
def project_add(
    kind: Annotated[
        str,
        typer.Argument(
            help="system, pipeline, workflow, environment, profile, or component"
        ),
    ],
    name: Annotated[str, typer.Argument()],
    template: Annotated[
        str | None,
        typer.Option("--template", "-t", help="Optional resource template"),
    ] = None,
    make_default: Annotated[
        bool,
        typer.Option("--default", help="Set system/pipeline/environment/profile as default"),
    ] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Create and register one project resource."""

    try:
        result = add_project_resource(
            kind,
            name,
            template=template,
            force=force,
            make_default=make_default,
        )
    except Exception as exc:
        console.print(f"[red]Cannot add resource:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"[green]Added[/green] {result.kind} {result.name}: {result.path}"
    )


@project_app.command("list")
def project_list(
    kind: Annotated[str | None, typer.Argument()] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List resources registered by the project manifest."""

    try:
        resources = list_project_resources(kind)
    except Exception as exc:
        console.print(f"[red]Cannot list project resources:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(resources, ensure_ascii=False))
        return
    table = Table(box=None, show_edge=False, pad_edge=False)
    table.add_column("KIND")
    table.add_column("NAME")
    table.add_column("PATH")
    for resource_kind, entries in resources.items():
        if not entries:
            table.add_row(resource_kind, "-", "-")
            continue
        for name, path in sorted(entries.items()):
            table.add_row(resource_kind, str(name), str(path))
    console.print(table)


@project_app.command("recipes")
def project_recipes(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List high-level Build Recipe SDK entries available to the project."""

    recipes = available_build_recipes()
    if json_output:
        console.print_json(
            json.dumps(
                [
                    {"name": item.name, "description": item.description}
                    for item in recipes
                ],
                ensure_ascii=False,
            )
        )
        return
    table = Table(box=None, show_edge=False, pad_edge=False)
    table.add_column("RECIPE")
    table.add_column("DESCRIPTION")
    for item in recipes:
        table.add_row(item.name, item.description)
    console.print(table)


@workflow_app.command("list")
def workflow_list(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List declared finite workflows."""

    try:
        workflows = list_workflows()
    except Exception as exc:
        console.print(f"[red]Cannot list workflows:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(workflows, ensure_ascii=False))
        return
    table = Table(box=None, show_edge=False, pad_edge=False)
    table.add_column("WORKFLOW")
    table.add_column("PATH")
    for name, path in sorted(workflows.items()):
        table.add_row(name, path)
    if not workflows:
        table.add_row("-", "No workflows declared")
    console.print(table)


@workflow_app.command("show")
def workflow_show(
    name: Annotated[str, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show a resolved workflow document."""

    try:
        document, path, _ = load_workflow(name)
    except Exception as exc:
        console.print(f"[red]Cannot load workflow:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(document, ensure_ascii=False))
        return
    console.print(f"[bold]{path}[/bold]")
    console.print(yaml.safe_dump(document, sort_keys=False).rstrip())


def _execute_workflow(
    name: str,
    environment: str | None,
    dry_run: bool,
    json_output: bool,
    rebuild: bool = False,
) -> None:
    try:
        result = run_workflow(
            name,
            environment_name=environment,
            dry_run=dry_run,
            force=rebuild,
        )
    except Exception as exc:
        console.print(f"[red]Workflow failed before execution:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(result.as_dict(), ensure_ascii=False))
    else:
        table = Table(box=None, show_edge=False, pad_edge=False)
        table.add_column("STATUS")
        table.add_column("STEP")
        table.add_column("SECONDS", justify="right")
        table.add_column("LOG")
        for step in result.steps:
            table.add_row(
                step.status.upper(),
                step.step_id,
                f"{step.duration_seconds:.3f}",
                step.log_path,
                style="red" if step.status == "failed" else None,
            )
        console.print(table)
        color = "green" if result.succeeded or dry_run else "red"
        console.print(
            f"[{color}]{result.status.upper()}[/{color}] {result.name}"
        )
        console.print(f"Artifacts: {result.run_directory}")
    if not result.succeeded and not dry_run:
        raise typer.Exit(1)


@workflow_app.command("run")
def workflow_run(
    name: Annotated[str, typer.Argument()],
    environment: Annotated[
        str | None,
        typer.Option("--environment", "-e"),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    rebuild: Annotated[
        bool,
        typer.Option("--rebuild", help="Ignore successful step cache entries"),
    ] = False,
) -> None:
    """Run a declared workflow and persist logs and summary artifacts."""

    _execute_workflow(name, environment, dry_run, json_output, rebuild)


def _render_build_plan(result: WorkflowPlanResult) -> None:
    source = "generated recipes" if result.generated else "workflow"
    environment = result.environment or "default"
    console.print(
        f"[bold]BUILD PLAN[/bold] · {source} · environment={environment}"
    )
    table = Table(box=None, show_edge=False, pad_edge=False)
    table.add_column("#", justify="right")
    table.add_column("STATUS")
    table.add_column("STEP")
    table.add_column("RECIPE")
    table.add_column("DEPENDS")
    table.add_column("CACHE")
    table.add_column("REASON")
    for step in result.steps:
        style = (
            "green" if step.status == "cached" else
            "yellow" if step.status == "planned" else
            "dim"
        )
        table.add_row(
            str(step.index),
            step.status.upper(),
            step.step_id,
            step.recipe or "-",
            ", ".join(step.depends_on) or "-",
            step.cache,
            "; ".join(step.reasons) or "-",
            style=style,
        )
    console.print(table)
    cached = sum(item.status == "cached" for item in result.steps)
    planned = sum(item.status == "planned" for item in result.steps)
    skipped = sum(item.status == "skipped" for item in result.steps)
    console.print(
        f"Cached: {cached} · Planned: {planned} · Skipped: {skipped}"
    )


def _render_build_explain(result: WorkflowPlanResult, step_id: str) -> None:
    step = result.step(step_id)
    console.print(f"[bold]BUILD EXPLAIN {step.step_id}[/bold]")
    console.print(f"Status:      {step.status.upper()}")
    console.print(f"Recipe:      {step.recipe or '-'}")
    console.print(f"Depends on:  {', '.join(step.depends_on) or '-'}")
    console.print(f"Cache:       {step.cache}")
    console.print(f"Working dir: {step.cwd}")
    console.print("Reasons:")
    for reason in step.reasons:
        console.print(f"  - {reason}")
    console.print("Tracked inputs:")
    for item in step.cache_inputs or ("-",):
        console.print(f"  {item}")
    console.print("Tracked outputs:")
    for item in step.cache_outputs or ("-",):
        console.print(f"  {item}")
    console.print("Tracked environment:")
    for item in step.cache_environment or ("-",):
        console.print(f"  {item}")


def _require_build_configuration(*, json_output: bool) -> None:
    """Fail with an actionable message when this project has no build definition."""

    try:
        workflows = list_workflows()
    except Exception as exc:
        console.print(f"[red]Build configuration check failed:[/red] {exc}")
        raise typer.Exit(1)
    if "build" in workflows:
        return

    message = (
        "Build is not configured for this project. "
        "Add a 'build:' section to nodrix.yaml or register workflows.build."
    )
    if json_output:
        console.print_json(
            json.dumps(
                {
                    "status": "not_configured",
                    "workflow": "build",
                    "message": message,
                },
                ensure_ascii=False,
            )
        )
    else:
        console.print("[yellow]Build is not configured for this project.[/yellow]")
        console.print(
            "Add a [bold]build:[/bold] section to nodrix.yaml "
            "or register [bold]workflows.build[/bold]."
        )
        console.print("Available recipes: [bold]plyctl project recipes[/bold]")
    raise typer.Exit(1)


@app.command("build")
def build_command(
    environment: Annotated[
        str | None,
        typer.Option("--environment", "-e"),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    rebuild: Annotated[
        bool,
        typer.Option("--rebuild", help="Ignore successful build cache entries"),
    ] = False,
    plan_only: Annotated[
        bool,
        typer.Option("--plan", help="Resolve build order and cache decisions without executing"),
    ] = False,
    explain: Annotated[
        str | None,
        typer.Option("--explain", metavar="STEP", help="Explain why one build step is cached or planned"),
    ] = None,
) -> None:
    """Run or inspect the project's build workflow."""

    _require_build_configuration(json_output=json_output)

    if plan_only or explain is not None:
        if dry_run:
            console.print(
                "[red]Build inspection failed:[/red] use either --dry-run or --plan/--explain"
            )
            raise typer.Exit(2)
        try:
            result = plan_workflow(
                "build",
                environment_name=environment,
                force=rebuild,
            )
            selected = result.step(explain) if explain is not None else None
        except Exception as exc:
            console.print(f"[red]Build inspection failed:[/red] {exc}")
            raise typer.Exit(1)

        if json_output:
            payload = selected.as_dict() if selected is not None else result.as_dict()
            console.print_json(json.dumps(payload, ensure_ascii=False))
            return
        if selected is not None:
            _render_build_explain(result, selected.step_id)
        else:
            _render_build_plan(result)
        return

    _execute_workflow("build", environment, dry_run, json_output, rebuild)


@app.command("test")
def test_command(
    environment: Annotated[
        str | None,
        typer.Option("--environment", "-e"),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run the project's test workflow."""

    _execute_workflow("test", environment, dry_run, json_output)
