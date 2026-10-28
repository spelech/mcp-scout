"""MCP Scout - Docker MCP container discovery, active protocol handshake prober, and compose label injector."""

__version__ = "0.1.1"

from mcp_scout.models import (
    ContainerInfo,
    LabelConfig,
    McpProbeResult,
    McpStatus,
    McpType,
    ProbeCandidate,
)

__all__ = [
    "__version__",
    "ContainerInfo",
    "LabelConfig",
    "McpProbeResult",
    "McpStatus",
    "McpType",
    "ProbeCandidate",
]
