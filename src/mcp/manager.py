"""MCPManager — manages MCP server connections and tool lifecycle."""

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

import anyio
from mcp.client.session import ClientSession

from src.tools.registry import ToolRegistry
from .transport import create_stdio_transport, create_streamable_http_transport

logger = logging.getLogger(__name__)


def _sanitize(name: str) -> str:
    """Clean a string for use in tool name prefixes."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', name).strip('_').lower() or 'server'


def _resolve_env_vars(value: str | dict | None) -> str | dict | None:
    """Replace ${VAR} patterns in strings with environment variable values."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, str):
        def _replace(m):
            var_name = m.group(1)
            return os.environ.get(var_name, m.group(0))
        return re.sub(r'\$\{(\w+)\}', _replace, value)
    return value


class _ServerConnection:
    """Holds the running task and registered tool names for one server."""

    def __init__(self, task: anyio.abc.TaskStatus | None = None):
        self.task: anyio.abc.TaskStatus | None = None
        self.tool_names: list[str] = []


class MCPManager:
    """Manages MCP server connections: connect, disconnect, reload, and tool registration.

    Lifecycle:
      1. Created during AgentSession init with a ToolRegistry reference.
      2. start() loads persisted configs and auto-connects enabled servers.
      3. Runtime: connect/disconnect/reload called by agent tools or code.
      4. stop() closes all connections and unregisters all MCP tools.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        history_dir: str = "./history",
        tool_prefix: str = "mcp",
    ):
        self.registry = registry
        # Use absolute path to ensure persistence works regardless of CWD
        self.history_dir = os.path.abspath(history_dir)
        self.tool_prefix = tool_prefix
        self._servers: dict[str, dict] = {}          # name -> config dict
        self._connections: dict[str, _ServerConnection] = {}  # name -> runtime state
        self._task_group: anyio.abc.TaskGroup | None = None
        
        # Load config immediately so list_servers() works before start()
        self._load_config()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Load persisted config and auto-connect enabled servers."""
        if self._task_group is not None:
            return

        os.makedirs(self.history_dir, exist_ok=True)
        # Config is now loaded in __init__, but we can refresh it here
        self._load_config()

        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()

        # Auto-connect only servers explicitly enabled by the user
        for name, config in self._servers.items():
            if not config.get("enabled", False):
                continue
            try:
                await self._connect_from_config(config)
            except Exception as e:
                print(f"[mcp] auto-connect failed for {name}: {e}")

        # Register management tools
        from .mcp_tools import create_mcp_tools
        for tool_fn in create_mcp_tools(self):
            is_list = tool_fn.__name__ == "mcp_server_list"
            self.registry.register(
                tool_fn,
                read_only=is_list,
                destructive=tool_fn.__name__ == "mcp_server_remove",
                requires_permission=not is_list,
                concurrency_safe=False,
                tags=("mcp", "management"),
            )

    async def stop(self) -> None:
        """Disconnect all servers and cancel the task group."""
        for name in list(self._connections.keys()):
            await self.disconnect(name)
        if self._task_group:
            await self._task_group.__aexit__(None, None, None)
            self._task_group = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self, config: dict) -> dict:
        """Connect to an MCP server and register its tools."""
        name = config["name"]

        # Disconnect existing connection if any
        if name in self._connections:
            await self.disconnect(name)

        config["enabled"] = True
        self._servers[name] = config
        self._save_config()
        return await self._connect_from_config(config)

    async def _connect_from_config(self, config: dict) -> dict:
        """Internal: establish connection and register tools."""
        # Ensure the task group is started if it hasn't been already.
        # This handles cases where runtime connections are attempted before start()
        # or when the manager was initialized but not explicitly started.
        if self._task_group is None:
            await self.start()

        # Force-unregister any leftover tools for this server before connecting.
        # This prevents "already exists" conflicts when reconnecting, since the
        # background task cleanup may not have completed yet after cancellation.
        name = config["name"]
        prefix = f"{self.tool_prefix}_{_sanitize(name)}"
        for tname in list(self.registry._tools.keys()):
            if tname.startswith(f"{prefix}_"):
                self.registry.unregister(tname)

        # Infer transport: command → stdio, url → streamable-http
        if "command" in config:
            transport = "stdio"
        elif "url" in config:
            transport = config.get("transport", "streamable-http")
        else:
            transport = config.get("transport", "stdio")

        return await self._task_group.start(self._run_server, config)

    async def disconnect(self, name: str, *, disable: bool = False) -> None:
        """Disconnect a server and unregister its tools.

        Args:
            name: Server name.
            disable: If True, mark the server as disabled (won't auto-connect on restart).
        """
        conn = self._connections.pop(name, None)
        if conn is None:
            # Even if no active connection, ensure registry is clean for this prefix
            prefix = f"{self.tool_prefix}_{_sanitize(name)}"
            to_unregister = [
                tname for tname in self.registry._tools.keys()
                if tname.startswith(f"{prefix}_")
            ]
            for tname in to_unregister:
                self.registry.unregister(tname)
            return

        if conn.task:
            conn.task.cancel_scope.cancel()

        for tool_name in conn.tool_names:
            self.registry.unregister(tool_name)

        if disable and name in self._servers:
            self._servers[name]["enabled"] = False
            self._save_config()

    async def toggle_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a server without connecting/disconnecting immediately."""
        if name not in self._servers:
            raise ValueError(f"Unknown server: {name}")
        self._servers[name]["enabled"] = enabled
        self._save_config()

    async def reload(self, name: str) -> dict:
        """Reconnect a server and refresh tool list."""
        if name not in self._servers:
            raise ValueError(f"Unknown server: {name}")
        await self.disconnect(name)
        return await self._connect_from_config(self._servers[name])

    def list_servers(self) -> list[dict]:
        """Return status of all configured servers."""
        result = []
        for name, config in self._servers.items():
            conn = self._connections.get(name)
            transport = "stdio" if "command" in config else "streamable-http"
            result.append({
                "name": name,
                "transport": transport,
                "connected": name in self._connections,
                "enabled": config.get("enabled", False),
                "tool_count": len(conn.tool_names) if conn else 0,
                "last_connected": config.get("last_connected"),
            })
        return result

    async def call_tool(self, server_name: str, tool_name: str, args: dict) -> str:
        """Execute a tool on a specific MCP server.

        Used by the agent management tools to invoke MCP tools indirectly,
        and by the wrapper functions registered in ToolRegistry.
        """
        conn = self._connections.get(server_name)
        if conn is None:
            return f"Error: MCP server '{server_name}' is not connected"
        # The session is stored on the connection — see _run_server
        if not hasattr(conn, 'session') or conn.session is None:
            return f"Error: MCP server '{server_name}' has no active session"
        try:
            result = await conn.session.call_tool(tool_name, args)
            # Extract text content from CallToolResult
            parts = []
            for block in result.content:
                if hasattr(block, 'text'):
                    parts.append(block.text)
                elif hasattr(block, 'data'):
                    parts.append(f"[binary content: {getattr(block, 'mime_type', 'unknown')}]")
                else:
                    parts.append(str(block))
            return "".join(parts) if parts else "(empty response)"
        except Exception as e:
            return f"Error calling {tool_name}: {e}"

    # ------------------------------------------------------------------
    # Internal: background task per server
    # ------------------------------------------------------------------

    async def _run_server(
        self, config: dict, *, task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED
    ) -> dict:
        """Long-lived task: establish transport + session, register tools, then wait."""
        name = config["name"]
        transport = config.get("transport", "stdio")
        prefix = f"{self.tool_prefix}_{_sanitize(name)}"

        # Step 1: establish transport (resolve ${VAR} in env/headers)
        if transport == "stdio":
            transport_cm = create_stdio_transport(
                command=config["command"],
                args=config.get("args", []),
                cwd=config.get("cwd", ""),
                env=_resolve_env_vars(config.get("env")),
            )
        elif transport in ("streamable-http", "sse"):
            transport_cm = create_streamable_http_transport(
                url=config["url"],
                headers=_resolve_env_vars(config.get("headers")),
            )
        else:
            task_status.started({"error": f"Unsupported transport: {transport}"})
            return

        async with transport_cm as transport_result:
            read_stream = transport_result[0]
            write_stream = transport_result[1]

            # Step 2: establish session
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Step 3: discover tools
                tools_result = await session.list_tools()
                tool_names = []
                for tool in tools_result.tools:
                    full_name = f"{prefix}_{tool.name}"
                    if self.registry.get(full_name) is not None:
                        # Should not happen since we pre-clean in _connect_from_config,
                        # but guard against it just in case.
                        logger.warning(
                            "[mcp] tool name conflict, skipping %s (already exists)",
                            full_name,
                        )
                        continue

                    # Create a wrapper function for this tool
                    wrapper = self._make_tool_wrapper(
                        server_name=name,
                        tool_name=tool.name,
                        full_name=full_name,
                        description=tool.description or f"MCP tool {tool.name} from {name}",
                        input_schema=tool.inputSchema,
                    )
                    self.registry.register(
                        wrapper,
                        read_only=False,
                        requires_permission=True,
                        concurrency_safe=False,
                        tags=("mcp", name),
                    )
                    tool_names.append(full_name)

                # Step 4: store connection state
                conn = _ServerConnection()
                conn.tool_names = tool_names
                conn.session = session
                self._connections[name] = conn

                config["enabled"] = True
                config["last_connected"] = datetime.now().isoformat()
                self._save_config()

                logger.info(
                    "[mcp] connected %s (%d tools)", name, len(tool_names)
                )
                task_status.started({
                    "name": name,
                    "tools": tool_names,
                })

                # Step 5: wait until cancelled (disconnect)
                try:
                    await anyio.sleep_forever()
                except anyio.get_cancelled_exc_class():
                    pass

                # Step 6: cleanup on exit
                for tool_name in tool_names:
                    self.registry.unregister(tool_name)
                self._connections.pop(name, None)

    def _make_tool_wrapper(
        self, server_name: str, tool_name: str, full_name: str,
        description: str, input_schema: dict,
    ):
        """Create a function that the ToolRegistry can register as a tool."""
        async def wrapper(**kwargs):
            return await self.call_tool(server_name, tool_name, kwargs)

        wrapper.__name__ = full_name
        wrapper.__doc__ = f"{description}\n[MCP: {server_name}]"

        # Inject the raw MCP inputSchema so the registry exports it directly,
        # preserving format/enum/min/max/etc. that Python type-hints would lose.
        wrapper.__tool_schema__ = {
            "name": full_name,
            "description": f"{description}  [MCP: {server_name}]",
            "parameters": input_schema,
        }

        return wrapper

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Load server config from mcp_servers.json."""
        path = os.path.join(self.history_dir, "mcp_servers.json")
        if not os.path.exists(path):
            logger.info("[mcp] no config file found at %s", path)
            return
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            logger.info("[mcp] loading config from %s", path)
        except Exception as e:
            logger.error("[mcp] failed to load config from %s: %s", path, e)
            return

        # Clear current servers before loading
        self._servers = {}
        if isinstance(raw, dict) and "mcpServers" in raw:
            for name, config in raw["mcpServers"].items():
                config["name"] = name
                # Preserve persisted enabled state; new servers default to False
                config.setdefault("enabled", False)
                # Infer transport: command → stdio, url → streamable-http
                if "command" not in config and "transport" not in config:
                    config["transport"] = "streamable-http" if "url" in config else "stdio"
                self._servers[name] = config

        # Legacy array format: [{"name": "...", "transport": "...", ...}]
        elif isinstance(raw, list):
            for item in raw:
                if "name" not in item:
                    continue
                item.setdefault("enabled", False)
                if "transport" not in item:
                    item["transport"] = "streamable-http" if "url" in item else "stdio"
                self._servers[item["name"]] = item

    def _save_config(self) -> None:
        """Save config in standard mcpServers format."""
        path = os.path.join(self.history_dir, "mcp_servers.json")
        servers = {}
        for name, config in self._servers.items():
            # Save in standard format — strip internal-only fields but keep enabled
            server_config = {
                k: v for k, v in config.items()
                if k not in ("name", "last_connected", "transport")
            }
            # Re-infer transport on save
            if "command" in config:
                # stdio — keep as is
                pass
            elif "url" in config:
                # remote — no transport field needed
                pass
            servers[name] = server_config

        with open(path, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": servers}, f, indent=2, ensure_ascii=False)
