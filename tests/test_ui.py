"""Tests for UI formatting and interactive prompts in mcp_scout.ui."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from rich.table import Table

from mcp_scout.models import (
    ContainerInfo,
    LabelConfig,
    McpProbeResult,
    McpStatus,
    McpType,
)
from mcp_scout.ui import (
    create_summary_table,
    format_status_badge,
    generate_compose_snippet,
    prompt_label_configuration,
    render_catalog_json,
    render_catalog_markdown,
    render_yaml_snippet,
)


@pytest.fixture
def sample_result() -> McpProbeResult:
    c = ContainerInfo(
        id="c12345678901",
        name="test-server",
        image="test/server:latest",
        ip_addresses={"bridge": "172.17.0.5"},
        exposed_ports=[8000],
        labels={"com.docker.compose.service": "server-service"},
    )
    return McpProbeResult(
        container=c,
        status=McpStatus.VERIFIED_UNLABELED,
        mcp_type=McpType.HTTP,
        port=8000,
        path="/mcp",
        server_name="test-server",
        server_version="1.0.0",
        protocol_version="2024-11-05",
        tools_count=4,
        resources_count=2,
        prompts_count=1,
    )


def test_format_status_badge():
    """Verify status badge colors and formatting."""
    assert "green" in format_status_badge(McpStatus.VERIFIED_LABELED)
    assert "yellow" in format_status_badge(McpStatus.VERIFIED_UNLABELED)
    assert "cyan" in format_status_badge(McpStatus.SUSPECTED)
    assert "dim" in format_status_badge(McpStatus.NOT_MCP)
    assert "CUSTOM" in format_status_badge("CUSTOM")


def test_create_summary_table(sample_result):
    """Test generating a Rich Table from probe results."""
    not_mcp = McpProbeResult(
        container=ContainerInfo(id="c2", name="redis", image="redis"),
        status=McpStatus.NOT_MCP,
    )
    table = create_summary_table([sample_result, not_mcp], show_all=True)
    assert isinstance(table, Table)
    assert table.row_count == 2

    # When show_all=False, NOT_MCP is excluded
    table_filtered = create_summary_table([sample_result, not_mcp], show_all=False)
    assert table_filtered.row_count == 1


def test_generate_compose_snippet():
    """Test generating compose YAML snippet from LabelConfig."""
    cfg = LabelConfig(
        mcp_enabled=True,
        mcp_id="my-service",
        mcp_display_name="My Service",
        mcp_port=8000,
        mcp_type="http",
        mcp_path="/mcp",
        mcp_categories=["tools", "productivity"],
    )
    snippet = generate_compose_snippet("my-service", cfg, attach_network="net_mcp")
    assert "services:" in snippet
    assert "my-service:" in snippet
    assert "labels:" in snippet
    assert "mcp.enabled=true" in snippet
    assert "mcp.id=my-service" in snippet
    assert "mcp.categories=tools,productivity" in snippet
    assert "net_mcp" in snippet
    assert "external: true" in snippet


def test_render_yaml_snippet():
    """Test rendering syntax highlighted snippet."""
    syntax = render_yaml_snippet("services:\n  app:\n    image: test")
    assert syntax is not None
    assert syntax.lexer.name == "YAML"


def test_render_catalog_markdown(sample_result):
    """Test rendering MCP service catalog in Markdown format."""
    md = render_catalog_markdown([sample_result])
    assert "# MCP Service Catalog" in md
    assert "test-server" in md
    assert "server-service" in md
    assert "8000" in md
    assert "/mcp" in md
    assert "4" in md


def test_render_catalog_json(sample_result):
    """Test rendering MCP service catalog in JSON format."""
    json_str = render_catalog_json([sample_result])
    data = json.loads(json_str)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["container"]["name"] == "test-server"
    assert data[0]["status"] == "VERIFIED_UNLABELED"
    assert data[0]["tools_count"] == 4


def test_prompt_label_configuration_apply(sample_result):
    """Test interactive prompt returning apply configuration."""
    with patch("questionary.text") as mock_text, \
         patch("questionary.select") as mock_select, \
         patch("questionary.confirm") as mock_confirm:

        mock_text.side_effect = [
            MagicMock(ask=lambda: "server-service"),  # id
            MagicMock(ask=lambda: "Test Server"),      # displayName
            MagicMock(ask=lambda: "8000"),             # port
            MagicMock(ask=lambda: "/mcp"),             # path
            MagicMock(ask=lambda: "tools, core"),      # categories
        ]
        mock_select.side_effect = [
            MagicMock(ask=lambda: "http"),             # type
            MagicMock(ask=lambda: "apply"),            # action
        ]
        mock_confirm.side_effect = [
            MagicMock(ask=lambda: True),               # attach net_mcp
        ]

        cfg, net, action = prompt_label_configuration(sample_result)
        assert action == "apply"
        assert net == "net_mcp"
        assert cfg.mcp_id == "server-service"
        assert cfg.mcp_display_name == "Test Server"
        assert cfg.mcp_port == 8000
        assert cfg.mcp_type == "http"
        assert cfg.mcp_path == "/mcp"
        assert cfg.mcp_categories == ["tools", "core"]


def test_prompt_label_configuration_cancel(sample_result):
    """Test interactive prompt returning None when user cancels."""
    with patch("questionary.text") as mock_text:
        mock_text.return_value = MagicMock(ask=lambda: None)
        res = prompt_label_configuration(sample_result)
        assert res is None


def test_prompt_label_configuration_invalid_port(sample_result):
    """Test fallback when non-integer port is entered."""
    with patch("questionary.text") as mock_text, \
         patch("questionary.select") as mock_select, \
         patch("questionary.confirm") as mock_confirm:

        mock_text.side_effect = [
            MagicMock(ask=lambda: "server-service"),  # id
            MagicMock(ask=lambda: "Test Server"),      # displayName
            MagicMock(ask=lambda: "invalid-port"),     # invalid port string
            MagicMock(ask=lambda: "/mcp"),             # path
            MagicMock(ask=lambda: ""),                 # categories
        ]
        mock_select.side_effect = [
            MagicMock(ask=lambda: "http"),             # type
            MagicMock(ask=lambda: "snippet"),          # action
        ]
        mock_confirm.side_effect = [
            MagicMock(ask=lambda: False),              # no network
        ]

        cfg, net, action = prompt_label_configuration(sample_result)
        assert action == "snippet"
        assert net is None
        assert cfg.mcp_port == 8000  # Fallback to default port


def test_prompt_label_configuration_already_in_net(sample_result):
    """Test prompt when container is already attached to net_mcp."""
    sample_result.container.ip_addresses["net_mcp"] = "172.20.0.10"

    with patch("questionary.text") as mock_text, \
         patch("questionary.select") as mock_select, \
         patch("questionary.confirm") as mock_confirm:

        mock_text.side_effect = [
            MagicMock(ask=lambda: "server-service"),
            MagicMock(ask=lambda: "Test Server"),
            MagicMock(ask=lambda: "8000"),
            MagicMock(ask=lambda: "/mcp"),
            MagicMock(ask=lambda: ""),
        ]
        mock_select.side_effect = [
            MagicMock(ask=lambda: "http"),
            MagicMock(ask=lambda: "skip"),
        ]

        cfg, net, action = prompt_label_configuration(sample_result)
        assert action == "skip"
        assert net is None
        assert not mock_confirm.called
