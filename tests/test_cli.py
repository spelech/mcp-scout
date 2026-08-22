"""Tests for Typer CLI commands in mcp-scout."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from mcp_scout.cli import app
from mcp_scout.models import (
    ContainerInfo,
    LabelConfig,
    McpProbeResult,
    McpStatus,
    McpType,
)

runner = CliRunner()


@pytest.fixture
def sample_results() -> list[McpProbeResult]:
    """Sample discovery results for CLI testing."""
    c1 = ContainerInfo(
        id="c11111111111",
        name="weather-server",
        image="mcp/weather:latest",
        ip_addresses={"net_mcp": "172.20.0.10"},
        exposed_ports=[8000],
        labels={"com.docker.compose.service": "weather"},
        existing_mcp_labels={"mcp.enabled": "true", "mcp.port": "8000"},
    )
    r1 = McpProbeResult(
        container=c1,
        status=McpStatus.VERIFIED_LABELED,
        mcp_type=McpType.HTTP,
        port=8000,
        path="/mcp",
        server_name="weather-server",
        protocol_version="2024-11-05",
        tools_count=3,
        resources_count=1,
        prompts_count=0,
    )

    c2 = ContainerInfo(
        id="c22222222222",
        name="notes-rag",
        image="ghcr.io/mcp/notes-rag:latest",
        ip_addresses={"net_mcp": "172.20.0.11"},
        exposed_ports=[8080],
        labels={"com.docker.compose.service": "notes-rag"},
        existing_mcp_labels={},
    )
    r2 = McpProbeResult(
        container=c2,
        status=McpStatus.VERIFIED_UNLABELED,
        mcp_type=McpType.SSE,
        port=8080,
        path="/sse",
        server_name="notes-rag",
        protocol_version="2024-11-05",
        tools_count=5,
        resources_count=2,
        prompts_count=1,
    )

    c3 = ContainerInfo(
        id="c33333333333",
        name="fastmcp-app",
        image="my-fastmcp:latest",
        ip_addresses={"bridge": "172.17.0.4"},
        exposed_ports=[8000],
        labels={"com.docker.compose.service": "fastmcp"},
        existing_mcp_labels={},
    )
    r3 = McpProbeResult(
        container=c3,
        status=McpStatus.SUSPECTED,
        port=8000,
        error_message="Matches MCP heuristics but active probe failed",
    )

    c4 = ContainerInfo(
        id="c44444444444",
        name="redis-cache",
        image="redis:7-alpine",
        ip_addresses={"bridge": "172.17.0.2"},
        exposed_ports=[6379],
        labels={},
        existing_mcp_labels={},
    )
    r4 = McpProbeResult(
        container=c4,
        status=McpStatus.NOT_MCP,
    )

    return [r1, r2, r3, r4]


def test_cli_help():
    """Verify --help displays available CLI commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "scan" in result.stdout
    assert "interactive" in result.stdout
    assert "catalog" in result.stdout


