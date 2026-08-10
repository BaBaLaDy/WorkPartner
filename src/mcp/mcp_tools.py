"""MCP management tools — exposed to the agent as callable functions."""

from .manager import MCPManager


def create_mcp_tools(manager: MCPManager) -> list:
    """Return a list of MCP management tool functions.

    These are registered to the ToolRegistry so the agent can manage
    MCP servers during conversation.
    """

    async def mcp_server_list() -> str:
        """List all configured MCP servers and their connection status."""
        servers = manager.list_servers()
        if not servers:
            return "No MCP servers configured. Use mcp_server_connect to add one."
        lines = ["Configured MCP servers:", ""]
        for s in servers:
            status = "connected" if s["connected"] else "disconnected"
            lines.append(
                f"- **{s['name']}** ({s['transport']}) — {status}, "
                f"{s['tool_count']} tools"
            )
        return "\n".join(lines)

    async def mcp_server_connect(
        name: str,
        command: str = "",
        args: str = "",
        url: str = "",
        headers: str = "",
        env: str = "",
    ) -> str:
        """Connect to a new MCP server.

        Args:
            name: Server name identifier
            command: Command to run (for stdio servers like npx/uvx)
            args: Space-separated command arguments (for stdio)
            url: Server URL (for remote/HTTP servers)
            headers: JSON string of HTTP headers (for HTTP servers)
            env: JSON string of environment variables (for stdio servers)
        """
        import json

        config = {"name": name}

        if command:
            config["command"] = command
            config["args"] = args.split() if args else []
            if env:
                try:
                    config["env"] = json.loads(env)
                except json.JSONDecodeError:
                    return "Error: 'env' must be valid JSON"
        elif url:
            config["url"] = url
            if headers:
                try:
                    config["headers"] = json.loads(headers)
                except json.JSONDecodeError:
                    return "Error: 'headers' must be valid JSON"
        else:
            return "Error: provide either 'command' (stdio) or 'url' (HTTP)"

        try:
            result = await manager.connect(config)
            return (
                f"Connected to '{name}'. "
                f"Added {len(result['tools'])} tools: "
                + ", ".join(result["tools"])
            )
        except Exception as e:
            return f"Error connecting to '{name}': {e}"

    async def mcp_server_disconnect(name: str) -> str:
        """Disconnect an MCP server (keeps configuration).

        Args:
            name: Server name to disconnect
        """
        if name not in manager._servers:
            return f"Error: server '{name}' not found"
        if name not in manager._connections:
            return f"Server '{name}' is not connected"
        await manager.disconnect(name)
        return f"Disconnected from '{name}'"

    async def mcp_server_remove(name: str) -> str:
        """Remove an MCP server completely (disconnect and delete config).

        Args:
            name: Server name to remove
        """
        if name not in manager._servers:
            return f"Error: server '{name}' not found"
        await manager.disconnect(name)
        del manager._servers[name]
        manager._save_config()
        return f"Removed server '{name}'"

    async def mcp_server_reload(name: str) -> str:
        """Reload an MCP server (reconnect and refresh tool list).

        Args:
            name: Server name to reload
        """
        if name not in manager._servers:
            return f"Error: server '{name}' not found"
        try:
            result = await manager.reload(name)
            return (
                f"Reloaded '{name}'. "
                f"Added {len(result['tools'])} tools: "
                + ", ".join(result["tools"])
            )
        except Exception as e:
            return f"Error reloading '{name}': {e}"

    return [
        mcp_server_list,
        mcp_server_connect,
        mcp_server_disconnect,
        mcp_server_remove,
        mcp_server_reload,
    ]
