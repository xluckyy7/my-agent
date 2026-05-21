"""Sync wrapper over the async `mcp` SDK.

We bridge async → sync by spawning a fresh server / session per call (via
`asyncio.run`). This is correct but slow (each call pays full subprocess
startup cost). v0.8.x will add persistent connections via a background
thread or async-native agent loop.

Public surface:
  - MCPToolSpec       :: descriptor we return for each remote tool
  - MCPCallError      :: raised when a tool returns isError=True
  - fetch_tools_sync(spec) -> list[MCPToolSpec]
  - call_tool_sync(spec, tool_name, args) -> str

Tests mock the internal helpers `_open_session` / `_close_session` so they
never spawn real subprocesses.
"""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import MCPServerSpec


class MCPCallError(RuntimeError):
    """Raised when an MCP server returns isError=True for a tool call."""


@dataclass
class MCPToolSpec:
    """One tool exposed by an MCP server, normalized to our internal shape."""

    name: str
    description: str
    input_schema: dict


# ---------------- internal helpers (mocked in tests) ----------------


async def _open_session(spec: MCPServerSpec):
    """Spawn the configured MCP server, open a ClientSession, initialize.

    The async-context-manager state is squirreled away on the session as
    `_my_agent_stack` so callers can later hand the session to
    `_close_session` without juggling a tuple.
    """
    stack = AsyncExitStack()
    try:
        server_params = StdioServerParameters(
            command=spec.command, args=spec.args, env=spec.env or None
        )
        read, write = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        session._my_agent_stack = stack  # private, our convention
        return session
    except Exception:
        await stack.aclose()
        raise


async def _close_session(session) -> None:
    stack = getattr(session, "_my_agent_stack", None)
    if stack is not None:
        await stack.aclose()


# ---------------- public sync API ----------------


def fetch_tools_sync(spec: MCPServerSpec) -> list[MCPToolSpec]:
    """Spawn server → list its tools → cleanup. Synchronous."""

    async def _go() -> list[MCPToolSpec]:
        session = await _open_session(spec)
        try:
            resp = await session.list_tools()
            return [
                MCPToolSpec(
                    name=t.name,
                    description=getattr(t, "description", "") or "",
                    input_schema=getattr(t, "inputSchema", None) or {"type": "object", "properties": {}},
                )
                for t in (resp.tools or [])
            ]
        finally:
            await _close_session(session)

    return asyncio.run(_go())


def call_tool_sync(spec: MCPServerSpec, tool_name: str, args: dict) -> str:
    """Spawn server → call one tool → cleanup. Synchronous.

    Returns the concatenated text content. Raises MCPCallError if the server
    flagged the result as an error.
    """

    async def _go() -> str:
        session = await _open_session(spec)
        try:
            resp = await session.call_tool(tool_name, args)
            text_parts = [
                c.text
                for c in (resp.content or [])
                if getattr(c, "type", None) == "text"
            ]
            text = "".join(text_parts)
            if getattr(resp, "isError", False):
                raise MCPCallError(text or "MCP tool returned an error with no message")
            return text
        finally:
            await _close_session(session)

    return asyncio.run(_go())
