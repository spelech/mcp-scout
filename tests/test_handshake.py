"""Tests for ProtocolProber active network handshake."""

from __future__ import annotations

import pytest

from mcp_scout.models import ContainerInfo, McpStatus, McpType, ProbeCandidate
from mcp_scout.probe.handshake import ProtocolProber


@pytest.mark.asyncio
async def test_probe_streamable_http_success(mock_mcp_http_server):
    """Test successful Streamable HTTP JSON-RPC initialize handshake."""
    prober = ProtocolProber(timeout=2.0)
    candidate = ProbeCandidate(
        port=mock_mcp_http_server.port,
        path="/mcp",
        candidate_type=McpType.HTTP,
    )
    res = await prober.probe_candidate(mock_mcp_http_server.host, candidate)
    assert res is not None
    assert res.is_mcp is True
    assert res.server_name == "mock-mcp-server"
    assert res.server_version == "1.0.0"
    assert res.protocol_version == "2024-11-05"
    assert res.mcp_type == McpType.HTTP
    assert res.port == mock_mcp_http_server.port
    assert res.path == "/mcp"
    assert res.tools_count == 2
    assert res.prompts_count == 1
    assert res.resources_count == 1


@pytest.mark.asyncio
async def test_probe_sse_success(mock_mcp_sse_server):
    """Test successful SSE stream connection and endpoint discovery."""
    prober = ProtocolProber(timeout=2.0)
    candidate = ProbeCandidate(
        port=mock_mcp_sse_server.port,
        path="/sse",
        candidate_type=McpType.SSE,
    )
    res = await prober.probe_candidate(mock_mcp_sse_server.host, candidate)
    assert res is not None
    assert res.is_mcp is True
    assert res.mcp_type == McpType.SSE
    assert res.server_name == "mock-sse-mcp-server"
    assert res.server_version == "2.0.0"
    assert res.port == mock_mcp_sse_server.port
    assert res.path == "/sse"


@pytest.mark.asyncio
async def test_probe_healthcheck_fallback(mock_fastmcp_health_server):
    """Test healthcheck endpoint probe fallback."""
    prober = ProtocolProber(timeout=2.0)
    candidate = ProbeCandidate(
        port=mock_fastmcp_health_server.port,
        path="/healthz",
        candidate_type=McpType.HTTP,
    )
    res = await prober.probe_candidate(mock_fastmcp_health_server.host, candidate)
    assert res is not None
    assert res.is_mcp is True
    assert res.server_name == "health-mcp-server"


@pytest.mark.asyncio
async def test_probe_non_mcp_endpoint(mock_non_mcp_server):
    """Test probing a non-MCP web endpoint returns None."""
    prober = ProtocolProber(timeout=2.0)
    candidate = ProbeCandidate(
        port=mock_non_mcp_server.port,
        path="/mcp",
        candidate_type=McpType.HTTP,
    )
    res = await prober.probe_candidate(mock_non_mcp_server.host, candidate)
    assert res is None


@pytest.mark.asyncio
async def test_probe_connection_refused():
    """Test probing an unreachable port returns None without throwing."""
    prober = ProtocolProber(timeout=1.0)
    candidate = ProbeCandidate(
        port=59998,
        path="/mcp",
        candidate_type=McpType.HTTP,
    )
    res = await prober.probe_candidate("127.0.0.1", candidate)
    assert res is None


@pytest.mark.asyncio
async def test_probe_with_labeled_and_unlabeled_containers(mock_mcp_http_server):
    """Test probe result respects container label status."""
    prober = ProtocolProber(timeout=2.0)
    candidate = ProbeCandidate(
        port=mock_mcp_http_server.port,
        path="/mcp",
        candidate_type=McpType.HTTP,
    )

    unlabeled = ContainerInfo(
        id="c1",
        name="unlabeled-server",
        image="sample-image",
        ip_addresses={"bridge": mock_mcp_http_server.host},
        exposed_ports=[mock_mcp_http_server.port],
    )
    res_unlabeled = await prober.probe_candidate(mock_mcp_http_server.host, candidate, container=unlabeled)
    assert res_unlabeled is not None
    assert res_unlabeled.status == McpStatus.VERIFIED_UNLABELED

    labeled = ContainerInfo(
        id="c2",
        name="labeled-server",
        image="sample-image",
        ip_addresses={"bridge": mock_mcp_http_server.host},
        exposed_ports=[mock_mcp_http_server.port],
        existing_mcp_labels={"mcp.enabled": "true"},
    )
    res_labeled = await prober.probe_candidate(mock_mcp_http_server.host, candidate, container=labeled)
    assert res_labeled is not None
    assert res_labeled.status == McpStatus.VERIFIED_LABELED


@pytest.mark.asyncio
async def test_probe_with_external_client(mock_mcp_http_server):
    """Test ProtocolProber works with a pre-configured external AsyncClient."""
    import httpx
    async with httpx.AsyncClient() as client:
        prober = ProtocolProber(timeout=2.0, client=client)
        candidate = ProbeCandidate(
            port=mock_mcp_http_server.port,
            path="/mcp",
            candidate_type=McpType.HTTP,
        )
        res = await prober.probe_candidate(mock_mcp_http_server.host, candidate)
        assert res is not None
        assert res.is_mcp is True


@pytest.mark.asyncio
async def test_probe_transport_fallback_http_to_sse(mock_mcp_sse_server):
    """Test fallback when candidate type is HTTP but server is SSE."""
    prober = ProtocolProber(timeout=2.0)
    candidate = ProbeCandidate(
        port=mock_mcp_sse_server.port,
        path="/sse",
        candidate_type=McpType.HTTP,
    )
    res = await prober.probe_candidate(mock_mcp_sse_server.host, candidate)
    assert res is not None
    assert res.is_mcp is True
    assert res.mcp_type == McpType.SSE


@pytest.mark.asyncio
async def test_probe_transport_fallback_sse_to_http(mock_mcp_http_server):
    """Test fallback when candidate type is SSE but server is HTTP."""
    prober = ProtocolProber(timeout=2.0)
    candidate = ProbeCandidate(
        port=mock_mcp_http_server.port,
        path="/mcp",
        candidate_type=McpType.SSE,
    )
    res = await prober.probe_candidate(mock_mcp_http_server.host, candidate)
    assert res is not None
    assert res.is_mcp is True
    assert res.mcp_type == McpType.HTTP
