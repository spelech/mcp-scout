"""Tests for the heuristics-based candidate endpoint evaluator."""

import pytest
from mcp_scout.models import ContainerInfo, McpType, ProbeCandidate
from mcp_scout.probe.heuristics import HeuristicsEvaluator


def test_heuristics_candidate_generation():
    container = ContainerInfo(
        id="c1",
        name="custom-fastmcp",
        image="fastmcp-test:latest",
        ip_addresses={"net_mcp": "172.20.0.10"},
        exposed_ports=[8000],
        env_vars={"FASTMCP_PORT": "8000"},
        labels={"com.docker.compose.service": "fastmcp-service"},
        existing_mcp_labels={},
    )
    evaluator = HeuristicsEvaluator()
    candidates = evaluator.generate_candidates(container)
    assert len(candidates) > 0
    assert any(c.port == 8000 and c.path == "/mcp" for c in candidates)
    assert any(c.port == 8000 and c.path == "/sse" for c in candidates)


def test_heuristics_with_existing_mcp_labels():
    container = ContainerInfo(
        id="c2",
        name="labeled-mcp",
        image="my-mcp:latest",
        ip_addresses={"net_mcp": "172.20.0.11"},
        exposed_ports=[9000],
        labels={
            "mcp.enabled": "true",
            "mcp.port": "9000",
            "mcp.path": "/custom/sse",
            "mcp.type": "sse",
        },
        existing_mcp_labels={
            "mcp.enabled": "true",
            "mcp.port": "9000",
            "mcp.path": "/custom/sse",
            "mcp.type": "sse",
        },
    )
    evaluator = HeuristicsEvaluator()
    assert evaluator.is_suspected_mcp(container) is True
    assert evaluator.score_container(container) == 100

    candidates = evaluator.generate_candidates(container)
    assert len(candidates) > 0
    first = candidates[0]
    assert first.port == 9000
    assert first.path == "/custom/sse"
    assert first.candidate_type == McpType.SSE
    assert first.source == "labels"


def test_heuristics_env_vars_priority():
    container = ContainerInfo(
        id="c3",
        name="env-mcp",
        image="custom-app:latest",
        ip_addresses={"net_mcp": "172.20.0.12"},
        exposed_ports=[3000, 8080],
        env_vars={
            "MCP_PORT": "8080",
            "MCP_PATH": "/v1/mcp",
            "MCP_TRANSPORT": "sse",
        },
    )
    evaluator = HeuristicsEvaluator()
    assert evaluator.is_suspected_mcp(container) is True
    assert evaluator.score_container(container) >= 50
    candidates = evaluator.generate_candidates(container)
    assert len(candidates) > 0
    # Should have candidate from env
    env_candidates = [c for c in candidates if "env" in c.source]
    assert len(env_candidates) > 0
    assert any(c.port == 8080 for c in env_candidates)


def test_heuristics_image_keywords():
    evaluator = HeuristicsEvaluator()
    images = [
        "ghcr.io/modelcontextprotocol/server-postgres:latest",
        "mcp/filesystem:v1.0",
        "supergateway/mcp-proxy:latest",
        "fastmcp-sqlite:latest",
        "context7/server:latest",
    ]
    for img in images:
        container = ContainerInfo(
            id="c_img",
            name="app",
            image=img,
            exposed_ports=[8000],
        )
        assert evaluator.is_suspected_mcp(container) is True
        score = evaluator.score_container(container)
        assert score >= 50
        candidates = evaluator.generate_candidates(container)
        assert len(candidates) > 0


def test_heuristics_command_entrypoint_keywords():
    evaluator = HeuristicsEvaluator()
    container_cmd = ContainerInfo(
        id="c_cmd",
        name="generic-node",
        image="node:18-alpine",
        command="npx -y @modelcontextprotocol/server-memory --port 8080",
        exposed_ports=[8080],
    )
    assert evaluator.is_suspected_mcp(container_cmd) is True
    assert evaluator.score_container(container_cmd) >= 40
    candidates = evaluator.generate_candidates(container_cmd)
    assert any(c.port == 8080 for c in candidates)

    container_entry = ContainerInfo(
        id="c_entry",
        name="python-runtime",
        image="python:3.11-slim",
        entrypoint="fastmcp run server.py",
        exposed_ports=[8000],
    )
    assert evaluator.is_suspected_mcp(container_entry) is True
    assert evaluator.score_container(container_entry) >= 40


def test_heuristics_name_and_service_keywords():
    evaluator = HeuristicsEvaluator()
    c_name = ContainerInfo(
        id="c_n",
        name="sqlite-mcp-service",
        image="alpine:latest",
    )
    assert evaluator.is_suspected_mcp(c_name) is True
    assert evaluator.score_container(c_name) >= 30

    c_svc = ContainerInfo(
        id="c_s",
        name="raw-app",
        image="alpine:latest",
        labels={"com.docker.compose.service": "notes-fastmcp"},
    )
    assert evaluator.is_suspected_mcp(c_svc) is True
    assert evaluator.score_container(c_svc) >= 30


def test_heuristics_deduplication_and_ordering():
    evaluator = HeuristicsEvaluator()
    container = ContainerInfo(
        id="c_dedup",
        name="fastmcp-app",
        image="fastmcp-app:latest",
        exposed_ports=[8000, 8000],
        env_vars={"FASTMCP_PORT": "8000"},
    )
    candidates = evaluator.generate_candidates(container)
    seen = set()
    for c in candidates:
        key = (c.port, c.path, c.candidate_type)
        assert key not in seen, f"Duplicate candidate found: {key}"
        seen.add(key)


def test_heuristics_fallback_defaults():
    evaluator = HeuristicsEvaluator(fallback_ports=[9100, 9200])
    container = ContainerInfo(
        id="c_fallback",
        name="generic-mcp-no-ports",
        image="fastmcp:latest",
        exposed_ports=[],
    )
    candidates = evaluator.generate_candidates(container)
    assert len(candidates) > 0
    ports = {c.port for c in candidates}
    assert 9100 in ports
    assert 9200 in ports


def test_heuristics_non_mcp_container():
    evaluator = HeuristicsEvaluator()
    container = ContainerInfo(
        id="c_non_mcp",
        name="redis-cache",
        image="redis:7-alpine",
        exposed_ports=[6379],
    )
    assert evaluator.is_suspected_mcp(container) is False
    assert evaluator.score_container(container) == 0
    # Even for non-suspected container, generate_candidates provides generic probes for exposed ports
    candidates = evaluator.generate_candidates(container)
    assert len(candidates) > 0
    assert all(c.port == 6379 for c in candidates)
