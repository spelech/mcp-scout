"""Typer CLI entrypoint for mcp-scout."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel

from mcp_scout.injector.compose_locator import ComposeLocator
from mcp_scout.injector.yaml_modifier import YamlModifier
from mcp_scout.models import McpProbeResult, McpStatus
from mcp_scout.probe.engine import ProbeEngine
from mcp_scout.probe.handshake import ProtocolProber
from mcp_scout.ui import (
    console,
    create_summary_table,
    format_status_badge,
    generate_compose_snippet,
    prompt_label_configuration,
    render_catalog_json,
    render_catalog_markdown,
    render_yaml_snippet,
)

__version__ = "0.1.0"

app = typer.Typer(
    name="mcp-scout",
    help="Active Docker container discovery, protocol handshake prober, and interactive compose label injector for Model Context Protocol (MCP) servers.",
    no_args_is_help=True,
    add_completion=False,
)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"[bold cyan]mcp-scout[/bold cyan] version [bold green]{__version__}[/bold green]")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show mcp-scout version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Active Docker discovery and label injector for Model Context Protocol (MCP) servers."""


def _run_discovery(
    timeout: float = 3.0,
    max_concurrency: int = 10,
    all_containers: bool = False,
) -> list[McpProbeResult]:
    """Execute container scanning and protocol probing."""
    prober = ProtocolProber(timeout=timeout)
    engine = ProbeEngine(prober=prober, max_concurrency=max_concurrency)
    return asyncio.run(engine.discover(all_containers=all_containers))


@app.command("scan")
def scan_command(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output full probe results in JSON format.",
    ),
    unlabeled_only: bool = typer.Option(
        False,
        "--unlabeled-only",
        "-u",
        help="Filter to show only unlabeled or suspected MCP containers.",
    ),
    all_containers: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Include non-MCP containers in output.",
    ),
    timeout: float = typer.Option(
        3.0,
        "--timeout",
        "-t",
        help="Handshake timeout in seconds.",
    ),
    concurrency: int = typer.Option(
        10,
        "--concurrency",
        "-c",
        help="Max concurrent container probes.",
    ),
) -> None:
    """Scan Docker containers and probe for active MCP endpoints."""
    results = _run_discovery(timeout=timeout, max_concurrency=concurrency, all_containers=all_containers)

    if unlabeled_only:
        results = [
            r for r in results
            if r.status in (McpStatus.VERIFIED_UNLABELED, McpStatus.SUSPECTED)
        ]

    if json_output:
        typer.echo(render_catalog_json(results))
    else:
        table = create_summary_table(results, show_all=all_containers)
        console.print(table)


@app.command("interactive")
def interactive_command(
    timeout: float = typer.Option(
        3.0,
        "--timeout",
        "-t",
        help="Handshake timeout in seconds.",
    ),
    concurrency: int = typer.Option(
        10,
        "--concurrency",
        "-c",
        help="Max concurrent container probes.",
    ),
    search_root: Optional[Path] = typer.Option(
        None,
        "--search-root",
        "-r",
        help="Root directory to search for docker-compose files.",
    ),
    unlabeled_only: bool = typer.Option(
        True,
        "--unlabeled-only/--all-mcp",
        help="Target only unlabeled/suspected containers (default) or all verified MCP containers.",
    ),
) -> None:
    """Interactively walk through discovered MCP containers and inject Compose labels."""
    console.print("[bold cyan]Scanning running containers for MCP capabilities...[/bold cyan]")
    results = _run_discovery(timeout=timeout, max_concurrency=concurrency)

    # Show summary table first
    console.print(create_summary_table(results, show_all=False))

    # Filter target containers
    if unlabeled_only:
        targets = [
            r for r in results
            if r.status in (McpStatus.VERIFIED_UNLABELED, McpStatus.SUSPECTED)
        ]
    else:
        targets = [
            r for r in results
            if r.is_mcp or r.status == McpStatus.SUSPECTED
        ]

    if not targets:
        console.print("[green]No unlabeled MCP servers detected that require configuration.[/green]")
        return

    locator = ComposeLocator(search_root=search_root)
    modifier = YamlModifier()

    for r in targets:
        prompt_result = prompt_label_configuration(r)
        if prompt_result is None:
            console.print("[dim]Aborted by user.[/dim]")
            break

        config, attach_net, action = prompt_result

        if action == "apply":
            try:
                compose_file, service_name = locator.find_compose_file(
                    r.container, search_root=search_root
                )
                success = modifier.inject_mcp_labels(
                    compose_file=compose_file,
                    service_name=service_name,
                    config=config,
                    attach_network=attach_net,
                    create_backup=True,
                )
                if success:
                    console.print(
                        f"[bold green]✔ Successfully injected labels into {compose_file} (service: {service_name})[/bold green]"
                    )
                else:
                    console.print(
                        f"[bold red]✘ Failed to write labels to {compose_file}[/bold red]"
                    )
            except FileNotFoundError:
                console.print(
                    f"[bold yellow]⚠ Could not locate docker-compose.yaml for container '{r.container.name}'[/bold yellow]"
                )
                console.print("Here is the configuration snippet you can add manually:\n")
                snippet = generate_compose_snippet(
                    r.container.service_name, config, attach_network=attach_net
                )
                console.print(render_yaml_snippet(snippet))

        elif action == "snippet":
            snippet = generate_compose_snippet(
                r.container.service_name, config, attach_network=attach_net
            )
            console.print("\n[bold]Generated Docker Compose snippet:[/bold]")
            console.print(render_yaml_snippet(snippet))

        elif action == "skip":
            console.print(f"[dim]Skipped {r.container.name}.[/dim]")


@app.command("catalog")
def catalog_command(
    output_format: str = typer.Option(
        "markdown",
        "--output-format",
        "-f",
        help="Catalog format: 'markdown' or 'json'.",
    ),
    output_file: Optional[Path] = typer.Option(
        None,
        "--output-file",
        "-o",
        help="Path to write catalog output to (defaults to stdout).",
    ),
    unlabeled_only: bool = typer.Option(
        False,
        "--unlabeled-only",
        "-u",
        help="Include only unlabeled/suspected containers.",
    ),
    all_containers: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Include non-MCP containers in the catalog.",
    ),
    timeout: float = typer.Option(
        3.0,
        "--timeout",
        "-t",
        help="Handshake timeout in seconds.",
    ),
    concurrency: int = typer.Option(
        10,
        "--concurrency",
        "-c",
        help="Max concurrent container probes.",
    ),
) -> None:
    """Export a catalog of discovered MCP servers in Markdown or JSON format."""
    results = _run_discovery(timeout=timeout, max_concurrency=concurrency, all_containers=all_containers)

    if unlabeled_only:
        results = [
            r for r in results
            if r.status in (McpStatus.VERIFIED_UNLABELED, McpStatus.SUSPECTED)
        ]
    elif not all_containers:
        results = [
            r for r in results
            if r.is_mcp or r.status == McpStatus.SUSPECTED
        ]

    fmt = output_format.strip().lower()
    if fmt == "json":
        content = render_catalog_json(results)
    else:
        content = render_catalog_markdown(results)

    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(content, encoding="utf-8")
        console.print(f"[bold green]✔ MCP catalog successfully written to {output_file}[/bold green]")
    else:
        typer.echo(content)


if __name__ == "__main__":
    app()
