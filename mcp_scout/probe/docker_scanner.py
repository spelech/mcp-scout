"""Docker container discovery and inspection scanner."""

from __future__ import annotations

from typing import Any
import docker
import docker.errors
from docker.models.containers import Container

from mcp_scout.models import ContainerInfo


class DockerScanner:
    """Discovers and inspects running Docker containers on the host."""

    def __init__(
        self,
        client: docker.DockerClient | None = None,
        base_url: str | None = None,
    ) -> None:
        """Initialize the Docker scanner.
        
        Args:
            client: Optional pre-configured DockerClient instance.
            base_url: Optional Docker daemon socket or HTTP URL.
        """
        if client is not None:
            self.client = client
        elif base_url is not None:
            self.client = docker.DockerClient(base_url=base_url)
        else:
            self.client = docker.from_env()

    def is_available(self) -> bool:
        """Check if the Docker daemon is reachable and responding."""
        return self.ping()

    def ping(self) -> bool:
        """Ping the Docker daemon to check connectivity."""
        try:
            return bool(self.client.ping())
        except (docker.errors.DockerException, Exception):
            return False

    def scan_containers(
        self,
        all: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> list[ContainerInfo]:
        """Scan running Docker containers and parse them into ContainerInfo instances.
        
        Args:
            all: Whether to list all containers (including stopped) or only running ones.
            filters: Optional dictionary of Docker API filters.
            
        Returns:
            List of parsed ContainerInfo instances.
        """
        raw_containers = self.client.containers.list(all=all, filters=filters)
        return [self.parse_container(c) for c in raw_containers]

    def get_container(self, container_id_or_name: str) -> ContainerInfo | None:
        """Retrieve a specific container by its ID or name.
        
        Args:
            container_id_or_name: Container ID or name.
            
        Returns:
            Parsed ContainerInfo if found, otherwise None.
        """
        try:
            raw_container = self.client.containers.get(container_id_or_name)
            return self.parse_container(raw_container)
        except (docker.errors.NotFound, docker.errors.DockerException):
            return None

    def parse_container(self, container: Container | dict[str, Any]) -> ContainerInfo:
        """Parse a Docker container object or raw inspect dictionary into ContainerInfo.
        
        Args:
            container: Docker SDK Container object or inspect dict.
            
        Returns:
            Populated ContainerInfo instance.
        """
        if isinstance(container, dict):
            attrs = container
            cid = attrs.get("Id", "")
            raw_name = attrs.get("Name", "")
            status = attrs.get("State", {}).get("Status", "running")
            labels = attrs.get("Config", {}).get("Labels") or {}
            image = attrs.get("Config", {}).get("Image") or attrs.get("Image", "")
        else:
            attrs = getattr(container, "attrs", {}) or {}
            cid = getattr(container, "id", "") or attrs.get("Id", "")
            raw_name = getattr(container, "name", "") or attrs.get("Name", "")
            status = getattr(container, "status", "") or attrs.get("State", {}).get("Status", "running")
            labels = getattr(container, "labels", None) or attrs.get("Config", {}).get("Labels") or {}
            
            image_obj = getattr(container, "image", None)
            image_tags = getattr(image_obj, "tags", []) if image_obj else []
            if image_tags:
                image = image_tags[0]
            else:
                image = attrs.get("Config", {}).get("Image") or attrs.get("Image", "")

        name = raw_name.lstrip("/")

        config = attrs.get("Config", {}) or {}
        cmd = config.get("Cmd")
        command_str = " ".join(cmd) if isinstance(cmd, list) else (str(cmd) if cmd else None)

        entrypoint = config.get("Entrypoint")
        entrypoint_str = (
            " ".join(entrypoint)
            if isinstance(entrypoint, list)
            else (str(entrypoint) if entrypoint else None)
        )

        # Parse environment variables
        raw_env = config.get("Env") or []
        env_vars: dict[str, str] = {}
        for env_entry in raw_env:
            if "=" in env_entry:
                k, v = env_entry.split("=", 1)
                env_vars[k] = v
            else:
                env_vars[env_entry] = ""

        # Parse network IP addresses
        net_settings = attrs.get("NetworkSettings", {}) or {}
        networks = net_settings.get("Networks", {}) or {}
        ip_addresses: dict[str, str] = {}
        for net_name, net_data in networks.items():
            if isinstance(net_data, dict):
                ip = net_data.get("IPAddress")
                if ip:
                    ip_addresses[net_name] = ip
        if not ip_addresses and net_settings.get("IPAddress"):
            ip_addresses["bridge"] = net_settings["IPAddress"]

        # Parse exposed ports
        exposed_ports_set: set[int] = set()
        raw_exposed = config.get("ExposedPorts") or {}
        for port_proto in raw_exposed.keys():
            port_num_str = port_proto.split("/")[0]
            if port_num_str.isdigit():
                exposed_ports_set.add(int(port_num_str))

        # Parse published ports and port mappings
        published_ports: dict[int, int] = {}
        raw_ports = net_settings.get("Ports") or {}
        for port_proto, bindings in raw_ports.items():
            port_num_str = port_proto.split("/")[0]
            if port_num_str.isdigit():
                c_port = int(port_num_str)
                exposed_ports_set.add(c_port)
                if bindings and isinstance(bindings, list) and len(bindings) > 0:
                    first_binding = bindings[0]
                    if isinstance(first_binding, dict):
                        host_port_str = first_binding.get("HostPort")
                        if host_port_str and host_port_str.isdigit():
                            published_ports[c_port] = int(host_port_str)

        # Extract MCP labels
        existing_mcp_labels = {
            k: str(v) for k, v in labels.items() if k.startswith("mcp.")
        }

        return ContainerInfo(
            id=cid,
            name=name,
            image=image,
            status=status,
            command=command_str,
            entrypoint=entrypoint_str,
            ip_addresses=ip_addresses,
            exposed_ports=sorted(exposed_ports_set),
            published_ports=published_ports,
            env_vars=env_vars,
            labels=labels,
            existing_mcp_labels=existing_mcp_labels,
        )
