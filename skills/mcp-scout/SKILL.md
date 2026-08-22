---
name: mcp-scout
description: Use when discovering MCP endpoints across running Docker containers, auditing unlabeled MCP services, fixing suspected MCP container setups (like unmounted FastAPI FastMCP routes), or injecting mcp.* labels and net_mcp networks into docker-compose.yaml files.
---

# MCP Scout: Container Discovery & Labeling Skill

Use this skill to scan running containers for Model Context Protocol (MCP) endpoints, troubleshoot suspected MCP services, and configure `mcp.*` Docker labels so that `mcp-router` automatically discovers and routes requests to them.

---

## 1. Quick Discovery Commands

The `mcp-scout` CLI resides in `/containers/dev/mcp-scout`.

```bash
# 1. Run a full discovery scan across all running Docker containers
python3 -m mcp_scout.cli scan

# 2. Filter to show ONLY containers needing attention (unlabeled or suspected)
python3 -m mcp_scout.cli scan --unlabeled-only

# 3. Launch interactive prompt wizard to configure and inject labels
python3 -m mcp_scout.cli interactive

# 4. Probe a specific container directly
python3 -m mcp_scout.cli probe <container_name_or_ip> --port <port> --path /mcp
```

---

## 2. Understanding Discovery Statuses

| Status Badge | Meaning | Action Required |
|---|---|---|
| 🟢 `VERIFIED_LABELED` | Active MCP endpoint confirmed & `mcp.*` labels exist | None. Already auto-discovered by `mcp-router`. |
| 🟡 `VERIFIED_UNLABELED` | Active MCP handshake confirmed, but missing `mcp.*` labels | Run interactive labeling or add `mcp.*` labels to `docker-compose.yaml`. |
| 🔵 `SUSPECTED` | Heuristics (image/env/command) match MCP, but network probe failed | Troubleshoot endpoint: verify app mounted MCP routes, check internal port/path, and check auth. |
| ⚪ `NOT_MCP` | Normal container with no MCP signatures | None. |

---

## 3. Workflow: Resolving `SUSPECTED` MCP Containers

When a container appears as `SUSPECTED` (e.g. `quickcreds`, `playwright-csharp-scraper`), follow these steps:

### Step 1: Inspect the Source Code
Check if the service defines an MCP server but failed to mount the HTTP/SSE transport into its web framework:
- **FastAPI / Python (`fastmcp`)**:
  ```python
  # Ensure the FastMCP instance is mounted onto the FastAPI app:
  from app.mcp_server import mcp
  
  # For Streamable HTTP:
  app.mount("/mcp", mcp.http_app())
  # Or for SSE:
  app.mount("/sse", mcp.sse_app())
  ```
- **Node.js / TypeScript (`@modelcontextprotocol/sdk`)**:
  Verify the Express/Fastify server listens on `0.0.0.0` (not `127.0.0.1`) and handles `/mcp` (POST) or `/sse` (GET).

### Step 2: Verify Network Connectivity & Port Binding
- Check which internal port the container listens on (e.g. `8110`, `8000`, `3000`).
- Ensure the container is connected to `net_mcp` or a shared network that `mcp-router` can reach.

### Step 3: Rebuild & Probe
```bash
# Restart the updated service
cd /containers/<stack> && docker compose up -d --build <service_name>

# Probe directly to verify handshake
python3 -m mcp_scout.cli probe <container_name> --port <internal_port> --path /mcp
```

---

## 4. Standard Docker Labels Contract (`mcp-router`)

When labeling a service in `docker-compose.yaml`, use the canonical `mcp.*` label schema:

```yaml
services:
  my-service:
    container_name: my-service
    # ...
    networks:
      - net_webservices
      - net_mcp           # <-- Ensure net_mcp is attached
    labels:
      # MCP Auto-Discovery Labels for mcp-router:
      - "mcp.enabled=true"
      - "mcp.id=my-service"
      - "mcp.displayName=My Service MCP"
      - "mcp.port=8000"           # Container's internal listening port
      - "mcp.type=http"           # 'http' (Streamable HTTP) or 'sse'
      - "mcp.path=/mcp"           # Default: '/mcp' for http, '/sse' for sse
      - "mcp.categories=infrastructure,tools" # Comma-separated categories

networks:
  net_webservices:
    external: true
  net_mcp:
    external: true
```

---

## 5. Automated Interactive Labeling

Instead of manually typing YAML labels, run:

```bash
python3 /containers/dev/mcp-scout/mcp_scout/cli.py interactive
```

1. It automatically iterates through each `VERIFIED_UNLABELED` and `SUSPECTED` container.
2. Prompts to confirm/override detected fields (`ID`, `Display Name`, `Port`, `Type`, `Path`, `Categories`).
3. Checks if `net_mcp` is attached and offers to attach it.
4. Select **`[A] Apply to compose file`** to atomically inject the labels into `docker-compose.yaml` with a `.bak` backup.
5. Re-run `docker compose up -d` in the stack folder to apply the new container labels.
