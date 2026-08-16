from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Annotated

import typer
from rich.table import Table

from .cli_context import app, console
from .workspace import (
    PROJECT_FILE,
    build_environment,
    check_environment,
    create_workspace,
    export_environment,
    find_workspace,
    read_supervisor,
    resolve_pipeline_reference,
    set_active_context,
    supervisor_state,
)


workspace_app = typer.Typer(help="Create and inspect Nodrix workspaces.")
context_app = typer.Typer(help="Select execution contexts.")
environment_app = typer.Typer(help="Inspect and enter execution environments.")

app.add_typer(workspace_app, name="workspace")
app.add_typer(context_app, name="context")
app.add_typer(environment_app, name="env")


def _workspace_root() -> Path:
    root = find_workspace(required=True)
    assert root is not None
    return root


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


@workspace_app.command("init")
def workspace_init(
    directory: Annotated[Path, typer.Argument()] = Path.cwd(),
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    try:
        created = create_workspace(directory, force=force)
    except Exception as exc:
        console.print(f"[red]Workspace init failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Created[/green] {directory.resolve()}")
    for path in created:
        console.print(f"  {path}")


@workspace_app.command("show")
def workspace_show(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        resolution = resolve_pipeline_reference()
    except Exception as exc:
        console.print(f"[red]Workspace unavailable:[/red] {exc}")
        raise typer.Exit(1)
    data = {
        "root": str(resolution.root),
        "config": str(resolution.config_path) if resolution.config_path else None,
        "pipeline": str(resolution.pipeline),
        "pipeline_name": resolution.pipeline_name,
        "context": resolution.context_name,
        "environment": resolution.environment_name,
        "profile": resolution.profile_name,
        "runtime_profile": resolution.runtime_profile,
        "view": resolution.view,
    }
    if json_output:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    for key, value in data.items():
        console.print(f"{key:<18} {value or '-'}")


@context_app.command("list")
def context_list() -> None:
    root = _workspace_root()
    import yaml

    config = yaml.safe_load(
        (root / PROJECT_FILE).read_text(encoding="utf-8")
    ) or {}
    contexts = dict(config.get("contexts") or {})
    active = None
    state = root / ".nodrix" / "context"
    if state.is_file():
        active = state.read_text(encoding="utf-8").strip()
    if not active:
        active = dict(config.get("defaults") or {}).get("context")
    table = Table(box=None, show_edge=False, pad_edge=False)
    table.add_column("CONTEXT")
    table.add_column("ENVIRONMENT")
    table.add_column("PROFILE")
    table.add_column("VIEW")
    for name, raw in contexts.items():
        value = dict(raw or {})
        table.add_row(
            ("* " if name == active else "  ") + str(name),
            str(value.get("environment") or "-"),
            str(value.get("profile") or "-"),
            str(value.get("view") or "-"),
        )
    console.print(table)


@context_app.command("show")
def context_show() -> None:
    resolution = resolve_pipeline_reference()
    console.print(f"context      {resolution.context_name or '-'}")
    console.print(f"environment  {resolution.environment_name or '-'}")
    console.print(f"profile      {resolution.profile_name or '-'}")
    console.print(f"pipeline     {resolution.pipeline_name}")
    console.print(f"view         {resolution.view}")


@app.command("use")
def use_context(
    name: Annotated[str, typer.Argument(help="Workspace context name")],
) -> None:
    try:
        root = _workspace_root()
        target = set_active_context(root, name)
    except Exception as exc:
        console.print(f"[red]Cannot select context:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Using[/green] {name} ({target})")


@environment_app.command("show")
def environment_show(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    resolution = resolve_pipeline_reference()
    data = {
        "project": str(resolution.root),
        "context": resolution.context_name,
        "environment": resolution.environment_name,
        "sources": [str(item) for item in resolution.sources],
        "variables": resolution.variables,
    }
    if json_output:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    console.print(f"project      {resolution.root}")
    console.print(f"context      {resolution.context_name or '-'}")
    console.print(f"environment  {resolution.environment_name or '-'}")
    console.print("sources")
    for source in resolution.sources:
        console.print(f"  {source}")
    console.print("variables")
    for key, value in sorted(resolution.variables.items()):
        console.print(f"  {key}={value}")


@environment_app.command("export")
def environment_export() -> None:
    resolution = resolve_pipeline_reference()
    print(export_environment(resolution), end="")


@environment_app.command("check")
def environment_check() -> None:
    try:
        resolution = resolve_pipeline_reference()
        results = check_environment(resolution)
    except Exception as exc:
        console.print(f"[red]Environment check failed:[/red] {exc}")
        raise typer.Exit(1)
    table = Table(box=None, show_edge=False, pad_edge=False)
    table.add_column("STATUS")
    table.add_column("CHECK")
    table.add_column("DETAIL")
    failed = False
    for item in results:
        ok = item["status"] == "ok"
        failed = failed or not ok
        table.add_row(
            "OK" if ok else "ERROR",
            item["check"],
            item["detail"],
            style=None if ok else "red",
        )
    if not results:
        table.add_row("OK", "configuration", "no checks declared")
    console.print(table)
    if failed:
        raise typer.Exit(1)


@app.command("prepare")
def prepare_command(
    environment: Annotated[
        str | None,
        typer.Option("--environment", "-e"),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    rebuild: Annotated[
        bool,
        typer.Option("--rebuild", help="Ignore successful prepare cache entries"),
    ] = False,
) -> None:
    """Validate the selected environment and run the optional prepare workflow."""

    from .workflow_execution import (
        check_project_environment,
        has_workflow,
    )
    from .workflow_operation import execute_workflow_operation

    root = find_workspace()
    if root is not None:
        try:
            results = check_project_environment(
                root,
                environment_name=environment,
            )
        except Exception as exc:
            console.print(f"[red]Not ready:[/red] {exc}")
            raise typer.Exit(1)
        table = Table(box=None, show_edge=False, pad_edge=False)
        table.add_column("STATUS")
        table.add_column("CHECK")
        table.add_column("DETAIL")
        failed = False
        for item in results:
            ok = item["status"] == "ok"
            failed = failed or not ok
            table.add_row(
                "OK" if ok else "ERROR",
                item["check"],
                item["detail"],
                style=None if ok else "red",
            )
        if results:
            console.print(table)
        if failed:
            raise typer.Exit(1)
        if has_workflow(root, "prepare"):
            outcome = execute_workflow_operation(
                "prepare",
                root=root,
                environment_name=environment,
                dry_run=dry_run,
                force=rebuild,
            )
            result = outcome.legacy_result()

            for step in result["steps"]:
                console.print(
                    f"{str(step.get('status', '')).upper():<10} "
                    f"{str(step.get('step_id', '-')):<24} "
                    f"{str(step.get('log_path', '-'))}"
                )

            console.print(
                f"Artifacts: {result.get('run_directory') or '-'}"
            )
            console.print(
                f"History: {outcome.history.path}"
            )

            if not outcome.successful:
                raise typer.Exit(1)
        console.print(f"[green]READY[/green] {root.name}")
        console.print(f"Project: {root}")
        console.print(f"Environment: {environment or 'default'}")
        return

    try:
        resolution = resolve_pipeline_reference()
        results = check_environment(resolution)
        failed_items = [item for item in results if item["status"] != "ok"]
        if failed_items:
            rendered = "; ".join(item["detail"] for item in failed_items)
            raise RuntimeError(rendered)
        build_environment(resolution)
    except Exception as exc:
        console.print(f"[red]Not ready:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]READY[/green] {resolution.pipeline_name}")
    console.print(f"Project: {resolution.root}")
    console.print(f"Context: {resolution.context_name or '-'}")
    console.print(f"Pipeline: {resolution.pipeline}")

@app.command("shell")
def shell_command() -> None:
    try:
        resolution = resolve_pipeline_reference()
        env = build_environment(resolution)
    except Exception as exc:
        console.print(f"[red]Cannot open workspace shell:[/red] {exc}")
        raise typer.Exit(1)
    shell = env.get("SHELL") or "/bin/bash"
    rcfile = resolution.root / ".nodrix" / "shell.rc"
    rcfile.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"source {source!s}" for source in resolution.sources]
    lines.extend(
        f"export {key}={json.dumps(value)}"
        for key, value in sorted(resolution.variables.items())
    )
    lines.append(
        "export PS1='("
        + resolution.root.name
        + ":"
        + (resolution.context_name or "default")
        + ") \\u@\\h:\\w\\$ '"
    )
    rcfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.execvpe(
        shell,
        [shell, "--noprofile", "--rcfile", str(rcfile), "-i"],
        env,
    )


@app.command("up")
def up_command(
    pipeline: Annotated[str | None, typer.Argument()] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    try:
        resolution = resolve_pipeline_reference(pipeline)
        state_path = supervisor_state(resolution.root)
        current = read_supervisor(resolution.root)
        current_pid = int(current.get("pid", 0) or 0)
        if current_pid and _is_alive(current_pid) and not force:
            raise RuntimeError(
                f"Pipeline is already running with pid {current_pid}"
            )
        log_path = resolution.root / ".nodrix" / "logs" / "runtime.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "nodrix.cli",
            "run",
            pipeline or resolution.pipeline_name,
            "--run-root",
            str(resolution.root / ".nodrix" / "runs"),
        ]
        if profile:
            command.extend(["--profile", profile])
        env = build_environment(resolution)
        log = log_path.open("ab", buffering=0)
        process = subprocess.Popen(
            command,
            cwd=resolution.root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "pid": process.pid,
                    "pipeline": resolution.pipeline_name,
                    "command": command,
                    "log": str(log_path),
                    "started_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        time.sleep(0.4)
        if process.poll() is not None:
            raise RuntimeError(
                f"Pipeline exited during startup; inspect {log_path}"
            )
    except Exception as exc:
        console.print(f"[red]Up failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"[green]RUNNING[/green] {resolution.pipeline_name} pid={process.pid}"
    )
    console.print(f"Logs: {log_path}")
    console.print("Monitor: plyctl top")


@app.command("down")
def down_command(
    timeout: Annotated[float, typer.Option("--timeout", min=0.1)] = 10.0,
) -> None:
    root = _workspace_root()
    state = read_supervisor(root)
    pid = int(state.get("pid", 0) or 0)
    if not pid or not _is_alive(pid):
        console.print("No supervised pipeline is running")
        supervisor_state(root).unlink(missing_ok=True)
        return
    try:
        os.killpg(pid, signal.SIGINT)
    except ProcessLookupError:
        supervisor_state(root).unlink(missing_ok=True)
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _is_alive(pid):
        time.sleep(0.1)
    if _is_alive(pid):
        os.killpg(pid, signal.SIGTERM)
        time.sleep(1.0)
    if _is_alive(pid):
        os.killpg(pid, signal.SIGKILL)
    supervisor_state(root).unlink(missing_ok=True)
    console.print("[yellow]STOPPED[/yellow]")


@app.command("ps")
def ps_command() -> None:
    root = _workspace_root()
    state = read_supervisor(root)
    pid = int(state.get("pid", 0) or 0)
    alive = bool(pid and _is_alive(pid))
    console.print(
        f"{state.get('pipeline', '-'):<24} "
        f"{'RUNNING' if alive else 'STOPPED':<8} "
        f"pid={pid or '-'}"
    )
    if pid and not alive:
        supervisor_state(root).unlink(missing_ok=True)


@app.command("logs")
def logs_command(
    lines: Annotated[int, typer.Option("--lines", "-n", min=1)] = 100,
    follow: Annotated[bool, typer.Option("--follow", "-f")] = False,
) -> None:
    root = _workspace_root()
    state = read_supervisor(root)
    path = Path(
        state.get("log")
        or root / ".nodrix" / "logs" / "runtime.log"
    )
    if not path.is_file():
        console.print(f"[red]Log file not found:[/red] {path}")
        raise typer.Exit(1)
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in content[-lines:]:
        print(line)
    if not follow:
        return
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        stream.seek(0, os.SEEK_END)
        try:
            while True:
                line = stream.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.2)
        except KeyboardInterrupt:
            return


@app.command("restart")
def restart_command(
    pipeline: Annotated[str | None, typer.Argument()] = None,
) -> None:
    down_command()
    up_command(pipeline=pipeline, profile=None, force=True)
