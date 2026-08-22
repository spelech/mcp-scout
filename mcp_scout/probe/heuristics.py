"""Rule-based heuristics evaluator for identifying MCP candidates and endpoints."""

from __future__ import annotations

import re
from typing import Sequence

from mcp_scout.models import ContainerInfo, McpType, ProbeCandidate

MCP_IMAGE_KEYWORDS = [
    "mcp",
    "fastmcp",
    "supergateway",
    "mcp-server",
    "modelcontextprotocol",
    "context7",
    "brave-search",
    "filesystem-mcp",
    "postgres-mcp",
    "sqlite-mcp",
    "fetch-mcp",
    "puppeteer-mcp",
    "github-mcp",
]

MCP_COMMAND_KEYWORDS = [
    "fastmcp",
    "supergateway",
    "mcp-server",
    "mcp-proxy",
    "mcp_server",
    "@modelcontextprotocol",
]

MCP_ENV_PREFIXES = [
    "FASTMCP_",
    "MCP_",
]

DEFAULT_FALLBACK_PORTS = [8000, 3000, 8080, 8001]

COMMON_PROBE_PATHS: list[tuple[str, McpType]] = [
    ("/mcp", McpType.HTTP),
    ("/sse", McpType.SSE),
    ("/", McpType.HTTP),
    ("/api/mcp", McpType.HTTP),
    ("/mcp/sse", McpType.SSE),
    ("/sse/v1", McpType.SSE),
    ("/healthz", McpType.HTTP),
]


