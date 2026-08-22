"""Lossless, comment-preserving YAML modifier for Docker Compose files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from mcp_scout.models import LabelConfig


class YamlModifier:
    """Modifies Docker Compose YAML files while preserving comments, formatting, and quotes."""

    def __init__(
        self,
        indent_mapping: int = 2,
        indent_sequence: int = 4,
        indent_offset: int = 2,
    ) -> None:
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(
            mapping=indent_mapping,
            sequence=indent_sequence,
            offset=indent_offset,
        )
        self.yaml.width = 4096

    def backup_compose_file(self, compose_file: Path | str) -> Path:
        """Create a timestamped backup copy of a compose file before modifying it."""
        path = Path(compose_file)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak_path = path.with_name(f"{path.name}.{timestamp}.bak")
        shutil.copy2(path, bak_path)
        return bak_path

    def inject_mcp_labels(
        self,
        compose_file: Path | str,
        service_name: str,
        config: LabelConfig,
        attach_network: str | None = None,
        create_backup: bool = True,
    ) -> bool:
        """Inject or update standard mcp.* labels in a Docker Compose service block.

        Args:
            compose_file: Path to docker-compose file.
            service_name: Name of the service key under 'services:'.
            config: LabelConfig containing the MCP metadata to inject.
            attach_network: Optional network name (e.g. 'net_mcp') to attach to service & root.
            create_backup: Whether to create a .bak backup file before modifying.

        Returns:
            True if modification succeeded, False otherwise.
        """
        path = Path(compose_file)
        if not path.is_file():
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = self.yaml.load(f)
        except Exception:
            return False

        if not isinstance(data, dict) or "services" not in data or not isinstance(data["services"], dict):
            return False

        if service_name not in data["services"] or not isinstance(data["services"][service_name], dict):
            return False

        if create_backup:
            self.backup_compose_file(path)

        service = data["services"][service_name]
        new_labels_dict = config.to_labels_dict()
        new_labels_list = config.to_labels_list()

        # Update service labels
        if "labels" in service and service["labels"] is not None:
            existing_labels = service["labels"]
            if isinstance(existing_labels, dict):
                # Remove existing mcp.* labels
                for key in list(existing_labels.keys()):
                    if str(key).startswith("mcp."):
                        del existing_labels[key]
                # Insert updated labels
                for k, v in new_labels_dict.items():
                    existing_labels[k] = v
            elif isinstance(existing_labels, list):
                # Filter out existing mcp.* entries
                filtered = [
                    lbl for lbl in existing_labels
                    if not (isinstance(lbl, str) and lbl.startswith("mcp."))
                ]
                seq = CommentedSeq(filtered)
                for lbl in new_labels_list:
                    seq.append(lbl)
                service["labels"] = seq
            else:
                service["labels"] = CommentedSeq(new_labels_list)
        else:
            service["labels"] = CommentedSeq(new_labels_list)

        # Attach network if requested
        if attach_network:
            # 1. Attach to service
            if "networks" not in service or service["networks"] is None:
                service["networks"] = CommentedSeq([attach_network])
            elif isinstance(service["networks"], list):
                if attach_network not in service["networks"]:
                    service["networks"].append(attach_network)
            elif isinstance(service["networks"], dict):
                if attach_network not in service["networks"]:
                    service["networks"][attach_network] = CommentedMap()

            # 2. Attach to root networks section
            if "networks" not in data or data["networks"] is None:
                ext_net = CommentedMap({"external": True})
                data["networks"] = CommentedMap({attach_network: ext_net})
            elif isinstance(data["networks"], dict):
                if attach_network not in data["networks"]:
                    ext_net = CommentedMap({"external": True})
                    data["networks"][attach_network] = ext_net
            elif isinstance(data["networks"], list):
                if attach_network not in data["networks"]:
                    data["networks"].append(attach_network)

        # Atomic write back to file
        tmp_file = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                self.yaml.dump(data, f)
            tmp_file.replace(path)
            return True
        except Exception:
            if tmp_file.exists():
                tmp_file.unlink()
            return False

    def remove_mcp_labels(
        self,
        compose_file: Path | str,
        service_name: str,
        detach_network: str | None = None,
        create_backup: bool = True,
    ) -> bool:
        """Remove mcp.* labels from a Docker Compose service block."""
        path = Path(compose_file)
        if not path.is_file():
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = self.yaml.load(f)
        except Exception:
            return False

        if not isinstance(data, dict) or "services" not in data or service_name not in data["services"]:
            return False

        if create_backup:
            self.backup_compose_file(path)

        service = data["services"][service_name]
        if "labels" in service and service["labels"] is not None:
            existing = service["labels"]
            if isinstance(existing, dict):
                for key in list(existing.keys()):
                    if str(key).startswith("mcp."):
                        del existing[key]
            elif isinstance(existing, list):
                service["labels"] = [
                    lbl for lbl in existing
                    if not (isinstance(lbl, str) and lbl.startswith("mcp."))
                ]

        if detach_network and "networks" in service and service["networks"] is not None:
            if isinstance(service["networks"], list) and detach_network in service["networks"]:
                service["networks"].remove(detach_network)
            elif isinstance(service["networks"], dict) and detach_network in service["networks"]:
                del service["networks"][detach_network]

        tmp_file = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                self.yaml.dump(data, f)
            tmp_file.replace(path)
            return True
        except Exception:
            if tmp_file.exists():
                tmp_file.unlink()
            return False
