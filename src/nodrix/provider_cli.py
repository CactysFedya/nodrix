"""Provider discovery, inspection, and verification CLI group."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.table import Table
import typer

from .providers import (
    ProviderPolicy,
    provider_record,
    provider_records,
    resolve_provider,
    verify_provider,
)


provider_app = typer.Typer(
    help="Discover and verify installed Provider API distributions."
)
console = Console()


def _provider_policy(
    *,
    production: bool,
    trust_store: Path | None,
    allow: list[str] | None,
) -> ProviderPolicy:
    return ProviderPolicy.from_environment(
        production=production,
        trust_store=trust_store,
        allowlist=allow,
    )


@provider_app.command("list")
def provider_list_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON"),
    ] = False,
    production: Annotated[
        bool,
        typer.Option("--production", help="Apply production trust policy"),
    ] = False,
    trust_store: Annotated[
        Path | None,
        typer.Option(
            "--trust-store",
            help="Directory containing trusted Ed25519 public keys",
        ),
    ] = None,
    allow: Annotated[
        list[str] | None,
        typer.Option("--allow", help="Production provider id; repeatable"),
    ] = None,
) -> None:
    """List provider metadata without importing provider packages."""

    try:
        records = provider_records(
            policy=_provider_policy(
                production=production,
                trust_store=trust_store,
                allow=allow,
            )
        )
    except Exception as exc:
        console.print(f"[red]Provider discovery failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(records))
        return
    table = Table("Provider", "Version", "Source", "Status", "Features")
    for item in records:
        table.add_row(
            item["id"],
            str(item["version"]),
            item["source"],
            item["verification"]["status"],
            ", ".join(item["features"]) or "-",
        )
    console.print(table)


@provider_app.command("info")
def provider_info_command(
    provider_id: Annotated[
        str,
        typer.Argument(help="Provider id or unambiguous suffix"),
    ],
    json_output: Annotated[bool, typer.Option("--json")] = False,
    production: Annotated[bool, typer.Option("--production")] = False,
    trust_store: Annotated[
        Path | None,
        typer.Option("--trust-store"),
    ] = None,
    allow: Annotated[list[str] | None, typer.Option("--allow")] = None,
) -> None:
    """Show one provider's metadata and trust state without importing it."""

    try:
        candidate = resolve_provider(provider_id)
        record = provider_record(
            candidate,
            policy=_provider_policy(
                production=production,
                trust_store=trust_store,
                allow=allow,
            ),
        )
    except Exception as exc:
        console.print(f"[red]Provider info failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(record))
        return
    console.print(f"[bold]{record['id']}[/bold] {record['version']}")
    console.print(
        f"Distribution: {record['distribution']} ({record['source']})"
    )
    console.print(f"Provider API: {record['provider_api']}")
    console.print(f"Requires Nodrix: {record['requires_nodrix']}")
    console.print(f"Trust status: {record['verification']['status']}")
    if record["verification"]["errors"]:
        for error in record["verification"]["errors"]:
            console.print(f"[red]- {error}[/red]")
    table = Table("Kind", "Id", "Implementation")
    for node in record["nodes"]:
        table.add_row("node", node["id"], node["factory"])
    for probe in record["probes"]:
        table.add_row("probe", probe["id"], probe["callable"])
    for session in record["sessions"]:
        table.add_row("session", session["id"], session["factory"])
    for resource in record["resources"]:
        table.add_row("resource", resource["id"], resource["factory"])
    for application in record["applications"]:
        table.add_row(
            "application",
            application["id"],
            application["factory"],
        )
    for transport in record["transports"]:
        table.add_row("transport", transport["id"], "edge transport")
    for link in record["links"]:
        table.add_row("link", link["id"], "external compiler binding")
    for template in record["templates"]:
        table.add_row("template", template["id"], template["source"])
    console.print(table)


@provider_app.command("verify")
def provider_verify_command(
    provider_id: Annotated[
        str,
        typer.Argument(help="Provider id or unambiguous suffix"),
    ],
    production: Annotated[bool, typer.Option("--production")] = False,
    trust_store: Annotated[
        Path | None,
        typer.Option("--trust-store"),
    ] = None,
    allow: Annotated[list[str] | None, typer.Option("--allow")] = None,
) -> None:
    """Verify metadata, compatibility, features, signature, and trust."""

    try:
        result = verify_provider(
            provider_id,
            policy=_provider_policy(
                production=production,
                trust_store=trust_store,
                allow=allow,
            ),
        )
    except Exception as exc:
        console.print(f"[red]Provider verification failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print_json(json.dumps(result.to_dict()))
    if result.errors:
        raise typer.Exit(1)


__all__ = ["provider_app"]
