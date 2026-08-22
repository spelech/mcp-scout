"""Core data models and enums for mcp-scout."""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class McpType(str, Enum):
    """Transport protocol type for Model Context Protocol (MCP)."""

    SSE = "sse"
    HTTP = "http"

    def __str__(self) -> str:
        return self.value


class McpStatus(str, Enum):
    """Verification and labeling status of a container regarding MCP."""

    VERIFIED_LABELED = "VERIFIED_LABELED"
    VERIFIED_UNLABELED = "VERIFIED_UNLABELED"
    SUSPECTED = "SUSPECTED"
    NOT_MCP = "NOT_MCP"

    def __str__(self) -> str:
        return self.value


class ProbeCandidate(BaseModel):
    """Candidate endpoint to probe for MCP server capabilities."""

    port: int
    path: str = "/mcp"
    candidate_type: McpType = McpType.HTTP
    source: str = "heuristics"


class ContainerInfo(BaseModel):
    """Information extracted from a running Docker container."""

    id: str
    name: str
    image: str
    status: str = "running"
    command: str | None = None
    entrypoint: str | None = None
    ip_addresses: dict[str, str] = Field(default_factory=dict)
    exposed_ports: list[int] = Field(default_factory=list)
    published_ports: dict[int, int] = Field(default_factory=dict)
    env_vars: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    existing_mcp_labels: dict[str, str] = Field(default_factory=dict)

    @property
    def short_id(self) -> str:
        """Return 12-character truncated container ID."""
        return self.id[:12]

    @property
    def service_name(self) -> str:
        """Docker Compose service name if available, otherwise sanitized container name."""
        compose_service = self.labels.get("com.docker.compose.service")
        if compose_service:
            return compose_service
        return self.name.lstrip("/")

    @property
    def compose_working_dir(self) -> str | None:
        """Docker Compose project working directory if set in labels."""
        return self.labels.get("com.docker.compose.project.working_dir")

    @property
    def compose_config_files(self) -> list[str]:
        """List of Docker Compose config files resolved from labels."""
        raw_files = self.labels.get("com.docker.compose.project.config_files")
        if not raw_files:
            return []
        return [f.strip() for f in raw_files.split(",") if f.strip()]

    @property
    def primary_ip(self) -> str | None:
        """Primary IP address to reach the container.
        
        Prioritizes 'net_mcp', then other user-defined bridge networks, then default bridge.
        """
        if not self.ip_addresses:
            return None
        if "net_mcp" in self.ip_addresses and self.ip_addresses["net_mcp"]:
            return self.ip_addresses["net_mcp"]
        for net_name, ip in self.ip_addresses.items():
            if ip and net_name != "host":
                return ip
        return next(iter(self.ip_addresses.values()), None)

    @property
    def is_mcp_labeled(self) -> bool:
        """Whether the container currently has mcp.enabled=true."""
        return self.existing_mcp_labels.get("mcp.enabled", "").strip().lower() == "true"


class LabelConfig(BaseModel):
    """Configuration for standard mcp.* Docker labels."""

    mcp_enabled: bool = True
    mcp_id: str
    mcp_display_name: str | None = None
    mcp_port: int
    mcp_type: str = "http"
    mcp_path: str = "/mcp"
    mcp_categories: list[str] = Field(default_factory=list)

    def to_labels_dict(self) -> dict[str, str]:
        """Convert configuration to standard mcp.* key-value pairs."""
        labels: dict[str, str] = {
            "mcp.enabled": "true" if self.mcp_enabled else "false",
            "mcp.id": self.mcp_id,
            "mcp.port": str(self.mcp_port),
            "mcp.type": str(self.mcp_type),
            "mcp.path": self.mcp_path,
        }
        if self.mcp_display_name:
            labels["mcp.displayName"] = self.mcp_display_name
        if self.mcp_categories:
            labels["mcp.categories"] = ",".join(self.mcp_categories)
        return labels

    def to_labels_list(self) -> list[str]:
        """Convert configuration to a list of 'key=value' strings."""
        return [f"{k}={v}" for k, v in self.to_labels_dict().items()]


class McpProbeResult(BaseModel):
    """Result of probing a container for MCP server capabilities."""

    container: ContainerInfo
    status: McpStatus = McpStatus.NOT_MCP
    mcp_type: McpType | None = None
    port: int | None = None
    path: str | None = None
    server_name: str | None = None
    server_version: str | None = None
    protocol_version: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    tools_count: int = 0
    prompts_count: int = 0
    resources_count: int = 0
    error_message: str | None = None

    @property
    def is_mcp(self) -> bool:
        """Whether a live MCP server was verified."""
        return self.status in (McpStatus.VERIFIED_LABELED, McpStatus.VERIFIED_UNLABELED)

    def generate_label_config(
        self,
        id_override: str | None = None,
        display_name_override: str | None = None,
        port_override: int | None = None,
        path_override: str | None = None,
        type_override: str | None = None,
        categories: list[str] | None = None,
    ) -> LabelConfig:
        """Generate a LabelConfig based on probe results and container metadata."""
        mcp_id = id_override or self.container.service_name

        display_name = display_name_override
        if not display_name:
            if self.server_name:
                display_name = self.server_name.replace("-", " ").replace("_", " ").title()
            else:
                display_name = self.container.service_name.replace("-", " ").replace("_", " ").title()

        effective_port = port_override or self.port or (
            self.container.exposed_ports[0] if self.container.exposed_ports else 8000
        )

        effective_type = type_override or (
            self.mcp_type.value if isinstance(self.mcp_type, McpType) else (self.mcp_type or "http")
        )

        effective_path = path_override or self.path or (
            "/sse" if effective_type == "sse" else "/mcp"
        )

        effective_categories = categories if categories is not None else []

        return LabelConfig(
            mcp_enabled=True,
            mcp_id=mcp_id,
            mcp_display_name=display_name,
            mcp_port=effective_port,
            mcp_type=str(effective_type),
            mcp_path=effective_path,
            mcp_categories=effective_categories,
        )
