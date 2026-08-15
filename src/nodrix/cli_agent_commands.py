"""Remote-agent CLI commands for Nodrix 2.8 M5."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Annotated

import typer

from .cli_context import app, console
from .system.remote_agent import RemoteAgentServer


agent_app = typer.Typer(
    help="Run the Nodrix remote execution agent on a prepared target host."
)
app.add_typer(agent_app, name="agent")


@agent_app.command("serve")
def agent_serve(
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help="Agent bind host. M5a accepts loopback only.",
        ),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(
            "--port",
            min=0,
            max=65535,
            help="Agent TCP port; 0 selects an ephemeral port.",
        ),
    ] = 7843,
    token_env: Annotated[
        str,
        typer.Option(
            "--token-env",
            help="Environment variable containing the agent authentication token.",
        ),
    ] = "NODRIX_AGENT_TOKEN",
    working_directory: Annotated[
        Path,
        typer.Option(
            "--working-directory",
            "-C",
            help="Prepared target workspace used for generated execution files.",
        ),
    ] = Path("."),
    run_root: Annotated[
        Path | None,
        typer.Option(
            "--run-root",
            help="Optional runtime output root for remote process scopes.",
        ),
    ] = None,
) -> None:
    """Serve the M5 remote execution control plane."""

    token = os.environ.get(token_env)
    if not token:
        console.print(
            f"[red]Agent start failed:[/red] environment variable {token_env!r} is not set"
        )
        raise typer.Exit(1)

    try:
        server = RemoteAgentServer(
            host=host,
            port=port,
            token=token,
            working_directory=working_directory,
            run_root=run_root,
        )
        server.start()
    except Exception as exc:
        console.print(f"[red]Agent start failed:[/red] {exc}")
        raise typer.Exit(1)

    bound_host, bound_port = server.address
    console.print(
        f"[green]AGENT READY[/green] · {bound_host}:{bound_port} · "
        f"protocol=nodrix.remote-agent/v1"
    )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        console.print("[yellow]Stopping remote agent[/yellow]")
    finally:
        server.close()


__all__ = ["agent_app", "agent_serve"]
