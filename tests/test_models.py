"""Tests for mcp-scout core data models and enums."""

import pytest
from mcp_scout.models import (
    ContainerInfo,
    LabelConfig,
    McpProbeResult,
    McpStatus,
    McpType,
    ProbeCandidate,
)


def test_models_instantiation():
    container = ContainerInfo(
        id="abc12345",
        name="test-mcp-app",
        image="ghcr.io/test/mcp-app:latest",
        ip_addresses={"net_mcp": "172.20.0.5"},
        exposed_ports=[8000, 8080],
        env_vars={"FASTMCP_PORT": "8000"},
        labels={"com.docker.compose.service": "test-app"},
        existing_mcp_labels={},
    )
    assert container.name == "test-mcp-app"
    assert "FASTMCP_PORT" in container.env_vars

    result = McpProbeResult(
        container=container,
        status=McpStatus.VERIFIED_UNLABELED,
        mcp_type=McpType.HTTP,
        port=8000,
        path="/mcp",
        server_name="test-server",
        protocol_version="2024-11-05",
    )
    assert result.status == McpStatus.VERIFIED_UNLABELED

    labels = result.generate_label_config()
    assert labels.mcp_enabled is True
    assert labels.mcp_id == "test-app"
    assert labels.mcp_port == 8000
    assert labels.mcp_type == "http"
    assert labels.mcp_path == "/mcp"


def test_mcp_type_enum():
    assert McpType.SSE == "sse"
    assert McpType.HTTP == "http"
    assert McpType("sse") == McpType.SSE
    assert McpType("http") == McpType.HTTP


def test_mcp_status_enum():
    assert McpStatus.VERIFIED_LABELED == "VERIFIED_LABELED"
    assert McpStatus.VERIFIED_UNLABELED == "VERIFIED_UNLABELED"
    assert McpStatus.SUSPECTED == "SUSPECTED"
    assert McpStatus.NOT_MCP == "NOT_MCP"


def test_probe_candidate():
    candidate = ProbeCandidate(
        port=8000,
        path="/mcp",
        candidate_type=McpType.HTTP,
        source="heuristics:port",
    )
    assert candidate.port == 8000
    assert candidate.path == "/mcp"
    assert candidate.candidate_type == McpType.HTTP
    assert candidate.source == "heuristics:port"


def test_container_info_helpers():
    container = ContainerInfo(
        id="1234567890abcdef",
        name="my-container",
        image="test/image:v1",
        ip_addresses={"net_mcp": "172.20.0.12", "bridge": "172.17.0.4"},
        exposed_ports=[3000],
        labels={
            "com.docker.compose.service": "my-service",
            "com.docker.compose.project.working_dir": "/containers/custom",
            "com.docker.compose.project.config_files": "/containers/custom/docker-compose.yaml",
        },
    )
    assert container.service_name == "my-service"
    assert container.compose_working_dir == "/containers/custom"
    assert container.compose_config_files == ["/containers/custom/docker-compose.yaml"]
    assert container.primary_ip == "172.20.0.12"
    assert container.short_id == "1234567890ab"


def test_container_info_fallbacks():
    container = ContainerInfo(
        id="abcdef",
        name="raw-container",
        image="raw/image:latest",
    )
    assert container.service_name == "raw-container"
    assert container.compose_working_dir is None
    assert container.compose_config_files == []
    assert container.primary_ip is None
    assert container.short_id == "abcdef"


def test_label_config_serialization():
    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="my-app",
        mcp_display_name="My App MCP",
        mcp_port=8000,
        mcp_type="http",
        mcp_path="/mcp",
        mcp_categories=["productivity", "tools"],
    )
    labels_dict = config.to_labels_dict()
    assert labels_dict["mcp.enabled"] == "true"
    assert labels_dict["mcp.id"] == "my-app"
    assert labels_dict["mcp.displayName"] == "My App MCP"
    assert labels_dict["mcp.port"] == "8000"
    assert labels_dict["mcp.type"] == "http"
    assert labels_dict["mcp.path"] == "/mcp"
    assert labels_dict["mcp.categories"] == "productivity,tools"

    labels_list = config.to_labels_list()
    assert "mcp.enabled=true" in labels_list
    assert "mcp.id=my-app" in labels_list
    assert "mcp.displayName=My App MCP" in labels_list
    assert "mcp.port=8000" in labels_list
    assert "mcp.type=http" in labels_list
    assert "mcp.path=/mcp" in labels_list
    assert "mcp.categories=productivity,tools" in labels_list


