"""Docker Compose file locator for running containers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from ruamel.yaml import YAML

from mcp_scout.models import ContainerInfo

COMPOSE_FILENAMES = (
    "docker-compose.yaml",
    "docker-compose.yml",
    "compose.yaml",
    "compose.yml",
)

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".superpowers",
    ".gemini",
}


class ComposeLocator:
    """Locates Docker Compose files corresponding to running Docker containers."""

    def __init__(self, search_root: Path | str | None = None) -> None:
        self.search_root = Path(search_root) if search_root else None
        self._yaml = YAML(typ="safe")

    def find_compose_file(
        self,
        container: ContainerInfo,
        search_root: Path | str | None = None,
    ) -> tuple[Path, str]:
        """Locate the docker-compose file and service name for a container.

        Args:
            container: Container metadata and Docker labels.
            search_root: Optional directory to search if labels do not resolve directly.

        Returns:
            Tuple of (resolved compose file Path, service name string).

        Raises:
            FileNotFoundError: If no matching compose file could be located.
        """
        root = Path(search_root) if search_root else self.search_root
        service_name = container.service_name

        # 1. Check explicit config files from compose labels
        for cfg_str in container.compose_config_files:
            cfg_path = Path(cfg_str)
            if cfg_path.is_file():
                return cfg_path.resolve(), service_name

            # Check relative to working_dir if present
            if container.compose_working_dir:
                work_candidate = Path(container.compose_working_dir) / cfg_path
                if work_candidate.is_file():
                    return work_candidate.resolve(), service_name

            # Check relative to search_root if present
            if root:
                root_candidate = root / cfg_path
                if root_candidate.is_file():
                    return root_candidate.resolve(), service_name
                # Check root / filename
                root_name_candidate = root / cfg_path.name
                if root_name_candidate.is_file():
                    return root_name_candidate.resolve(), service_name

        # 2. Check compose working directory label
        if container.compose_working_dir:
            work_dir = Path(container.compose_working_dir)
            if work_dir.is_dir():
                for fname in COMPOSE_FILENAMES:
                    candidate = work_dir / fname
                    if candidate.is_file():
                        return candidate.resolve(), service_name

            if root:
                # In case container working dir path was inside another mount/environment
                rel_work_dir = root / work_dir.name
                if rel_work_dir.is_dir():
                    for fname in COMPOSE_FILENAMES:
                        candidate = rel_work_dir / fname
                        if candidate.is_file():
                            return candidate.resolve(), service_name

        # 3. Check compose project label
        project_name = container.labels.get("com.docker.compose.project")
        if project_name and root:
            proj_dir = root / project_name
            if proj_dir.is_dir():
                for fname in COMPOSE_FILENAMES:
                    candidate = proj_dir / fname
                    if candidate.is_file():
                        return candidate.resolve(), service_name

        # 4. Search directory tree under search_root
        if root and root.is_dir():
            for compose_path in self.find_all_compose_files(root):
                services = self.list_services(compose_path)
                if service_name in services or container.name.lstrip("/") in services:
                    return compose_path.resolve(), service_name

        # 5. Default search under /containers if exists and not already searched
        default_containers_root = Path("/containers")
        if default_containers_root.is_dir() and (root != default_containers_root):
            for compose_path in self.find_all_compose_files(default_containers_root):
                services = self.list_services(compose_path)
                if service_name in services or container.name.lstrip("/") in services:
                    return compose_path.resolve(), service_name

        raise FileNotFoundError(
            f"Could not locate docker-compose file for container '{container.name}' "
            f"(service: '{service_name}')"
        )

    def list_services(self, compose_file: Path | str) -> list[str]:
        """Extract defined service names from a compose file."""
        path = Path(compose_file)
        if not path.is_file():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = self._yaml.load(f)
            if isinstance(data, dict) and "services" in data and isinstance(data["services"], dict):
                return list(data["services"].keys())
        except Exception:
            pass
        return []

    def find_all_compose_files(self, search_root: Path | str | None = None) -> list[Path]:
        """Find all compose files under a directory, ignoring hidden/vendor folders."""
        root = Path(search_root) if search_root else (self.search_root or Path.cwd())
        if not root.is_dir():
            return []

        compose_files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune ignored directories in place
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]

            for fname in filenames:
                if fname in COMPOSE_FILENAMES:
                    compose_files.append(Path(dirpath) / fname)

        return compose_files