class HeuristicsEvaluator:
    """Evaluates container metadata using rule-based heuristics to generate probe candidates."""

    def __init__(
        self,
        fallback_ports: Sequence[int] | None = None,
    ) -> None:
        """Initialize the heuristics evaluator.
        
        Args:
            fallback_ports: Port numbers to evaluate if container exposes no ports.
        """
        self.fallback_ports = list(fallback_ports) if fallback_ports is not None else DEFAULT_FALLBACK_PORTS

    def is_suspected_mcp(self, container: ContainerInfo) -> bool:
        """Determine whether the container exhibits strong indicators of being an MCP server.
        
        Args:
            container: Container information to analyze.
            
        Returns:
            True if container matches MCP heuristics, False otherwise.
        """
        if container.is_mcp_labeled:
            return True

        # Check environment variables
        for env_key in container.env_vars.keys():
            upper_key = env_key.upper()
            if any(upper_key.startswith(p) for p in MCP_ENV_PREFIXES):
                return True

        # Check image name
        image_lower = container.image.lower()
        if any(kw in image_lower for kw in MCP_IMAGE_KEYWORDS):
            return True

        # Check container name and compose service name
        name_lower = container.name.lower()
        service_lower = container.service_name.lower()
        if "mcp" in name_lower or "fastmcp" in name_lower:
            return True
        if "mcp" in service_lower or "fastmcp" in service_lower:
            return True

        # Check command and entrypoint
        cmd_str = (container.command or "").lower()
        entry_str = (container.entrypoint or "").lower()
        if any(kw in cmd_str for kw in MCP_COMMAND_KEYWORDS):
            return True
        if any(kw in entry_str for kw in MCP_COMMAND_KEYWORDS):
            return True

        return False

    def score_container(self, container: ContainerInfo) -> int:
        """Calculate a heuristic confidence score (0 - 100) that container is an MCP server.
        
        Args:
            container: Container information to score.
            
        Returns:
            Integer confidence score from 0 to 100.
        """
        if container.is_mcp_labeled:
            return 100

        score = 0
        upper_env_keys = [k.upper() for k in container.env_vars.keys()]
        if any(any(k.startswith(p) for p in MCP_ENV_PREFIXES) for k in upper_env_keys):
            score += 50

        image_lower = container.image.lower()
        if any(kw in image_lower for kw in MCP_IMAGE_KEYWORDS):
            score += 60

        name_lower = container.name.lower()
        service_lower = container.service_name.lower()
        if "mcp" in name_lower or "mcp" in service_lower or "fastmcp" in name_lower or "fastmcp" in service_lower:
            score += 30

        cmd_str = (container.command or "").lower()
        entry_str = (container.entrypoint or "").lower()
        if any(kw in cmd_str for kw in MCP_COMMAND_KEYWORDS) or any(kw in entry_str for kw in MCP_COMMAND_KEYWORDS):
            score += 40

        return min(score, 100)

    def generate_candidates(self, container: ContainerInfo) -> list[ProbeCandidate]:
        """Generate prioritized, deduplicated probe candidates for a container.
        
        Args:
            container: Container information to evaluate.
            
        Returns:
            Ordered list of ProbeCandidate instances.
        """
        candidates: list[ProbeCandidate] = []

        # 1. Existing explicit MCP labels
        if container.existing_mcp_labels:
            mcp_port_str = container.existing_mcp_labels.get("mcp.port")
            if mcp_port_str and mcp_port_str.isdigit():
                port = int(mcp_port_str)
                path = container.existing_mcp_labels.get("mcp.path", "/mcp")
                type_str = container.existing_mcp_labels.get("mcp.type", "http").lower()
                candidate_type = McpType.SSE if type_str == "sse" else McpType.HTTP
                candidates.append(
                    ProbeCandidate(
                        port=port,
                        path=path,
                        candidate_type=candidate_type,
                        source="labels",
                    )
                )

        # 2. Explicit Environment Variables
        env_ports: list[int] = []
        for port_var in ["FASTMCP_PORT", "MCP_PORT", "PORT", "SERVER_PORT", "APP_PORT", "HTTP_PORT"]:
            val = container.env_vars.get(port_var)
            if val and val.isdigit():
                env_ports.append(int(val))

        env_path = container.env_vars.get("MCP_PATH") or container.env_vars.get("FASTMCP_PATH")
        env_type_raw = container.env_vars.get("MCP_TRANSPORT") or container.env_vars.get("MCP_TYPE")
        env_type = (
            McpType.SSE
            if env_type_raw and "sse" in env_type_raw.lower()
            else (McpType.HTTP if env_type_raw else None)
        )

        for port in env_ports:
            if env_path:
                candidates.append(
                    ProbeCandidate(
                        port=port,
                        path=env_path,
                        candidate_type=env_type or McpType.HTTP,
                        source="env:custom",
                    )
                )
            # Add standard fastmcp/mcp paths for env ports
            candidates.append(
                ProbeCandidate(
                    port=port,
                    path="/mcp",
                    candidate_type=McpType.HTTP,
                    source="env:fastmcp",
                )
            )
            candidates.append(
                ProbeCandidate(
                    port=port,
                    path="/sse",
                    candidate_type=McpType.SSE,
                    source="env:fastmcp",
                )
            )

        # 3. Ports from Exposed Ports or Fallbacks
        target_ports: list[int] = container.exposed_ports if container.exposed_ports else self.fallback_ports

        # Determine source tag
        if container.is_mcp_labeled:
            base_source = "heuristics:labeled"
        elif self.is_suspected_mcp(container):
            base_source = "heuristics:suspected"
        else:
            base_source = "heuristics:generic"

        for port in target_ports:
            for path, candidate_type in COMMON_PROBE_PATHS:
                candidates.append(
                    ProbeCandidate(
                        port=port,
                        path=path,
                        candidate_type=candidate_type,
                        source=f"{base_source}:{path.strip('/') or 'root'}",
                    )
                )

        # 4. Deduplication preserving priority order
        deduped: list[ProbeCandidate] = []
        seen: set[tuple[int, str, McpType]] = set()
        for c in candidates:
            key = (c.port, c.path, c.candidate_type)
            if key not in seen:
                seen.add(key)
                deduped.append(c)

        return deduped
