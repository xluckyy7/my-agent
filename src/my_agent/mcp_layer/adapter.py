"""Adapter:MCP tool descriptor → internal `Tool` instance.

Each MCP server's tool gets wrapped so the rest of our agent (LLMClient,
AgentLoop, REPL) never knows MCP exists. Tool names are namespaced
`<server>__<tool>` to avoid clashes with built-in tools.
"""

import logging

from my_agent.tools.base import Tool

from .client import MCPToolSpec, call_tool_sync, fetch_tools_sync
from .config import MCPServerSpec

logger = logging.getLogger(__name__)


def mcp_tool_to_internal(server: MCPServerSpec, mcp_tool: MCPToolSpec) -> Tool:
    """Build an internal Tool that delegates to call_tool_sync."""

    namespaced_name = f"{server.name}__{mcp_tool.name}"
    description = (
        f"[MCP server: {server.name}] {mcp_tool.description}"
        if mcp_tool.description
        else f"[MCP server: {server.name}] {mcp_tool.name}"
    )

    # Capture by default-arg trick to avoid late-binding gotchas if this code
    # ever lands inside a loop where `mcp_tool.name` changes.
    def _fn(args: dict, _server=server, _name=mcp_tool.name) -> str:
        return call_tool_sync(_server, _name, args)

    return Tool(
        name=namespaced_name,
        description=description,
        parameters=mcp_tool.input_schema or {"type": "object", "properties": {}},
        fn=_fn,
    )


def build_mcp_tools(spec: MCPServerSpec) -> list[Tool]:
    """Discover all tools on `spec` and wrap them as internal Tools.

    A failed discovery (bad command / handshake error / etc.) returns an
    empty list rather than raising — we don't want a misconfigured MCP
    server to crash the whole agent. The error is printed to stderr so the
    user can see what went wrong.
    """
    try:
        mcp_tools = fetch_tools_sync(spec)
    except Exception as e:
        logger.warning("failed to discover tools from server %r: %s", spec.name, e)
        return []
    return [mcp_tool_to_internal(spec, t) for t in mcp_tools]
