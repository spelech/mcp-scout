"""Discovery and classification orchestrator combining Docker inspection, heuristics, and network probing."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp_scout.models import ContainerInfo, McpProbeResult, McpStatus, ProbeCandidate
from mcp_scout.probe.docker_scanner import DockerScanner
from mcp_scout.probe.heuristics import HeuristicsEvaluator
from mcp_scout.probe.handshake import ProtocolProber


class ProbeEngine:
    """Orchestrates container scanning, heuristics evaluation, and active network protocol probing."""

    def __init__(
        self,
        scanner: DockerScanner | None = None,
        heuristics: HeuristicsEvaluator | None = None,
        prober: ProtocolProber | None = None,
        max_concurrency: int = 10,
    ) -> None:
        """Initialize the probe engine.
        
        Args:
            scanner: Scanner for discovering Docker containers.
            heuristics: Evaluator for analyzing container metadata and generating candidates.
            prober: Active network protocol prober.
            max_concurrency: Maximum number of containers probed concurrently.
        """
        self.scanner = scanner or DockerScanner()
        self.heuristics = heuristics or HeuristicsEvaluator()
        self.prober = prober or ProtocolProber()
        self.max_concurrency = max_concurrency

    async def probe_container(self, container: ContainerInfo) -> McpProbeResult:
        """Evaluate heuristics and probe active candidates for a single container.
        
        Args:
            container: Target container information.
            
        Returns:
            Classified McpProbeResult.
        """
        candidates = self.heuristics.generate_candidates(container)
        ip = container.primary_ip

        # If no internal IP address is found, check if published ports or host fallback available
        if not ip:
            if container.published_ports:
                ip = "127.0.0.1"
            else:
                # Unreachable container
                if container.is_mcp_labeled:
                    status = McpStatus.SUSPECTED
                    err = "Container labeled with mcp.enabled=true but has no reachable IP address"
                elif self.heuristics.is_suspected_mcp(container):
                    status = McpStatus.SUSPECTED
                    err = "Container matches MCP heuristics but has no reachable IP address"
                else:
                    status = McpStatus.NOT_MCP
                    err = None
                return McpProbeResult(container=container, status=status, error_message=err)

        # Probe candidate endpoints in priority order
        for candidate in candidates:
            # When probing via localhost, translate container port to published host port if mapped
            target_port = candidate.port
            if ip == "127.0.0.1" and candidate.port in container.published_ports:
                target_port = container.published_ports[candidate.port]

            effective_candidate = ProbeCandidate(
                port=target_port,
                path=candidate.path,
                candidate_type=candidate.candidate_type,
                source=candidate.source,
            )

            result = await self.prober.probe_candidate(ip, effective_candidate, container=container)
            if result is not None and result.is_mcp:
                # Retain the container's internal port in the recorded result
                result.port = candidate.port
                return result

        # If active probes did not succeed
        if container.is_mcp_labeled:
            status = McpStatus.SUSPECTED
            err = "Configured with mcp.enabled=true but active network probe failed"
        elif self.heuristics.is_suspected_mcp(container):
            status = McpStatus.SUSPECTED
            err = "Matches MCP heuristics but active network probe failed"
        else:
            status = McpStatus.NOT_MCP
            err = None

        return McpProbeResult(
            container=container,
            status=status,
            error_message=err,
        )

    async def discover(
        self,
        all_containers: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> list[McpProbeResult]:
        """Scan Docker containers and probe all candidates concurrently.
        
        Args:
            all_containers: Whether to scan stopped containers in addition to running ones.
            filters: Optional Docker API filter dictionary.
            
        Returns:
            List of McpProbeResult instances for all scanned containers.
        """
        containers = self.scanner.scan_containers(all=all_containers, filters=filters)
        if not containers:
            return []

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _probe_with_semaphore(c: ContainerInfo) -> McpProbeResult:
            async with semaphore:
                return await self.probe_container(c)

        results = await asyncio.gather(*[_probe_with_semaphore(c) for c in containers])
        return list(results)

    async def run_discovery(
        self,
        scanner: DockerScanner | None = None,
        heuristics: HeuristicsEvaluator | None = None,
        prober: ProtocolProber | None = None,
        all_containers: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> list[McpProbeResult]:
        """Run discovery with optional component overrides.
        
        Args:
            scanner: Optional replacement scanner.
            heuristics: Optional replacement heuristics evaluator.
            prober: Optional replacement protocol prober.
            all_containers: Whether to scan stopped containers.
            filters: Optional Docker API filters.
            
        Returns:
            List of McpProbeResult instances.
        """
        if scanner is not None:
            self.scanner = scanner
        if heuristics is not None:
            self.heuristics = heuristics
        if prober is not None:
            self.prober = prober
        return await self.discover(all_containers=all_containers, filters=filters)

    @classmethod
    async def run(
        cls,
        scanner: DockerScanner | None = None,
        heuristics: HeuristicsEvaluator | None = None,
        prober: ProtocolProber | None = None,
        all_containers: bool = False,
        filters: dict[str, Any] | None = None,
        max_concurrency: int = 10,
    ) -> list[McpProbeResult]:
        """Convenience classmethod to instantiate and run discovery.
        
        Args:
            scanner: Optional Docker scanner.
            heuristics: Optional heuristics evaluator.
            prober: Optional protocol prober.
            all_containers: Whether to scan stopped containers.
            filters: Optional Docker API filters.
            max_concurrency: Max concurrency limit.
            
        Returns:
            List of McpProbeResult instances.
        """
        engine = cls(
            scanner=scanner,
            heuristics=heuristics,
            prober=prober,
            max_concurrency=max_concurrency,
        )
        return await engine.discover(all_containers=all_containers, filters=filters)
