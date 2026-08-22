"""Unit tests for Docker Compose file locator."""

from pathlib import Path
import pytest

from mcp_scout.injector.compose_locator import ComposeLocator
from mcp_scout.models import ContainerInfo


def test_compose_locator_via_config_files_label(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yaml"
    compose_file.write_text("""services:
  my-service:
    image: test:latest
""")
    container = ContainerInfo(
        id="c12345678901",
        name="my-service-container",
        image="test:latest",
        labels={
            "com.docker.compose.project.config_files": str(compose_file),
            "com.docker.compose.service": "my-service",
            "com.docker.compose.project.working_dir": str(tmp_path),
        },
    )

    locator = ComposeLocator()
    found_path, service_name = locator.find_compose_file(container)
    assert found_path == compose_file
    assert service_name == "my-service"


def test_compose_locator_via_working_dir_label(tmp_path: Path):
    proj_dir = tmp_path / "smarthome"
    proj_dir.mkdir(parents=True)
    compose_file = proj_dir / "compose.yaml"
    compose_file.write_text("""services:
  homeassistant:
    image: homeassistant:latest
""")
    container = ContainerInfo(
        id="c22345678901",
        name="homeassistant",
        image="homeassistant:latest",
        labels={
            "com.docker.compose.project.working_dir": str(proj_dir),
            "com.docker.compose.service": "homeassistant",
        },
    )

    locator = ComposeLocator()
    found_path, service_name = locator.find_compose_file(container)
    assert found_path == compose_file
    assert service_name == "homeassistant"


def test_compose_locator_via_search_root_project_name(tmp_path: Path):
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True)
    compose_file = media_dir / "docker-compose.yml"
    compose_file.write_text("""services:
  radarr:
    image: radarr:latest
""")
    container = ContainerInfo(
        id="c32345678901",
        name="media_radarr_1",
        image="radarr:latest",
        labels={
            "com.docker.compose.project": "media",
            "com.docker.compose.service": "radarr",
        },
    )

    locator = ComposeLocator(search_root=tmp_path)
    found_path, service_name = locator.find_compose_file(container)
    assert found_path == compose_file
    assert service_name == "radarr"


def test_compose_locator_via_search_root_directory_traversal(tmp_path: Path):
    custom_dir = tmp_path / "custom_stack" / "nested"
    custom_dir.mkdir(parents=True)
    compose_file = custom_dir / "docker-compose.yaml"
    compose_file.write_text("""services:
  fastmcp-app:
    image: fastmcp:latest
""")
    container = ContainerInfo(
        id="c42345678901",
        name="fastmcp-app",
        image="fastmcp:latest",
        labels={},
    )

    locator = ComposeLocator(search_root=tmp_path)
    found_path, service_name = locator.find_compose_file(container)
    assert found_path == compose_file
    assert service_name == "fastmcp-app"


def test_compose_locator_not_found_raises_error(tmp_path: Path):
    container = ContainerInfo(
        id="c52345678901",
        name="unknown-standalone-app",
        image="unknown:latest",
        labels={
            "com.docker.compose.project.config_files": "/non/existent/path/docker-compose.yaml",
        },
    )

    locator = ComposeLocator(search_root=tmp_path)
    with pytest.raises(FileNotFoundError) as exc_info:
        locator.find_compose_file(container)
    assert "Could not locate docker-compose file" in str(exc_info.value)


def test_compose_locator_relative_config_file_with_working_dir(tmp_path: Path):
    proj_dir = tmp_path / "cloud"
    proj_dir.mkdir(parents=True)
    compose_file = proj_dir / "docker-compose.yaml"
    compose_file.write_text("""services:
  nextcloud:
    image: nextcloud:latest
""")
    container = ContainerInfo(
        id="c62345678901",
        name="nextcloud",
        image="nextcloud:latest",
        labels={
            "com.docker.compose.project.config_files": "docker-compose.yaml",
            "com.docker.compose.project.working_dir": str(proj_dir),
            "com.docker.compose.service": "nextcloud",
        },
    )

    locator = ComposeLocator()
    found_path, service_name = locator.find_compose_file(container)
    assert found_path == compose_file
    assert service_name == "nextcloud"


def test_compose_locator_list_services(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yaml"
    compose_file.write_text("""services:
  app:
    image: app:latest
  db:
    image: postgres:15
""")
    locator = ComposeLocator()
    services = locator.list_services(compose_file)
    assert services == ["app", "db"]


def test_compose_locator_list_services_invalid_file(tmp_path: Path):
    non_existent = tmp_path / "nonexistent.yaml"
    locator = ComposeLocator()
    assert locator.list_services(non_existent) == []

    corrupt = tmp_path / "corrupt.yaml"
    corrupt.write_text("invalid : : : yaml")
    assert locator.list_services(corrupt) == []

    no_services = tmp_path / "no_services.yaml"
    no_services.write_text("version: '3'")
    assert locator.list_services(no_services) == []


def test_compose_locator_find_all_compose_files(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "docker-compose.yaml").write_text("ignored")
    (tmp_path / "stack1").mkdir()
    (tmp_path / "stack1" / "docker-compose.yaml").write_text("services: {s1: {}}")
    (tmp_path / "stack2").mkdir()
    (tmp_path / "stack2" / "compose.yml").write_text("services: {s2: {}}")

    locator = ComposeLocator(search_root=tmp_path)
    found = locator.find_all_compose_files()
    assert len(found) == 2
    names = [f.parent.name for f in found]
    assert "stack1" in names
    assert "stack2" in names
    assert ".git" not in names


def test_compose_locator_find_all_compose_files_non_existent(tmp_path: Path):
    locator = ComposeLocator(search_root=tmp_path / "missing")
    assert locator.find_all_compose_files() == []


def test_compose_locator_working_dir_in_search_root(tmp_path: Path):
    (tmp_path / "myservice").mkdir()
    compose_file = tmp_path / "myservice" / "docker-compose.yaml"
    compose_file.write_text("services:\n  service1:\n    image: test")

    container = ContainerInfo(
        id="c72345678901",
        name="myservice_1",
        image="test:latest",
        labels={
            "com.docker.compose.project.working_dir": "/some/foreign/mount/myservice",
            "com.docker.compose.service": "service1",
        },
    )

    locator = ComposeLocator(search_root=tmp_path)
    found_path, service_name = locator.find_compose_file(container)
    assert found_path == compose_file
    assert service_name == "service1"
