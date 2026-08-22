"""Rich terminal presentation layer and interactive prompts for mcp-scout."""

from __future__ import annotations

import json
from typing import Any

import questionary
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from mcp_scout.models import LabelConfig, McpProbeResult, McpStatus, McpType

console = Console()


def format_status_badge(status: McpStatus | str) -> str:
    """Return colored markup string for a given McpStatus."""
    s = str(status)
    if s == McpStatus.VERIFIED_LABELED.value:
        return "[bold green]VERIFIED_LABELED[/bold green]"
    elif s == McpStatus.VERIFIED_UNLABELED.value:
        return "[bold yellow]VERIFIED_UNLABELED[/bold yellow]"
    elif s == McpStatus.SUSPECTED.value:
        return "[bold cyan]SUSPECTED[/bold cyan]"
    elif s == McpStatus.NOT_MCP.value:
        return "[dim]NOT_MCP[/dim]"
    return f"[white]{s}[/white]"


def create_summary_table(
    results: list[McpProbeResult],
    title: str = "MCP Server Discovery & Probe Results",
    show_all: bool = False,
) -> Table:
    """Create a formatted Rich Table summarizing container probe results.

    Args:
        results: List of probe results to display.
        title: Table title header.
        show_all: If True, include NOT_MCP containers; otherwise filter them out.

    Returns:
        Rich Table object ready for printing.
    """
    table = Table(
        title=f"[bold]{title}[/bold]",
        box=box.ROUNDED,
        header_style="bold magenta",
        show_lines=False,
    )

    table.add_column("Container", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center", no_wrap=True)
    table.add_column("Transport", justify="center")
    table.add_column("Endpoint URL", style="green")
    table.add_column("Protocol Version", justify="center")
    table.add_column("Tools/Res/Prompts", justify="center")
    table.add_column("Existing Labels", justify="center")

    filtered = results if show_all else [r for r in results if r.status != McpStatus.NOT_MCP]

    for r in filtered:
        status_badge = format_status_badge(r.status)
        transport = str(r.mcp_type.value) if r.mcp_type else "-"
        endpoint = "-"
        if r.port and r.path:
            ip = r.container.primary_ip or "127.0.0.1"
            endpoint = f"http://{ip}:{r.port}{r.path}"
        elif r.port:
            endpoint = f":{r.port}"

        proto = r.protocol_version or "-"
        trp = f"{r.tools_count} / {r.resources_count} / {r.prompts_count}" if r.is_mcp else "-"
        labeled = "[green]Yes[/green]" if r.container.is_mcp_labeled else "[dim]No[/dim]"

        table.add_row(
            r.container.name,
            status_badge,
            transport,
            endpoint,
            proto,
            trp,
            labeled,
        )

    return table


def generate_compose_snippet(
    service_name: str,
    config: LabelConfig,
    attach_network: str | None = None,
) -> str:
    """Generate a YAML snippet suitable for pasting into docker-compose.yaml.

    Args:
        service_name: Name of the Compose service block.
        config: LabelConfig object.
        attach_network: Optional network to attach (e.g. 'net_mcp').

    Returns:
        Formatted YAML string snippet.
    """
    labels = config.to_labels_list()
    lines = [
        "services:",
        f"  {service_name}:",
        "    labels:",
    ]
    for lbl in labels:
        lines.append(f'      - "{lbl}"')

    if attach_network:
        lines.append("    networks:")
        lines.append(f"      - {attach_network}")
        lines.append("")
        lines.append("networks:")
        lines.append(f"  {attach_network}:")
        lines.append("    external: true")

    return "\n".join(lines)


def render_yaml_snippet(yaml_str: str) -> Syntax:
    """Return syntax-highlighted YAML view."""
    return Syntax(yaml_str, "yaml", theme="monokai", line_numbers=False)


def prompt_label_configuration(
    result: McpProbeResult,
    default_network: str = "net_mcp",
) -> tuple[LabelConfig, str | None, str] | None:
    """Interactive guided questionnaire to configure MCP labels for a container.

    Args:
        result: McpProbeResult for the target container.
        default_network: Network name suggested for attachment.

    Returns:
        Tuple of (LabelConfig, attach_network or None, action) where action is
        'apply', 'snippet', or 'skip'. Returns None if user cancels.
    """
    def_config = result.generate_label_config()

    console.print()
    console.print(
        Panel(
            f"[bold cyan]Configuring MCP Labels for container:[/bold cyan] [bold white]{result.container.name}[/bold white]\n"
            f"Service: [bold]{result.container.service_name}[/bold] | Image: {result.container.image}\n"
            f"Status: {format_status_badge(result.status)}",
            box=box.ROUNDED,
            title="[bold yellow]MCP Label Configuration[/bold yellow]",
        )
    )

    try:
        # Prompt ID
        mcp_id = questionary.text(
            "MCP Service ID (mcp.id):",
            default=def_config.mcp_id,
        ).ask()
        if mcp_id is None:
            return None

        # Prompt Display Name
        disp_name = questionary.text(
            "Display Name (mcp.displayName):",
            default=def_config.mcp_display_name or def_config.mcp_id,
        ).ask()
        if disp_name is None:
            return None

        # Prompt Port
        port_str = questionary.text(
            "Container Port (mcp.port):",
            default=str(def_config.mcp_port),
        ).ask()
        if port_str is None:
            return None
        try:
            port = int(port_str)
        except ValueError:
            port = def_config.mcp_port

        # Prompt Type
        mcp_type = questionary.select(
            "Protocol Transport (mcp.type):",
            choices=["http", "sse"],
            default=def_config.mcp_type,
        ).ask()
        if mcp_type is None:
            return None

        # Prompt Path
        def_path = "/sse" if mcp_type == "sse" else def_config.mcp_path
        path = questionary.text(
            "Endpoint Path (mcp.path):",
            default=def_path,
        ).ask()
        if path is None:
            return None

        # Prompt Categories
        cat_default = ", ".join(def_config.mcp_categories) if def_config.mcp_categories else ""
        categories_str = questionary.text(
            "Categories (comma-separated, optional):",
            default=cat_default,
        ).ask()
        if categories_str is None:
            return None
        categories = [c.strip() for c in categories_str.split(",") if c.strip()]

        # Prompt attach network
        already_in_net = default_network in result.container.ip_addresses
        attach_net = None
        if not already_in_net:
            should_attach = questionary.confirm(
                f"Attach container to '{default_network}' Docker network?",
                default=True,
            ).ask()
            if should_attach is None:
                return None
            if should_attach:
                attach_net = default_network

        # Prompt action
        action = questionary.select(
            "Select action:",
            choices=[
                questionary.Choice("Apply labels to docker-compose.yaml", value="apply"),
                questionary.Choice("Print docker-compose YAML snippet", value="snippet"),
                questionary.Choice("Skip this container", value="skip"),
            ],
            default="apply",
        ).ask()
        if action is None:
            return None

        config = LabelConfig(
            mcp_enabled=True,
            mcp_id=mcp_id,
            mcp_display_name=disp_name,
            mcp_port=port,
            mcp_type=mcp_type,
            mcp_path=path,
            mcp_categories=categories,
        )

        return config, attach_net, action

    except (KeyboardInterrupt, EOFError):
        return None


def render_catalog_markdown(results: list[McpProbeResult]) -> str:
    """Format discovery results as a comprehensive Markdown catalog."""
    lines = [
        "# MCP Service Catalog",
        "",
        "Discovered Model Context Protocol (MCP) services across Docker containers.",
        "",
        "| Container | Service Name | Status | Type | Port | Path | Tools | Resources | Prompts | Version |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    mcp_results = [r for r in results if r.is_mcp or r.status == McpStatus.SUSPECTED]
    if not mcp_results:
        lines.append("| _No MCP services discovered_ | - | - | - | - | - | - | - | - | - |")
    else:
        for r in mcp_results:
            st = r.status.value
            tp = str(r.mcp_type.value) if r.mcp_type else "-"
            pt = str(r.port or "-")
            pa = r.path or "-"
            tc = str(r.tools_count)
            rc = str(r.resources_count)
            pc = str(r.prompts_count)
            ver = r.protocol_version or "-"
            lines.append(
                f"| `{r.container.name}` | `{r.container.service_name}` | **{st}** | {tp} | {pt} | `{pa}` | {tc} | {rc} | {pc} | {ver} |"
            )

    lines.append("")
    lines.append("## Service Details")
    lines.append("")

    for r in mcp_results:
        lines.append(f"### {r.container.name} (`{r.container.service_name}`)")
        lines.append(f"- **Status**: {r.status.value}")
        if r.server_name:
            lines.append(f"- **Server Name**: {r.server_name}")
        if r.server_version:
            lines.append(f"- **Server Version**: {r.server_version}")
        if r.protocol_version:
            lines.append(f"- **MCP Protocol Version**: {r.protocol_version}")
        if r.port and r.path:
            lines.append(f"- **Endpoint**: `http://{r.container.primary_ip or '127.0.0.1'}:{r.port}{r.path}`")
        lines.append(f"- **Capabilities Summary**: {r.tools_count} tools, {r.resources_count} resources, {r.prompts_count} prompts")
        if r.container.existing_mcp_labels:
            lines.append("- **Existing MCP Labels**:")
            for k, v in r.container.existing_mcp_labels.items():
                lines.append(f"  - `{k}={v}`")
        if r.error_message:
            lines.append(f"- **Probe Notes/Error**: {r.error_message}")
        lines.append("")

    return "\n".join(lines)


def render_catalog_json(results: list[McpProbeResult], indent: int = 2) -> str:
    """Serialize probe results to JSON string."""
    data = [r.model_dump(mode="json") for r in results]
    return json.dumps(data, indent=indent)