def test_mcp_probe_result_helpers():
    container = ContainerInfo(
        id="c1",
        name="standalone-mcp",
        image="ghcr.io/repo/mcp:latest",
        ip_addresses={"net_mcp": "172.20.0.2"},
        exposed_ports=[3000],
    )
    result = McpProbeResult(
        container=container,
        status=McpStatus.VERIFIED_UNLABELED,
        mcp_type=McpType.SSE,
        port=3000,
        path="/sse",
        server_name="test-sse",
    )
    assert result.is_mcp is True
    config = result.generate_label_config()
    assert config.mcp_id == "standalone-mcp"
    assert config.mcp_port == 3000
    assert config.mcp_type == "sse"
    assert config.mcp_path == "/sse"
    assert config.mcp_display_name == "Test Sse"

    # Test fallback to container service name when server_name is None
    result_no_server = McpProbeResult(
        container=container,
        status=McpStatus.VERIFIED_UNLABELED,
        mcp_type=McpType.SSE,
        port=3000,
        path="/sse",
        server_name=None,
    )
    config_fallback = result_no_server.generate_label_config()
    assert config_fallback.mcp_display_name == "Standalone Mcp"


def test_mcp_type_and_status_str():
    assert str(McpType.SSE) == "sse"
    assert str(McpType.HTTP) == "http"
    assert str(McpStatus.VERIFIED_LABELED) == "VERIFIED_LABELED"
    assert str(McpStatus.VERIFIED_UNLABELED) == "VERIFIED_UNLABELED"
    assert str(McpStatus.SUSPECTED) == "SUSPECTED"
    assert str(McpStatus.NOT_MCP) == "NOT_MCP"


def test_container_info_primary_ip_other_networks():
    # Only custom non-mcp network
    c1 = ContainerInfo(
        id="c1",
        name="custom-net-container",
        image="test:latest",
        ip_addresses={"custom_bridge": "172.18.0.5"},
    )
    assert c1.primary_ip == "172.18.0.5"

    # Only host network with fallback
    c2 = ContainerInfo(
        id="c2",
        name="host-container",
        image="test:latest",
        ip_addresses={"host": "127.0.0.1"},
    )
    assert c2.primary_ip == "127.0.0.1"


def test_container_info_is_mcp_labeled():
    c1 = ContainerInfo(
        id="c1",
        name="unlabeled",
        image="test:latest",
        existing_mcp_labels={},
    )
    assert c1.is_mcp_labeled is False

    c2 = ContainerInfo(
        id="c2",
        name="labeled",
        image="test:latest",
        existing_mcp_labels={"mcp.enabled": "true"},
    )
    assert c2.is_mcp_labeled is True


def test_generate_label_config_overrides():
    container = ContainerInfo(
        id="c1",
        name="my-container",
        image="test:latest",
        exposed_ports=[9000],
    )
    result = McpProbeResult(
        container=container,
        status=McpStatus.VERIFIED_UNLABELED,
        mcp_type=McpType.HTTP,
        port=9000,
        path="/mcp",
    )
    custom_labels = result.generate_label_config(
        id_override="custom-id",
        display_name_override="Custom Display Name",
        port_override=9999,
        path_override="/custom/mcp",
        type_override="sse",
        categories=["ai", "tools"],
    )
    assert custom_labels.mcp_id == "custom-id"
    assert custom_labels.mcp_display_name == "Custom Display Name"
    assert custom_labels.mcp_port == 9999
    assert custom_labels.mcp_path == "/custom/mcp"
    assert custom_labels.mcp_type == "sse"
    assert custom_labels.mcp_categories == ["ai", "tools"]


def test_mcp_probe_result_not_mcp():
    container = ContainerInfo(
        id="c2",
        name="nginx",
        image="nginx:alpine",
    )
    result = McpProbeResult(
        container=container,
        status=McpStatus.NOT_MCP,
    )
    assert result.is_mcp is False

