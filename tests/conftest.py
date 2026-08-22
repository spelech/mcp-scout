from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator
import pytest


class MockServer:
    """Lightweight test HTTP/SSE server wrapper."""

    def __init__(self, host: str, port: int, server: asyncio.Server) -> None:
        self.host = host
        self.port = port
        self.server = server

    async def close(self) -> None:
        self.server.close()
        await self.server.wait_closed()


@pytest.fixture
def sample_container_info_dict() -> dict:
    return {
        "id": "c1234567890abcdef",
        "name": "sample-mcp-server",
        "image": "ghcr.io/sample/mcp-server:latest",
        "ip_addresses": {"net_mcp": "172.20.0.10", "bridge": "172.17.0.2"},
        "exposed_ports": [8080, 8443],
        "env_vars": {"MCP_PORT": "8080", "FASTMCP_PORT": "8080"},
        "labels": {
            "com.docker.compose.service": "sample-service",
            "com.docker.compose.project.working_dir": "/containers/mcp",
            "com.docker.compose.project.config_files": "/containers/mcp/docker-compose.yaml",
        },
        "existing_mcp_labels": {},
    }


@pytest.fixture
async def mock_mcp_http_server() -> AsyncGenerator[MockServer, None]:
    """Mock MCP Streamable HTTP JSON-RPC server."""

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                req_line = line.decode("utf-8", errors="ignore").strip()
                if not req_line:
                    continue
                parts = req_line.split()
                method = parts[0]
                path = parts[1] if len(parts) > 1 else "/"

                headers: dict[str, str] = {}
                content_length = 0
                while True:
                    h_line = await reader.readline()
                    if not h_line or h_line == b"\r\n":
                        break
                    h_str = h_line.decode("utf-8", errors="ignore")
                    if ":" in h_str:
                        k, v = h_str.split(":", 1)
                        headers[k.strip().lower()] = v.strip()
                        if k.strip().lower() == "content-length":
                            content_length = int(v.strip())

                body = b""
                if content_length > 0:
                    body = await reader.readexactly(content_length)

                if method == "POST" and (path == "/mcp" or path == "/" or path.startswith("/api/mcp")):
                    try:
                        data = json.loads(body.decode("utf-8"))
                        req_id = data.get("id", 1)
                        rpc_method = data.get("method")

                        if rpc_method == "initialize":
                            resp_data = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {
                                    "protocolVersion": "2024-11-05",
                                    "capabilities": {
                                        "tools": {"listChanged": True},
                                        "prompts": {},
                                        "resources": {},
                                    },
                                    "serverInfo": {
                                        "name": "mock-mcp-server",
                                        "version": "1.0.0",
                                    },
                                },
                            }
                        elif rpc_method == "notifications/initialized":
                            resp_data = {"jsonrpc": "2.0"}
                        elif rpc_method == "tools/list":
                            resp_data = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {
                                    "tools": [
                                        {"name": "test_tool_1", "description": "A test tool"},
                                        {"name": "test_tool_2", "description": "Another test tool"},
                                    ]
                                },
                            }
                        elif rpc_method == "prompts/list":
                            resp_data = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {
                                    "prompts": [
                                        {"name": "test_prompt_1", "description": "A test prompt"}
                                    ]
                                },
                            }
                        elif rpc_method == "resources/list":
                            resp_data = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {
                                    "resources": [
                                        {"uri": "test://resource1", "name": "Resource 1"}
                                    ]
                                },
                            }
                        else:
                            resp_data = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "error": {"code": -32601, "message": "Method not found"},
                            }

                        resp_bytes = json.dumps(resp_data).encode("utf-8")
                        header_resp = (
                            f"HTTP/1.1 200 OK\r\n"
                            f"Content-Type: application/json\r\n"
                            f"Content-Length: {len(resp_bytes)}\r\n"
                            f"Connection: close\r\n\r\n"
                        ).encode("utf-8")
                        writer.write(header_resp + resp_bytes)
                        await writer.drain()
                        break
                    except Exception:
                        writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                        await writer.drain()
                        break
                else:
                    writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    await writer.drain()
                    break
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    mock_server = MockServer(host=host, port=port, server=server)
    try:
        yield mock_server
    finally:
        await mock_server.close()


