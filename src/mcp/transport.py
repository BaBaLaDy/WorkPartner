"""Transport layer factory — creates MCP client streams for different transports."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.shared.message import SessionMessage

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def create_stdio_transport(
    command: str, args: list[str], cwd: str = "", env: dict[str, str] | None = None
) -> AsyncGenerator[
    tuple[MemoryObjectReceiveStream[SessionMessage | Exception], MemoryObjectSendStream[SessionMessage]],
    None,
]:
    """Create stdio transport — spawns a subprocess.

    Yields (read_stream, write_stream).
    """
    import shutil
    import sys

    # Windows fix: common commands like npx/uvx are .cmd files and need full resolution
    actual_command = command
    if sys.platform == "win32" and not command.lower().endswith((".exe", ".cmd", ".bat")):
        resolved = shutil.which(command)
        if resolved:
            actual_command = resolved
        else:
            # Try appending .cmd or .exe if which failed
            for ext in (".cmd", ".exe", ".bat"):
                if shutil.which(command + ext):
                    actual_command = command + ext
                    break

    params = StdioServerParameters(
        command=actual_command,
        args=args,
        cwd=cwd or None,
        env=env,
    )
    async with stdio_client(params) as (read, write):
        yield (read, write)


@asynccontextmanager
async def create_streamable_http_transport(
    url: str, headers: dict[str, str] | None = None
) -> AsyncGenerator[
    tuple[MemoryObjectReceiveStream[SessionMessage | Exception], MemoryObjectSendStream[SessionMessage]],
    None,
]:
    """Create streamable-http transport — HTTP POST + SSE.

    Yields (read_stream, write_stream, get_session_id).
    """
    import httpx

    client_kwargs = {}
    if headers:
        client_kwargs["headers"] = headers

    async with streamable_http_client(
        url,
        http_client=httpx.AsyncClient(**client_kwargs) if client_kwargs else None
    ) as (read, write, _get_session_id):
        yield (read, write)