def test_cli_version():
    """Verify --version option outputs package version."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_scan_table_output(sample_results):
    """Test standard scan command rendering table output."""
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = sample_results
        result = runner.invoke(app, ["scan"])
        assert result.exit_code == 0
        assert "weather-server" in result.stdout
        assert "notes-rag" in result.stdout
        assert "VERIFIED_LABELED" in result.stdout
        assert "VERIFIED_UNLABELED" in result.stdout


def test_scan_all_containers_flag(sample_results):
    """Test scan command with --all flag includes NOT_MCP containers."""
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = sample_results
        result = runner.invoke(app, ["scan", "--all"])
        assert result.exit_code == 0
        assert "redis-cache" in result.stdout
        assert "NOT_MCP" in result.stdout


def test_scan_json_output(sample_results):
    """Test scan command with --json flag outputs valid JSON array."""
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = sample_results
        result = runner.invoke(app, ["scan", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 4
        assert data[0]["container"]["name"] == "weather-server"
        assert data[1]["status"] == "VERIFIED_UNLABELED"


def test_scan_unlabeled_only(sample_results):
    """Test scan command with --unlabeled-only flag filters results."""
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = sample_results
        result = runner.invoke(app, ["scan", "--unlabeled-only", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        names = [d["container"]["name"] for d in data]
        assert "notes-rag" in names
        assert "fastmcp-app" in names
        assert "weather-server" not in names


def test_catalog_markdown_stdout(sample_results):
    """Test catalog command default markdown output to stdout."""
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = sample_results
        result = runner.invoke(app, ["catalog", "--output-format", "markdown"])
        assert result.exit_code == 0
        assert "# MCP Service Catalog" in result.stdout
        assert "weather-server" in result.stdout
        assert "notes-rag" in result.stdout


def test_catalog_json_stdout(sample_results):
    """Test catalog command with JSON format to stdout."""
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = sample_results
        result = runner.invoke(app, ["catalog", "-f", "json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) >= 2


def test_catalog_file_output(tmp_path: Path, sample_results):
    """Test catalog command writing output to a file."""
    out_file = tmp_path / "catalog.md"
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = sample_results
        result = runner.invoke(app, ["catalog", "-o", str(out_file)])
        assert result.exit_code == 0
        assert out_file.is_file()
        content = out_file.read_text()
        assert "# MCP Service Catalog" in content


def test_catalog_empty_results():
    """Test catalog output when no MCP services are discovered."""
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [
            McpProbeResult(
                container=ContainerInfo(id="c1", name="redis", image="redis:latest"),
                status=McpStatus.NOT_MCP,
            )
        ]
        result = runner.invoke(app, ["catalog"])
        assert result.exit_code == 0
        assert "No MCP services discovered" in result.stdout


def test_interactive_no_candidates():
    """Test interactive command when no unlabeled MCP candidates are found."""
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover:
        # Only non-mcp and already-labeled
        mock_discover.return_value = [
            McpProbeResult(
                container=ContainerInfo(
                    id="1", name="redis", image="redis:latest", labels={}
                ),
                status=McpStatus.NOT_MCP,
            )
        ]
        result = runner.invoke(app, ["interactive"])
        assert result.exit_code == 0
        assert "No unlabeled MCP servers detected" in result.stdout


def test_interactive_apply_success(sample_results, tmp_path: Path):
    """Test interactive workflow applying labels to located compose file."""
    cfg = LabelConfig(
        mcp_enabled=True,
        mcp_id="notes-rag",
        mcp_display_name="Notes Rag",
        mcp_port=8080,
        mcp_type="sse",
        mcp_path="/sse",
        mcp_categories=["productivity"],
    )

    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover, \
         patch("mcp_scout.cli.prompt_label_configuration") as mock_prompt, \
         patch("mcp_scout.cli.ComposeLocator.find_compose_file") as mock_locator, \
         patch("mcp_scout.cli.YamlModifier.inject_mcp_labels") as mock_inject:

        mock_discover.return_value = [sample_results[1]]
        mock_prompt.return_value = (cfg, "net_mcp", "apply")
        mock_locator.return_value = (tmp_path / "docker-compose.yaml", "notes-rag")
        mock_inject.return_value = True

        result = runner.invoke(app, ["interactive"])
        assert result.exit_code == 0
        assert mock_inject.called
        assert "Successfully injected labels" in result.stdout


def test_interactive_file_not_found(sample_results):
    """Test interactive workflow when ComposeLocator cannot find docker-compose.yaml."""
    cfg = LabelConfig(
        mcp_enabled=True,
        mcp_id="notes-rag",
        mcp_display_name="Notes Rag",
        mcp_port=8080,
        mcp_type="sse",
        mcp_path="/sse",
    )

    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover, \
         patch("mcp_scout.cli.prompt_label_configuration") as mock_prompt, \
         patch("mcp_scout.cli.ComposeLocator.find_compose_file") as mock_locator:

        mock_discover.return_value = [sample_results[1]]
        mock_prompt.return_value = (cfg, "net_mcp", "apply")
        mock_locator.side_effect = FileNotFoundError("Not found")

        result = runner.invoke(app, ["interactive"])
        assert result.exit_code == 0
        assert "Could not locate docker-compose.yaml" in result.stdout
        assert "mcp.enabled=true" in result.stdout


def test_interactive_injection_failure(sample_results, tmp_path: Path):
    """Test interactive workflow when YAML modification returns False."""
    cfg = LabelConfig(
        mcp_enabled=True,
        mcp_id="notes-rag",
        mcp_port=8080,
    )

    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover, \
         patch("mcp_scout.cli.prompt_label_configuration") as mock_prompt, \
         patch("mcp_scout.cli.ComposeLocator.find_compose_file") as mock_locator, \
         patch("mcp_scout.cli.YamlModifier.inject_mcp_labels") as mock_inject:

        mock_discover.return_value = [sample_results[1]]
        mock_prompt.return_value = (cfg, None, "apply")
        mock_locator.return_value = (tmp_path / "docker-compose.yaml", "notes-rag")
        mock_inject.return_value = False

        result = runner.invoke(app, ["interactive"])
        assert result.exit_code == 0
        assert "Failed to write labels" in result.stdout


def test_interactive_snippet_action(sample_results):
    """Test interactive workflow choosing to print snippet."""
    cfg = LabelConfig(
        mcp_enabled=True,
        mcp_id="notes-rag",
        mcp_display_name="Notes Rag",
        mcp_port=8080,
        mcp_type="sse",
        mcp_path="/sse",
    )

    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover, \
         patch("mcp_scout.cli.prompt_label_configuration") as mock_prompt:

        mock_discover.return_value = [sample_results[1]]
        mock_prompt.return_value = (cfg, "net_mcp", "snippet")

        result = runner.invoke(app, ["interactive"])
        assert result.exit_code == 0
        assert "mcp.enabled=true" in result.stdout
        assert "mcp.id=notes-rag" in result.stdout


def test_interactive_skip_action(sample_results):
    """Test interactive workflow choosing to skip a container."""
    cfg = LabelConfig(
        mcp_enabled=True,
        mcp_id="notes-rag",
        mcp_display_name="Notes Rag",
        mcp_port=8080,
    )

    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover, \
         patch("mcp_scout.cli.prompt_label_configuration") as mock_prompt:

        mock_discover.return_value = [sample_results[1]]
        mock_prompt.return_value = (cfg, None, "skip")

        result = runner.invoke(app, ["interactive"])
        assert result.exit_code == 0
        assert "Skipped" in result.stdout


def test_interactive_user_abort(sample_results):
    """Test interactive workflow when user aborts questionnaire."""
    with patch("mcp_scout.cli.ProbeEngine.discover", new_callable=AsyncMock) as mock_discover, \
         patch("mcp_scout.cli.prompt_label_configuration") as mock_prompt:

        mock_discover.return_value = [sample_results[1]]
        mock_prompt.return_value = None

        result = runner.invoke(app, ["interactive"])
        assert result.exit_code == 0
        assert "Aborted by user" in result.stdout
