"""Nodrix 2.8 System run command backed by ``SystemOrchestrator``.

The canonical System CLI module still owns validate/plan/show/convert/schema.
This focused module registers the 2.8 ``run`` callback after the legacy
registration so Typer resolves the newer command.  Keeping the migration in a
small module makes the lifecycle change reviewable while the 2.7 command
surface stays stable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from . import cli_system_commands as system_cli
from .cli_context import console
from .system import (
    BackendExecutionState,
    ExecutionScope,
    SystemExecutionStatus,
    SystemOrchestrator,
    plan_execution_scopes,
)
from .workspace import find_workspace


def _local_backend_for_scope(
    scope: ExecutionScope,
    *,
    project: Path | None,
    working_directory: Path,
    run_root: Path | None,
    stop_timeout: float,
):
    """Create one in-process backend instance for one orchestration scope."""

    return system_cli.LocalBackend(
        project=project,
        working_directory=working_directory,
        run_root=run_root,
        stop_timeout_seconds=stop_timeout,
        scope_name=scope.target,
    )


def _process_backend_for_scope(
    scope: ExecutionScope,
    *,
    project: Path | None,
    working_directory: Path,
    run_root: Path | None,
    stop_timeout: float,
):
    """Create one process-isolated backend for one orchestration scope."""

    from .system import ProcessBackend

    return ProcessBackend(
        project=project,
        working_directory=working_directory,
        run_root=run_root,
        stop_timeout_seconds=stop_timeout,
        scope_name=scope.target,
    )


def _build_orchestrator(
    plan,
    *,
    project: Path | None,
    working_directory: Path,
    run_root: Path | None,
    stop_timeout: float,
) -> SystemOrchestrator:
    bindings = {}
    for scope in plan_execution_scopes(plan):
        if scope.backend == "local":
            backend = _local_backend_for_scope(
                scope,
                project=project,
                working_directory=working_directory,
                run_root=run_root,
                stop_timeout=stop_timeout,
            )
        elif scope.backend == "process":
            backend = _process_backend_for_scope(
                scope,
                project=project,
                working_directory=working_directory,
                run_root=run_root,
                stop_timeout=stop_timeout,
            )
        else:
            # Later 2.8 milestones register remote backends here. An
            # intentionally missing binding becomes ORCH101 during validation.
            continue
        bindings[scope] = backend
    return SystemOrchestrator(bindings)


def _render_orchestration_validation(report) -> None:
    for item in report.diagnostics:
        color = "red" if item.level == "error" else "yellow"
        scope = item.scope.id if item.scope is not None else "-"
        source = f"{item.source}:" if item.source else ""
        console.print(
            f"[{color}]{item.code}[/{color}] {scope} · "
            f"{source}{item.path or '-'} · {item.message}"
        )


def _render_scope_status(
    system_name: str,
    item,
) -> None:
    status = item.status
    state = status.state.value.upper()
    color = (
        "green"
        if status.state
        in {BackendExecutionState.COMPLETED, BackendExecutionState.STOPPED}
        else "red"
        if status.state is BackendExecutionState.FAILED
        else "yellow"
    )
    suffix = f" · {status.message}" if status.message else ""
    console.print(
        f"[{color}]{state}[/{color}] [bold]{system_name}[/bold] · "
        f"{item.scope.id} · {status.backend}:{status.execution_id}{suffix}"
    )


def _render_changed_scope_statuses(
    system_name: str,
    status: SystemExecutionStatus,
    previous: dict[ExecutionScope, BackendExecutionState],
) -> None:
    for item in status.scopes:
        current = item.status.state
        if previous.get(item.scope) is current:
            continue
        _render_scope_status(system_name, item)
        previous[item.scope] = current


def _prepared_summary(system_name: str, prepared) -> None:
    if not prepared.scopes:
        console.print(
            f"[green]PREPARED[/green] [bold]{system_name}[/bold] · scopes=0"
        )
        return

    for item in prepared.scopes:
        manifest_path = item.prepared.metadata.get("manifest_path")
        suffix = f" · {manifest_path}" if manifest_path else ""
        console.print(
            f"[green]PREPARED[/green] [bold]{system_name}[/bold] · "
            f"scope={item.scope.id}{suffix}"
        )


@system_cli.system_app.command("run")
def system_run_orchestrated(
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
            help="Optional runtime output root passed to execution scopes",
        ),
    ] = None,
    stop_timeout: Annotated[
        float,
        typer.Option(
            "--stop-timeout",
            min=0.0,
            help="Seconds to wait for each execution scope to stop after Ctrl+C",
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
    """Plan and execute a System through the Nodrix 2.8 orchestrator."""

    try:
        resolved_path, effective_project = system_cli._resolve_system_cli_inputs(
            path,
            project,
        )
        system = system_cli.load_system(resolved_path)
        catalog = (
            system_cli._catalog_for_project(effective_project)
            if effective_project is not None
            else None
        )
        plan = system_cli.plan_system(system, catalog=catalog)
    except Exception as exc:
        console.print(f"[red]System run failed:[/red] {exc}")
        raise typer.Exit(1)

    if warnings_as_errors and plan.diagnostics:
        console.print(
            "[red]System run refused:[/red] "
            "RUN102: planner warnings are present and "
            "--warnings-as-errors was set"
        )
        system_cli._render_system_plan(plan)
        raise typer.Exit(1)

    if plan.diagnostics:
        console.print(f"[yellow]Planner warnings:[/yellow] {len(plan.diagnostics)}")
        for item in plan.diagnostics:
            console.print(
                f"[yellow]{item.code}[/yellow] "
                f"{item.path or '-'} · {item.message}"
            )

    execution_root = find_workspace(resolved_path.parent) or resolved_path.parent
    orchestrator = _build_orchestrator(
        plan,
        project=effective_project,
        working_directory=execution_root,
        run_root=run_root,
        stop_timeout=stop_timeout,
    )

    report = orchestrator.validate_plan(plan)
    if report.diagnostics:
        _render_orchestration_validation(report)
    if not report.valid:
        console.print(
            "[red]System run failed:[/red] "
            "RUN103: SystemOrchestrator rejected the execution plan"
        )
        raise typer.Exit(1)

    try:
        prepared = orchestrator.prepare_plan(plan)
    except Exception as exc:
        console.print(f"[red]System prepare failed:[/red] {exc}")
        raise typer.Exit(1)

    _prepared_summary(system.name, prepared)

    handle = None
    try:
        handle = orchestrator.start(
            prepared,
            rollback_timeout_seconds=stop_timeout,
        )
        console.print(
            f"[green]STARTED[/green] [bold]{system.name}[/bold] · "
            f"{handle.execution_id} · scopes={len(handle.scopes)}"
        )

        previous_states: dict[ExecutionScope, BackendExecutionState] = {}
        while True:
            status = orchestrator.inspect(handle)
            _render_changed_scope_statuses(
                system.name,
                status,
                previous_states,
            )

            if status.terminal:
                if status.state is BackendExecutionState.FAILED:
                    stopped = orchestrator.stop(
                        handle,
                        timeout_seconds=stop_timeout,
                    )
                    _render_changed_scope_statuses(
                        system.name,
                        stopped,
                        previous_states,
                    )
                    raise typer.Exit(1)
                return

            system_cli.time.sleep(0.1)

    except KeyboardInterrupt:
        if handle is None:
            console.print("[yellow]Interrupted before execution started.[/yellow]")
            raise typer.Exit(130)

        console.print(
            f"[yellow]Stopping[/yellow] [bold]{system.name}[/bold] · "
            f"{handle.execution_id} · scopes={len(handle.scopes)}"
        )
        status = orchestrator.stop(
            handle,
            timeout_seconds=stop_timeout,
        )
        previous_states = {}
        _render_changed_scope_statuses(system.name, status, previous_states)
        if status.state is BackendExecutionState.STOPPING:
            console.print(
                "[yellow]One or more execution scopes are still stopping after "
                "the requested timeout.[/yellow]"
            )
        raise typer.Exit(130)

    except typer.Exit:
        raise

    except Exception as exc:
        console.print(f"[red]System execution failed:[/red] {exc}")
        if handle is not None:
            orchestrator.stop(handle, timeout_seconds=stop_timeout)
        raise typer.Exit(1)


__all__ = [
    "system_run_orchestrated",
]