@pytest.fixture
async def mock_mcp_sse_server() -> AsyncGenerator[MockServer, None]:
    """Mock MCP SSE Server with endpoint discovery."""

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                req_line = line.decode("utf-8", errors="ignore").strip()
                if not req_line:
                    continue
                parts = req_line.split()
                method = parts[0]
                path = parts[1] if len(parts) > 1 else "/"

                headers: dict[str, str] = {}
                content_length = 0
                while True:
                    h_line = await reader.readline()
                    if not h_line or h_line == b"\r\n":
                        break
                    h_str = h_line.decode("utf-8", errors="ignore")
                    if ":" in h_str:
                        k, v = h_str.split(":", 1)
                        headers[k.strip().lower()] = v.strip()
                        if k.strip().lower() == "content-length":
                            content_length = int(v.strip())

                body = b""
                if content_length > 0:
                    body = await reader.readexactly(content_length)

                if method == "GET" and (path == "/sse" or path.startswith("/sse")):
                    sse_headers = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: text/event-stream\r\n"
                        "Cache-Control: no-cache\r\n"
                        "Connection: keep-alive\r\n\r\n"
                    ).encode("utf-8")
                    writer.write(sse_headers)
                    await writer.drain()

                    # Send endpoint event
                    event_data = "event: endpoint\r\ndata: /messages?session_id=mock-session-99\r\n\r\n"
                    writer.write(event_data.encode("utf-8"))
                    await writer.drain()

                    # Keep open briefly for reading
                    await asyncio.sleep(0.5)
                    break
                elif method == "POST" and "messages" in path:
                    # Message endpoint
                    resp_data = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {
                                "name": "mock-sse-mcp-server",
                                "version": "2.0.0",
                            },
                        },
                    }
                    resp_bytes = json.dumps(resp_data).encode("utf-8")
                    header_resp = (
                        f"HTTP/1.1 200 OK\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(resp_bytes)}\r\n"
                        f"Connection: close\r\n\r\n"
                    ).encode("utf-8")
                    writer.write(header_resp + resp_bytes)
                    await writer.drain()
                    break
                else:
                    writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    await writer.drain()
                    break
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    mock_server = MockServer(host=host, port=port, server=server)
    try:
        yield mock_server
    finally:
        await mock_server.close()


@pytest.fixture
async def mock_fastmcp_health_server() -> AsyncGenerator[MockServer, None]:
    """Mock FastMCP health endpoint server."""

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if line:
                req_line = line.decode("utf-8", errors="ignore").strip()
                parts = req_line.split()
                path = parts[1] if len(parts) > 1 else "/"

                # drain headers
                while True:
                    h_line = await reader.readline()
                    if not h_line or h_line == b"\r\n":
                        break

                if path in ("/healthz", "/health"):
                    resp_data = {"status": "ok", "service": "fastmcp", "name": "health-mcp-server"}
                    resp_bytes = json.dumps(resp_data).encode("utf-8")
                    header_resp = (
                        f"HTTP/1.1 200 OK\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(resp_bytes)}\r\n"
                        f"Connection: close\r\n\r\n"
                    ).encode("utf-8")
                    writer.write(header_resp + resp_bytes)
                    await writer.drain()
                else:
                    writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    mock_server = MockServer(host=host, port=port, server=server)
    try:
        yield mock_server
    finally:
        await mock_server.close()


@pytest.fixture
async def mock_non_mcp_server() -> AsyncGenerator[MockServer, None]:
    """Mock standard non-MCP web server (HTML / 404 / generic)."""

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if line:
                while True:
                    h_line = await reader.readline()
                    if not h_line or h_line == b"\r\n":
                        break
                resp_bytes = b"<html><body>Welcome to Nginx!</body></html>"
                header_resp = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: text/html\r\n"
                    f"Content-Length: {len(resp_bytes)}\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode("utf-8")
                writer.write(header_resp + resp_bytes)
                await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    mock_server = MockServer(host=host, port=port, server=server)
    try:
        yield mock_server
    finally:
        await mock_server.close()
