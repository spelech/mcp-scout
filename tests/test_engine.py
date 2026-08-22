"""Tests for ProbeEngine discovery and classification orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from mcp_scout.models import ContainerInfo, McpStatus, McpType, ProbeCandidate
from mcp_scout.probe.docker_scanner import DockerScanner
from mcp_scout.probe.heuristics import HeuristicsEvaluator
from mcp_scout.probe.handshake import ProtocolProber
from mcp_scout.probe.engine import ProbeEngine


@pytest.fixture
def mock_scanner():
    scanner = MagicMock(spec=DockerScanner)
    return scanner


@pytest.mark.asyncio
async def test_engine_discovery_verified_labeled(mock_scanner, mock_mcp_http_server):
    """Test discovering a container that is already labeled and verifies successfully."""
    c = ContainerInfo(
        id="c1",
        name="labeled-mcp",
        image="mcp-server:latest",
        ip_addresses={"bridge": mock_mcp_http_server.host},
        exposed_ports=[mock_mcp_http_server.port],
        existing_mcp_labels={
            "mcp.enabled": "true",
            "mcp.port": str(mock_mcp_http_server.port),
            "mcp.path": "/mcp",
            "mcp.type": "http",
        },
    )
    mock_scanner.scan_containers.return_value = [c]

    engine = ProbeEngine(
        scanner=mock_scanner,
        heuristics=HeuristicsEvaluator(),
        prober=ProtocolProber(timeout=2.0),
    )
    results = await engine.discover()

    assert len(results) == 1
    res = results[0]
    assert res.status == McpStatus.VERIFIED_LABELED
    assert res.is_mcp is True
    assert res.server_name == "mock-mcp-server"
    assert res.port == mock_mcp_http_server.port


@pytest.mark.asyncio
async def test_engine_discovery_verified_unlabeled(mock_scanner, mock_mcp_http_server):
    """Test discovering an unlabeled container matching heuristics and actively verified."""
    c = ContainerInfo(
        id="c2",
        name="unlabeled-mcp",
        image="ghcr.io/fastmcp/test-server:latest",
        ip_addresses={"bridge": mock_mcp_http_server.host},
        exposed_ports=[mock_mcp_http_server.port],
        env_vars={"FASTMCP_PORT": str(mock_mcp_http_server.port)},
    )
    mock_scanner.scan_containers.return_value = [c]

    engine = ProbeEngine(
        scanner=mock_scanner,
        heuristics=HeuristicsEvaluator(),
        prober=ProtocolProber(timeout=2.0),
    )
    results = await engine.discover()

    assert len(results) == 1
    res = results[0]
    assert res.status == McpStatus.VERIFIED_UNLABELED
    assert res.is_mcp is True
    assert res.server_name == "mock-mcp-server"


@pytest.mark.asyncio
async def test_engine_discovery_suspected_unresponsive(mock_scanner):
    """Test a container matching MCP heuristics whose ports are unreachable becomes SUSPECTED."""
    c = ContainerInfo(
        id="c3",
        name="unresponsive-mcp",
        image="fastmcp/service:latest",
        ip_addresses={"bridge": "127.0.0.1"},
        exposed_ports=[59990],
        env_vars={"FASTMCP_PORT": "59990"},
    )
    mock_scanner.scan_containers.return_value = [c]

    engine = ProbeEngine(
        scanner=mock_scanner,
        heuristics=HeuristicsEvaluator(),
        prober=ProtocolProber(timeout=0.5),
    )
    results = await engine.discover()

    assert len(results) == 1
    res = results[0]
    assert res.status == McpStatus.SUSPECTED
    assert res.is_mcp is False
    assert res.error_message is not None


@pytest.mark.asyncio
async def test_engine_discovery_suspected_labeled_unresponsive(mock_scanner):
    """Test a labeled MCP container that fails probe becomes SUSPECTED."""
    c = ContainerInfo(
        id="c4",
        name="labeled-broken",
        image="mcp-server:latest",
        ip_addresses={"bridge": "127.0.0.1"},
        exposed_ports=[59991],
        existing_mcp_labels={"mcp.enabled": "true", "mcp.port": "59991"},
    )
    mock_scanner.scan_containers.return_value = [c]

    engine = ProbeEngine(
        scanner=mock_scanner,
        heuristics=HeuristicsEvaluator(),
        prober=ProtocolProber(timeout=0.5),
    )
    results = await engine.discover()

    assert len(results) == 1
    res = results[0]
    assert res.status == McpStatus.SUSPECTED
    assert res.is_mcp is False


@pytest.mark.asyncio
async def test_engine_discovery_not_mcp(mock_scanner, mock_non_mcp_server):
    """Test a generic non-MCP container is classified as NOT_MCP."""
    c = ContainerInfo(
        id="c5",
        name="redis-cache",
        image="redis:alpine",
        ip_addresses={"bridge": mock_non_mcp_server.host},
        exposed_ports=[mock_non_mcp_server.port],
    )
    mock_scanner.scan_containers.return_value = [c]

    engine = ProbeEngine(
        scanner=mock_scanner,
        heuristics=HeuristicsEvaluator(),
        prober=ProtocolProber(timeout=1.0),
    )
    results = await engine.discover()

    assert len(results) == 1
    res = results[0]
    assert res.status == McpStatus.NOT_MCP
    assert res.is_mcp is False


@pytest.mark.asyncio
async def test_engine_discovery_no_ip_suspected_and_not_mcp(mock_scanner):
    """Test container with no IP address handled gracefully."""
    suspected_c = ContainerInfo(
        id="c6",
        name="offline-mcp",
        image="mcp-offline:latest",
        ip_addresses={},
        exposed_ports=[8000],
    )
    generic_c = ContainerInfo(
        id="c7",
        name="offline-nginx",
        image="nginx:alpine",
        ip_addresses={},
        exposed_ports=[80],
    )
    mock_scanner.scan_containers.return_value = [suspected_c, generic_c]

    engine = ProbeEngine(
        scanner=mock_scanner,
        heuristics=HeuristicsEvaluator(),
        prober=ProtocolProber(timeout=0.5),
    )
    results = await engine.discover()

    assert len(results) == 2
    assert results[0].status == McpStatus.SUSPECTED
    assert results[1].status == McpStatus.NOT_MCP


@pytest.mark.asyncio
async def test_engine_run_discovery_method(mock_scanner, mock_mcp_http_server):
    """Test run_discovery method and classmethod."""
    c = ContainerInfo(
        id="c8",
        name="test-server",
        image="fastmcp/test:latest",
        ip_addresses={"bridge": mock_mcp_http_server.host},
        exposed_ports=[mock_mcp_http_server.port],
    )
    mock_scanner.scan_containers.return_value = [c]

    engine = ProbeEngine(
        scanner=mock_scanner,
        heuristics=HeuristicsEvaluator(),
        prober=ProtocolProber(timeout=2.0),
    )
    results = await engine.run_discovery()
    assert len(results) == 1
    assert results[0].is_mcp is True


@pytest.mark.asyncio
async def test_engine_localhost_port_mapping(mock_scanner, mock_mcp_http_server):
    """Test engine translates internal port to published host port when probing localhost."""
    c = ContainerInfo(
        id="c9",
        name="published-mcp",
        image="fastmcp/test:latest",
        ip_addresses={},
        exposed_ports=[8000],
        published_ports={8000: mock_mcp_http_server.port},
    )
    mock_scanner.scan_containers.return_value = [c]

    engine = ProbeEngine(
        scanner=mock_scanner,
        heuristics=HeuristicsEvaluator(fallback_ports=[8000]),
        prober=ProtocolProber(timeout=2.0),
    )
    results = await engine.discover()
    assert len(results) == 1
    assert results[0].is_mcp is True
    assert results[0].port == 8000


@pytest.mark.asyncio
async def test_engine_empty_containers(mock_scanner):
    """Test engine handles empty container list cleanly."""
    mock_scanner.scan_containers.return_value = []
    engine = ProbeEngine(scanner=mock_scanner)
    results = await engine.discover()
    assert results == []


@pytest.mark.asyncio
async def test_engine_run_classmethod(mock_scanner, mock_mcp_http_server):
    """Test ProbeEngine.run classmethod directly."""
    c = ContainerInfo(
        id="c10",
        name="classmethod-test",
        image="mcp/test:latest",
        ip_addresses={"bridge": mock_mcp_http_server.host},
        exposed_ports=[mock_mcp_http_server.port],
    )
    mock_scanner.scan_containers.return_value = [c]

    results = await ProbeEngine.run(
        scanner=mock_scanner,
        heuristics=HeuristicsEvaluator(),
        prober=ProtocolProber(timeout=2.0),
    )
    assert len(results) == 1
    assert results[0].is_mcp is True
