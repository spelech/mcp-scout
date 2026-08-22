"""Unit tests for YAML comment-preserving label injector."""

from pathlib import Path
from unittest.mock import patch
import pytest
from ruamel.yaml import YAML

from mcp_scout.injector.yaml_modifier import YamlModifier
from mcp_scout.models import LabelConfig


def test_yaml_injection_preserves_comments(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""# Main services configuration
services:
  my-app:
    # Important note about image
    image: my-app:latest
    ports:
      - "8000:8000"
""")
    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="my-app",
        mcp_display_name="My App MCP",
        mcp_port=8000,
        mcp_type="http",
        mcp_path="/mcp",
        mcp_categories=["productivity"],
    )
    modifier = YamlModifier()
    success = modifier.inject_mcp_labels(sample_yaml, "my-app", config, attach_network="net_mcp")
    assert success is True

    content = sample_yaml.read_text()
    assert "# Main services configuration" in content
    assert "# Important note about image" in content
    assert "mcp.enabled=true" in content
    assert "mcp.id=my-app" in content
    assert "mcp.displayName=My App MCP" in content
    assert "mcp.port=8000" in content
    assert "mcp.type=http" in content
    assert "mcp.path=/mcp" in content
    assert "mcp.categories=productivity" in content
    assert "net_mcp" in content


def test_yaml_injection_updates_existing_mcp_labels(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""services:
  custom-svc:
    image: custom:latest
    labels:
      - "traefik.enable=true"
      - "mcp.enabled=false"
      - "mcp.id=old-id"
      - "mcp.port=9999"
""")
    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="new-svc-id",
        mcp_display_name="Updated Service",
        mcp_port=8080,
        mcp_type="sse",
        mcp_path="/sse",
        mcp_categories=["tools", "automation"],
    )
    modifier = YamlModifier()
    success = modifier.inject_mcp_labels(sample_yaml, "custom-svc", config)
    assert success is True

    content = sample_yaml.read_text()
    assert "traefik.enable=true" in content
    assert "mcp.enabled=true" in content
    assert "mcp.id=new-svc-id" in content
    assert "mcp.displayName=Updated Service" in content
    assert "mcp.port=8080" in content
    assert "mcp.type=sse" in content
    assert "mcp.path=/sse" in content
    assert "mcp.categories=tools,automation" in content
    assert "mcp.id=old-id" not in content
    assert "mcp.port=9999" not in content


def test_yaml_injection_dict_format_labels(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""services:
  map-svc:
    image: map-svc:latest
    labels:
      traefik.enable: "true"
      existing.label: "kept"
""")
    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="map-svc",
        mcp_display_name="Map Service",
        mcp_port=5000,
        mcp_type="http",
        mcp_path="/mcp",
    )
    modifier = YamlModifier()
    success = modifier.inject_mcp_labels(sample_yaml, "map-svc", config)
    assert success is True

    yaml = YAML()
    data = yaml.load(sample_yaml.read_text())
    labels = data["services"]["map-svc"]["labels"]
    assert isinstance(labels, dict)
    assert labels["traefik.enable"] == "true"
    assert labels["existing.label"] == "kept"
    assert labels["mcp.enabled"] == "true"
    assert labels["mcp.id"] == "map-svc"
    assert labels["mcp.port"] == "5000"
    assert labels["mcp.type"] == "http"
    assert labels["mcp.path"] == "/mcp"


def test_yaml_injection_creates_backup(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    original_content = """# Original file
services:
  app:
    image: app:latest
"""
    sample_yaml.write_text(original_content)

    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="app",
        mcp_port=8000,
    )
    modifier = YamlModifier()
    success = modifier.inject_mcp_labels(sample_yaml, "app", config, create_backup=True)
    assert success is True

    # Check that a backup file was created
    bak_files = list(tmp_path.glob("docker-compose.yaml.*.bak"))
    assert len(bak_files) >= 1
    assert bak_files[0].read_text() == original_content


def test_yaml_injection_service_not_found(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""services:
  existing-svc:
    image: test:latest
""")
    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="non-existent",
        mcp_port=8000,
    )
    modifier = YamlModifier()
    success = modifier.inject_mcp_labels(sample_yaml, "non-existent", config)
    assert success is False


def test_yaml_injection_invalid_files(tmp_path: Path):
    modifier = YamlModifier()
    config = LabelConfig(mcp_enabled=True, mcp_id="app", mcp_port=8000)

    # Missing file
    assert modifier.inject_mcp_labels(tmp_path / "missing.yaml", "app", config) is False

    # Corrupted YAML
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("invalid: [unclosed")
    assert modifier.inject_mcp_labels(bad_yaml, "app", config) is False

    # Not a dictionary
    list_yaml = tmp_path / "list.yaml"
    list_yaml.write_text("- item1\n- item2")
    assert modifier.inject_mcp_labels(list_yaml, "app", config) is False

    # No services key
    no_svc = tmp_path / "nosvc.yaml"
    no_svc.write_text("version: '3'")
    assert modifier.inject_mcp_labels(no_svc, "app", config) is False

    # Service is not a dict
    bad_svc = tmp_path / "badsvc.yaml"
    bad_svc.write_text("services:\n  app: 'not a map'")
    assert modifier.inject_mcp_labels(bad_svc, "app", config) is False


