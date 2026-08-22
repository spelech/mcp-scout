"""Pytest configuration and shared fixtures for mcp-scout tests."""

import pytest


@pytest.fixture
def sample_container_info_dict():
    return {
        "id": "c1234567890abcdef",
        "name": "sample-mcp-server",
        "image": "ghcr.io/sample/mcp-server:latest",
        "ip_addresses": {"net_mcp": "172.20.0.10", "bridge": "172.17.0.2"},
        "exposed_ports": [8080, 8443],
        "env_vars": {"MCP_PORT": "8080", "FASTMCP_PORT": "8080"},
        "labels": {
            "com.docker.compose.service": "sample-service",
            "com.docker.compose.project.working_dir": "/containers/mcp",
            "com.docker.compose.project.config_files": "/containers/mcp/docker-compose.yaml",
        },
        "existing_mcp_labels": {},
    }
