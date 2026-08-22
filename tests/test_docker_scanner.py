"""Tests for the Docker container discovery and inspection scanner."""

from unittest.mock import MagicMock, patch
import pytest
import docker.errors
from mcp_scout.models import ContainerInfo
from mcp_scout.probe.docker_scanner import DockerScanner


@pytest.fixture
def mock_docker_container():
    container = MagicMock()
    container.id = "abcdef1234567890123456789012345678901234567890"
    container.name = "mcp-server-postgres"
    container.status = "running"
    container.image.tags = ["ghcr.io/modelcontextprotocol/server-postgres:latest"]
    container.labels = {
        "com.docker.compose.service": "postgres-mcp",
        "com.docker.compose.project.working_dir": "/containers/mcp",
        "com.docker.compose.project.config_files": "/containers/mcp/docker-compose.yaml",
        "mcp.enabled": "true",
        "mcp.id": "postgres-mcp",
        "mcp.port": "8000",
        "mcp.type": "sse",
        "mcp.path": "/sse",
    }
    container.attrs = {
        "Id": container.id,
        "Name": f"/{container.name}",
        "State": {"Status": "running"},
        "Config": {
            "Image": "ghcr.io/modelcontextprotocol/server-postgres:latest",
            "Cmd": ["supergateway", "--port", "8000"],
            "Entrypoint": ["/docker-entrypoint.sh"],
            "Env": [
                "FASTMCP_PORT=8000",
                "POSTGRES_URL=postgresql://user:pass@db:5432/test",
                "NO_EQUALS_VAR",
            ],
            "Labels": container.labels,
            "ExposedPorts": {
                "8000/tcp": {},
                "8080/tcp": {},
            },
        },
        "NetworkSettings": {
            "Networks": {
                "net_mcp": {
                    "IPAddress": "172.20.0.10",
                    "Gateway": "172.20.0.1",
                },
                "bridge": {
                    "IPAddress": "172.17.0.2",
                    "Gateway": "172.17.0.1",
                },
            },
            "Ports": {
                "8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}],
                "8080/tcp": None,
            },
        },
    }
    return container


def test_docker_scanner_parse_container(mock_docker_container):
    scanner = DockerScanner(client=MagicMock())
    info = scanner.parse_container(mock_docker_container)

    assert isinstance(info, ContainerInfo)
    assert info.id == "abcdef1234567890123456789012345678901234567890"
    assert info.name == "mcp-server-postgres"
    assert info.image == "ghcr.io/modelcontextprotocol/server-postgres:latest"
    assert info.status == "running"
    assert "supergateway" in (info.command or "")
    assert "/docker-entrypoint.sh" in (info.entrypoint or "")
    assert info.ip_addresses["net_mcp"] == "172.20.0.10"
    assert info.ip_addresses["bridge"] == "172.17.0.2"
    assert set(info.exposed_ports) == {8000, 8080}
    assert info.published_ports == {8000: 8000}
    assert info.env_vars["FASTMCP_PORT"] == "8000"
    assert info.env_vars["POSTGRES_URL"] == "postgresql://user:pass@db:5432/test"
    assert "NO_EQUALS_VAR" in info.env_vars
    assert info.labels["com.docker.compose.service"] == "postgres-mcp"
    assert info.existing_mcp_labels["mcp.enabled"] == "true"
    assert info.existing_mcp_labels["mcp.port"] == "8000"
    assert info.is_mcp_labeled is True
    assert info.primary_ip == "172.20.0.10"


def test_docker_scanner_parse_container_no_image_tags():
    container = MagicMock()
    container.id = "c_no_tags"
    container.name = "untagged-app"
    container.status = "running"
    container.image.tags = []
    container.labels = {}
    container.attrs = {
        "Config": {"Image": "sha256:123456789", "Cmd": "run-server", "Entrypoint": "/init"},
        "NetworkSettings": {"Networks": {}, "IPAddress": "172.17.0.99"},
    }
    scanner = DockerScanner(client=MagicMock())
    info = scanner.parse_container(container)
    assert info.image == "sha256:123456789"
    assert info.ip_addresses == {"bridge": "172.17.0.99"}
    assert info.command == "run-server"
    assert info.entrypoint == "/init"


def test_docker_scanner_scan_containers(mock_docker_container):
    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_docker_container]

    scanner = DockerScanner(client=mock_client)
    containers = scanner.scan_containers()

    assert len(containers) == 1
    assert containers[0].name == "mcp-server-postgres"
    mock_client.containers.list.assert_called_once_with(all=False, filters=None)


def test_docker_scanner_get_container(mock_docker_container):
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_docker_container

    scanner = DockerScanner(client=mock_client)
    container = scanner.get_container("postgres-mcp")

    assert container is not None
    assert container.name == "mcp-server-postgres"
    mock_client.containers.get.assert_called_once_with("postgres-mcp")


def test_docker_scanner_get_container_not_found():
    mock_client = MagicMock()
    mock_client.containers.get.side_effect = docker.errors.NotFound("Not found")

    scanner = DockerScanner(client=mock_client)
    container = scanner.get_container("nonexistent")
    assert container is None


def test_docker_scanner_ping():
    mock_client = MagicMock()
    mock_client.ping.return_value = True

    scanner = DockerScanner(client=mock_client)
    assert scanner.ping() is True
    assert scanner.is_available() is True


def test_docker_scanner_ping_failure():
    mock_client = MagicMock()
    mock_client.ping.side_effect = docker.errors.DockerException("Connection refused")

    scanner = DockerScanner(client=mock_client)
    assert scanner.ping() is False
    assert scanner.is_available() is False


def test_docker_scanner_fallback_parsing():
    raw_dict = {
        "Id": "11223344",
        "Name": "/minimal-container",
        "State": {"Status": "running"},
        "Config": {
            "Image": "minimal:latest",
            "Labels": {},
            "Env": [],
        },
        "NetworkSettings": {
            "Networks": {},
            "Ports": {},
        },
    }
    scanner = DockerScanner(client=MagicMock())
    info = scanner.parse_container(raw_dict)
    assert info.id == "11223344"
    assert info.name == "minimal-container"
    assert info.image == "minimal:latest"
    assert info.exposed_ports == []
    assert info.published_ports == {}
    assert info.ip_addresses == {}
    assert info.env_vars == {}
    assert info.labels == {}
    assert info.existing_mcp_labels == {}


def test_docker_scanner_default_init():
    with patch("docker.from_env") as mock_from_env:
        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        scanner = DockerScanner()
        assert scanner.client is mock_client
        mock_from_env.assert_called_once()


def test_docker_scanner_base_url_init():
    with patch("docker.DockerClient") as mock_docker_client_cls:
        mock_client = MagicMock()
        mock_docker_client_cls.return_value = mock_client
        scanner = DockerScanner(base_url="tcp://10.0.0.10:2375")
        assert scanner.client is mock_client
        mock_docker_client_cls.assert_called_once_with(base_url="tcp://10.0.0.10:2375")
