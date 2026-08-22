"""Active protocol handshake prober for Model Context Protocol (MCP) servers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from typing import Any, AsyncIterator
import httpx

from mcp_scout.models import ContainerInfo, McpStatus, McpType, McpProbeResult, ProbeCandidate

MCP_PROTOCOL_VERSION = "2024-11-05"


class ProtocolProber:
    """Probes candidate network endpoints for active MCP servers using Streamable HTTP, SSE, and healthchecks."""

    def __init__(
        self,
        timeout: float = 2.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the protocol prober.
        
        Args:
            timeout: Network request timeout in seconds.
            client: Optional pre-configured httpx.AsyncClient instance.
        """
        self.timeout = timeout
        self._external_client = client

    @asynccontextmanager
    async def _get_client(self) -> AsyncIterator[httpx.AsyncClient]:
        """Provide an httpx.AsyncClient context."""
        if self._external_client is not None:
            yield self._external_client
        else:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                verify=False,
                follow_redirects=True,
            ) as client:
                yield client

    def _ensure_container(
        self,
        host: str,
        candidate: ProbeCandidate,
        container: ContainerInfo | None,
    ) -> ContainerInfo:
        """Ensure a valid ContainerInfo instance exists for results."""
        if container is not None:
            return container
        return ContainerInfo(
            id="candidate-probe",
            name=f"probe-{host}-{candidate.port}",
            image="unknown",
            ip_addresses={"default": host},
            exposed_ports=[candidate.port],
        )

    def _determine_verified_status(self, container: ContainerInfo) -> McpStatus:
        """Determine whether verified server is labeled or unlabeled."""
        return (
            McpStatus.VERIFIED_LABELED
            if container.is_mcp_labeled
            else McpStatus.VERIFIED_UNLABELED
        )

    async def probe_candidate(
        self,
        host: str,
        candidate: ProbeCandidate,
        container: ContainerInfo | None = None,
    ) -> McpProbeResult | None:
        """Probe a candidate endpoint using its designated protocol with fallback.
        
        Args:
            host: Target IP address or hostname.
            candidate: Probe candidate details (port, path, type).
            container: Optional container context.
            
        Returns:
            McpProbeResult if MCP protocol is confirmed, None otherwise.
        """
        effective_container = self._ensure_container(host, candidate, container)

        if candidate.path in ("/healthz", "/health"):
            res = await self.probe_health(host, candidate, effective_container)
            if res is not None:
                return res

        if candidate.candidate_type == McpType.SSE:
            res = await self.probe_sse(host, candidate, effective_container)
            if res is not None:
                return res
            # Fallback to HTTP initialize
            return await self.probe_streamable_http(host, candidate, effective_container)
        else:
            res = await self.probe_streamable_http(host, candidate, effective_container)
            if res is not None:
                return res
            # Fallback to SSE
            return await self.probe_sse(host, candidate, effective_container)

    async def probe_streamable_http(
        self,
        host: str,
        candidate: ProbeCandidate,
        container: ContainerInfo | None = None,
    ) -> McpProbeResult | None:
        """Probe using Streamable HTTP / JSON-RPC initialize method.
        
        Args:
            host: Target IP address or hostname.
            candidate: Candidate endpoint.
            container: Optional container context.
            
        Returns:
            McpProbeResult if valid JSON-RPC initialize response received, None otherwise.
        """
        effective_container = self._ensure_container(host, candidate, container)
        url = f"http://{host}:{candidate.port}{candidate.path}"

        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "roots": {"listChanged": True},
                    "sampling": {},
                },
                "clientInfo": {
                    "name": "mcp-scout",
                    "version": "0.1.0",
                },
            },
        }

        try:
            async with self._get_client() as client:
                response = await client.post(
                    url,
                    json=init_payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, application/x-ndjson, */*",
                    },
                )

                if response.status_code != 200:
                    return None

                data = response.json()
                if not isinstance(data, dict):
                    return None

                # Check JSON-RPC result
                if "result" in data and isinstance(data["result"], dict):
                    res_obj = data["result"]
                    protocol_ver = res_obj.get("protocolVersion")
                    server_info = res_obj.get("serverInfo") or {}
                    server_name = server_info.get("name")
                    server_version = server_info.get("version")
                    capabilities = res_obj.get("capabilities") or {}

                    tools_count, prompts_count, resources_count = await self._query_metadata(
                        client, url
                    )

                    return McpProbeResult(
                        container=effective_container,
                        status=self._determine_verified_status(effective_container),
                        mcp_type=McpType.HTTP,
                        port=candidate.port,
                        path=candidate.path,
                        server_name=server_name,
                        server_version=server_version,
                        protocol_version=protocol_ver,
                        capabilities=capabilities,
                        tools_count=tools_count,
                        prompts_count=prompts_count,
                        resources_count=resources_count,
                    )

                # Check JSON-RPC protocol error indicating valid JSON-RPC server
                if "error" in data and isinstance(data["error"], dict) and "code" in data["error"]:
                    err_msg = data["error"].get("message", "JSON-RPC error response")
                    return McpProbeResult(
                        container=effective_container,
                        status=self._determine_verified_status(effective_container),
                        mcp_type=McpType.HTTP,
                        port=candidate.port,
                        path=candidate.path,
                        error_message=err_msg,
                    )

        except (httpx.HTTPError, asyncio.TimeoutError, json.JSONDecodeError, OSError, Exception):
            return None

        return None

    async def probe_sse(
        self,
        host: str,
        candidate: ProbeCandidate,
        container: ContainerInfo | None = None,
    ) -> McpProbeResult | None:
        """Probe using SSE (Server-Sent Events) endpoint and message channel discovery.
        
        Args:
            host: Target IP address or hostname.
            candidate: Candidate endpoint.
            container: Optional container context.
            
        Returns:
            McpProbeResult if valid SSE stream and MCP channel detected, None otherwise.
        """
        effective_container = self._ensure_container(host, candidate, container)
        url = f"http://{host}:{candidate.port}{candidate.path}"

        try:
            async with self._get_client() as client:
                async with client.stream(
                    "GET",
                    url,
                    headers={"Accept": "text/event-stream"},
                    timeout=self.timeout,
                ) as response:
                    if response.status_code != 200:
                        return None

                    content_type = response.headers.get("Content-Type", "")
                    if "text/event-stream" not in content_type:
                        return None

                    endpoint_path: str | None = None

                    async def _read_sse_events() -> None:
                        nonlocal endpoint_path
                        async for line in response.aiter_lines():
                            line = line.strip()
                            if line.startswith("event: endpoint"):
                                continue
                            if line.startswith("data:"):
                                data_str = line.split("data:", 1)[1].strip()
                                if "messages" in data_str or "session" in data_str.lower() or data_str.startswith("/"):
                                    endpoint_path = data_str
                                    break

                    try:
                        await asyncio.wait_for(
                            _read_sse_events(),
                            timeout=min(self.timeout, 1.0),
                        )
                    except (asyncio.TimeoutError, Exception):
                        pass

                server_name: str | None = None
                server_version: str | None = None
                protocol_version: str | None = None
                capabilities: dict[str, Any] = {}
                tools_count = 0
                prompts_count = 0
                resources_count = 0

                # If endpoint path was discovered, post initialize payload
                if endpoint_path:
                    if endpoint_path.startswith("http://") or endpoint_path.startswith("https://"):
                        post_url = endpoint_path
                    elif endpoint_path.startswith("/"):
                        post_url = f"http://{host}:{candidate.port}{endpoint_path}"
                    else:
                        post_url = f"http://{host}:{candidate.port}/{endpoint_path}"

                    init_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": MCP_PROTOCOL_VERSION,
                            "capabilities": {
                                "roots": {"listChanged": True},
                                "sampling": {},
                            },
                            "clientInfo": {
                                "name": "mcp-scout",
                                "version": "0.1.0",
                            },
                        },
                    }

                    try:
                        post_resp = await client.post(
                            post_url,
                            json=init_payload,
                            headers={"Content-Type": "application/json"},
                        )
                        if post_resp.status_code in (200, 201, 202):
                            try:
                                post_data = post_resp.json()
                                if "result" in post_data and isinstance(post_data["result"], dict):
                                    r_obj = post_data["result"]
                                    protocol_version = r_obj.get("protocolVersion")
                                    s_inf = r_obj.get("serverInfo") or {}
                                    server_name = s_inf.get("name")
                                    server_version = s_inf.get("version")
                                    capabilities = r_obj.get("capabilities") or {}
                            except Exception:
                                pass
                    except Exception:
                        pass

                return McpProbeResult(
                    container=effective_container,
                    status=self._determine_verified_status(effective_container),
                    mcp_type=McpType.SSE,
                    port=candidate.port,
                    path=candidate.path,
                    server_name=server_name,
                    server_version=server_version,
                    protocol_version=protocol_version,
                    capabilities=capabilities,
                    tools_count=tools_count,
                    prompts_count=prompts_count,
                    resources_count=resources_count,
                )

        except (httpx.HTTPError, asyncio.TimeoutError, OSError, Exception):
            return None

    async def probe_health(
        self,
        host: str,
        candidate: ProbeCandidate,
        container: ContainerInfo | None = None,
    ) -> McpProbeResult | None:
        """Probe healthcheck endpoints for FastMCP / MCP markers.
        
        Args:
            host: Target IP address or hostname.
            candidate: Candidate endpoint.
            container: Optional container context.
            
        Returns:
            McpProbeResult if health check indicates MCP service, None otherwise.
        """
        effective_container = self._ensure_container(host, candidate, container)
        url = f"http://{host}:{candidate.port}{candidate.path}"

        try:
            async with self._get_client() as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if isinstance(data, dict):
                            status_val = str(data.get("status", "")).lower()
                            service_val = str(data.get("service", "")).lower()
                            if status_val in ("ok", "healthy", "up") or "fastmcp" in service_val or "mcp" in service_val:
                                name = data.get("name") or data.get("service") or "mcp-service"
                                return McpProbeResult(
                                    container=effective_container,
                                    status=self._determine_verified_status(effective_container),
                                    mcp_type=candidate.candidate_type,
                                    port=candidate.port,
                                    path=candidate.path,
                                    server_name=name,
                                )
                    except Exception:
                        pass
        except Exception:
            return None

        return None

    async def _query_metadata(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> tuple[int, int, int]:
        """Best-effort query for tools, prompts, and resources count via JSON-RPC."""
        tools_count = 0
        prompts_count = 0
        resources_count = 0

        # Send notifications/initialized (best effort)
        try:
            await client.post(
                url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Content-Type": "application/json"},
            )
        except Exception:
            pass

        # Query tools/list
        try:
            t_res = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers={"Content-Type": "application/json"},
            )
            if t_res.status_code == 200:
                t_data = t_res.json()
                if isinstance(t_data, dict) and "result" in t_data:
                    tools = t_data["result"].get("tools")
                    if isinstance(tools, list):
                        tools_count = len(tools)
        except Exception:
            pass

        # Query prompts/list
        try:
            p_res = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": 3, "method": "prompts/list"},
                headers={"Content-Type": "application/json"},
            )
            if p_res.status_code == 200:
                p_data = p_res.json()
                if isinstance(p_data, dict) and "result" in p_data:
                    prompts = p_data["result"].get("prompts")
                    if isinstance(prompts, list):
                        prompts_count = len(prompts)
        except Exception:
            pass

        # Query resources/list
        try:
            r_res = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
                headers={"Content-Type": "application/json"},
            )
            if r_res.status_code == 200:
                r_data = r_res.json()
                if isinstance(r_data, dict) and "result" in r_data:
                    resources = r_data["result"].get("resources")
                    if isinstance(resources, list):
                        resources_count = len(resources)
        except Exception:
            pass

        return tools_count, prompts_count, resources_count
