"""MCP server management routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/mcp", tags=["mcp"])


def get_engine():
    from src.api.server import get_app_state
    return get_app_state().engine


class McpConnectRequest(BaseModel):
    name: str
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    env: dict[str, str] | None = None
    cwd: str | None = None


class McpUpdateRequest(BaseModel):
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    env: dict[str, str] | None = None
    cwd: str | None = None


class McpConfigReplaceRequest(BaseModel):
    mcpServers: dict[str, Any]


@router.get("/servers")
def list_mcp_servers():
    """List all configured MCP servers and their connection status."""
    engine = get_engine()
    servers = engine.mcp.list_servers()
    # Also include the raw config for editing
    for s in servers:
        config = engine.mcp._servers.get(s["name"], {})
        s["config"] = {
            "command": config.get("command"),
            "args": config.get("args", []),
            "url": config.get("url"),
            "headers": config.get("headers", {}),
            "env": config.get("env", {}),
            "cwd": config.get("cwd"),
        }
    return {"servers": servers}


@router.post("/servers")
async def connect_mcp_server(body: McpConnectRequest):
    """Connect to (or add) an MCP server and register its tools."""
    engine = get_engine()
    config: dict[str, Any] = {"name": body.name}
    if body.command:
        config["command"] = body.command
        config["args"] = body.args or []
        if body.cwd:
            config["cwd"] = body.cwd
        if body.env:
            config["env"] = body.env
    elif body.url:
        config["url"] = body.url
        if body.headers:
            config["headers"] = body.headers
    else:
        return {"error": "Provide either command (stdio) or url (HTTP)"}

    try:
        result = await engine.mcp.connect(config)
        return {"ok": True, "tools": result.get("tools", [])}
    except Exception as e:
        return {"error": str(e)}


@router.put("/config")
async def replace_mcp_config(body: McpConfigReplaceRequest):
    """Replace entire MCP configuration and connect enabled servers."""
    engine = get_engine()

    # Ensure MCP is started (initializes task group if not already started)
    await engine.start_mcp()

    # 1. Disconnect all current servers
    for name in list(engine.mcp._connections.keys()):
        try:
            await engine.mcp.disconnect(name, disable=True)
        except Exception:
            pass

    # 2. Update server configs
    new_servers = {}
    for name, cfg in body.mcpServers.items():
        config = dict(cfg)
        config["name"] = name
        # Default new servers to disabled
        config.setdefault("enabled", False)
        # Infer transport
        if "command" not in config and "transport" not in config:
            config["transport"] = "streamable-http" if "url" in config else "stdio"
        new_servers[name] = config

    engine.mcp._servers = new_servers
    engine.mcp._save_config()

    # 3. Connect only enabled servers
    results = {}
    for name, config in new_servers.items():
        if not config.get("enabled", False):
            results[name] = {"ok": True, "enabled": False, "skipped": True}
            continue
        try:
            res = await engine.mcp._connect_from_config(config)
            results[name] = {"ok": True, "tools": res.get("tools", [])}
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)}

    return {"ok": True, "results": results}


@router.patch("/servers/{name}")
async def update_mcp_server(name: str, body: McpUpdateRequest):
    """Update an existing MCP server config and reconnect."""
    engine = get_engine()
    if name not in engine.mcp._servers:
        return {"error": f"Server '{name}' not found"}

    config = dict(engine.mcp._servers[name])

    if body.command is not None:
        config["command"] = body.command
    if body.args is not None:
        config["args"] = body.args
    if body.url is not None:
        config["url"] = body.url
    if body.headers is not None:
        config["headers"] = body.headers
    if body.env is not None:
        config["env"] = body.env
    if body.cwd is not None:
        config["cwd"] = body.cwd

    try:
        result = await engine.mcp.connect(config)
        return {"ok": True, "tools": result.get("tools", [])}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/servers/{name}")
async def remove_mcp_server(name: str):
    """Remove an MCP server completely (disconnect and delete config)."""
    engine = get_engine()
    if name not in engine.mcp._servers:
        return {"error": f"Server '{name}' not found"}
    try:
        await engine.mcp.disconnect(name)
    except Exception:
        pass
    del engine.mcp._servers[name]
    engine.mcp._save_config()
    return {"ok": True}


@router.post("/servers/{name}/disconnect")
async def disconnect_mcp_server(name: str):
    """Disconnect an MCP server and mark as disabled (won't auto-connect on restart)."""
    engine = get_engine()
    if name not in engine.mcp._connections:
        return {"error": f"Server '{name}' is not connected"}
    try:
        await engine.mcp.disconnect(name, disable=True)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


@router.post("/servers/{name}/toggle")
async def toggle_mcp_server(name: str):
    """Toggle a server's enabled state without connecting/disconnecting."""
    engine = get_engine()
    if name not in engine.mcp._servers:
        return {"error": f"Server '{name}' not found"}
    try:
        current = engine.mcp._servers[name].get("enabled", False)
        await engine.mcp.toggle_enabled(name, not current)
        return {"ok": True, "enabled": not current}
    except Exception as e:
        return {"error": str(e)}


@router.post("/servers/{name}/reload")
async def reload_mcp_server(name: str):
    """Reload (reconnect) an MCP server and refresh tools."""
    engine = get_engine()
    if name not in engine.mcp._servers:
        return {"error": f"Server '{name}' not found"}
    try:
        result = await engine.mcp.reload(name)
        return {"ok": True, "tools": result.get("tools", [])}
    except Exception as e:
        return {"error": str(e)}