def test_yaml_injection_existing_networks(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""services:
  web:
    image: nginx:alpine
    networks:
      - frontend
      - backend

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
""")
    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="web",
        mcp_port=80,
    )
    modifier = YamlModifier()
    success = modifier.inject_mcp_labels(sample_yaml, "web", config, attach_network="net_mcp")
    assert success is True

    yaml = YAML()
    data = yaml.load(sample_yaml.read_text())
    assert "frontend" in data["services"]["web"]["networks"]
    assert "backend" in data["services"]["web"]["networks"]
    assert "net_mcp" in data["services"]["web"]["networks"]
    assert "frontend" in data["networks"]
    assert "backend" in data["networks"]
    assert "net_mcp" in data["networks"]
    assert data["networks"]["net_mcp"]["external"] is True


def test_yaml_injection_dict_networks(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""services:
  web:
    image: nginx:alpine
    networks:
      frontend:
        aliases:
          - web.local

networks:
  frontend:
    driver: bridge
""")
    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="web",
        mcp_port=80,
    )
    modifier = YamlModifier()
    success = modifier.inject_mcp_labels(sample_yaml, "web", config, attach_network="net_mcp")
    assert success is True

    yaml = YAML()
    data = yaml.load(sample_yaml.read_text())
    assert "frontend" in data["services"]["web"]["networks"]
    assert "net_mcp" in data["services"]["web"]["networks"]
    assert "net_mcp" in data["networks"]


def test_yaml_injection_root_list_networks(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""services:
  web:
    image: nginx:alpine

networks:
  - default
""")
    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="web",
        mcp_port=80,
    )
    modifier = YamlModifier()
    success = modifier.inject_mcp_labels(sample_yaml, "web", config, attach_network="net_mcp")
    assert success is True

    yaml = YAML()
    data = yaml.load(sample_yaml.read_text())
    assert "net_mcp" in data["networks"]


def test_yaml_injection_network_already_attached(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""services:
  web:
    image: nginx:alpine
    networks:
      - net_mcp

networks:
  net_mcp:
    external: true
""")
    config = LabelConfig(
        mcp_enabled=True,
        mcp_id="web",
        mcp_port=80,
    )
    modifier = YamlModifier()
    success = modifier.inject_mcp_labels(sample_yaml, "web", config, attach_network="net_mcp")
    assert success is True

    yaml = YAML()
    data = yaml.load(sample_yaml.read_text())
    assert data["services"]["web"]["networks"].count("net_mcp") == 1
    assert "net_mcp" in data["networks"]


def test_remove_mcp_labels(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""services:
  app:
    image: app:latest
    labels:
      - "custom.label=true"
      - "mcp.enabled=true"
      - "mcp.id=app"
      - "mcp.port=8000"
    networks:
      - default
      - net_mcp
""")
    modifier = YamlModifier()
    success = modifier.remove_mcp_labels(sample_yaml, "app", detach_network="net_mcp")
    assert success is True

    content = sample_yaml.read_text()
    assert "custom.label=true" in content
    assert "mcp.enabled" not in content
    assert "mcp.id" not in content
    assert "mcp.port" not in content
    assert "net_mcp" not in content


def test_remove_mcp_labels_dict_format(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("""services:
  app:
    image: app:latest
    labels:
      custom.label: "true"
      mcp.enabled: "true"
      mcp.id: "app"
    networks:
      default: {}
      net_mcp: {}
""")
    modifier = YamlModifier()
    success = modifier.remove_mcp_labels(sample_yaml, "app", detach_network="net_mcp")
    assert success is True

    yaml = YAML()
    data = yaml.load(sample_yaml.read_text())
    assert "custom.label" in data["services"]["app"]["labels"]
    assert "mcp.enabled" not in data["services"]["app"]["labels"]
    assert "mcp.id" not in data["services"]["app"]["labels"]
    assert "net_mcp" not in data["services"]["app"]["networks"]


def test_remove_mcp_labels_invalid_inputs(tmp_path: Path):
    modifier = YamlModifier()
    assert modifier.remove_mcp_labels(tmp_path / "nonexistent.yaml", "app") is False

    corrupt = tmp_path / "corrupt.yaml"
    corrupt.write_text("invalid: [")
    assert modifier.remove_mcp_labels(corrupt, "app") is False

    no_svc = tmp_path / "no_svc.yaml"
    no_svc.write_text("services: {}")
    assert modifier.remove_mcp_labels(no_svc, "missing") is False


def test_yaml_injection_dump_error(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("services:\n  app:\n    image: test")
    config = LabelConfig(mcp_enabled=True, mcp_id="app", mcp_port=8000)

    modifier = YamlModifier()
    with patch.object(modifier.yaml, "dump", side_effect=Exception("Dump failure")):
        assert modifier.inject_mcp_labels(sample_yaml, "app", config) is False


def test_yaml_remove_dump_error(tmp_path: Path):
    sample_yaml = tmp_path / "docker-compose.yaml"
    sample_yaml.write_text("services:\n  app:\n    image: test\n    labels:\n      - mcp.id=app")

    modifier = YamlModifier()
    with patch.object(modifier.yaml, "dump", side_effect=Exception("Dump failure")):
        assert modifier.remove_mcp_labels(sample_yaml, "app") is False
