"""Tests for MCP → internal Tool adapter."""

from unittest.mock import patch

from my_agent.mcp_layer.adapter import build_mcp_tools, mcp_tool_to_internal
from my_agent.mcp_layer.client import MCPToolSpec
from my_agent.mcp_layer.config import MCPServerSpec


def test_adapter_namespaces_tool_name():
    """Internal tool name is `<server>__<tool>` to avoid clash with built-ins."""
    spec = MCPServerSpec(name="filesystem", command="npx")
    mcp_tool = MCPToolSpec(
        name="read_file", description="Read a file", input_schema={"type": "object"}
    )
    tool = mcp_tool_to_internal(spec, mcp_tool)
    assert tool.name == "filesystem__read_file"


def test_adapter_preserves_description_and_schema():
    spec = MCPServerSpec(name="x", command="x")
    mcp_tool = MCPToolSpec(
        name="t",
        description="tool description",
        input_schema={"type": "object", "properties": {"a": {"type": "string"}}},
    )
    tool = mcp_tool_to_internal(spec, mcp_tool)
    assert "tool description" in tool.description
    assert tool.parameters == {
        "type": "object",
        "properties": {"a": {"type": "string"}},
    }


def test_adapter_description_marks_provenance():
    """Augment description so the model knows this tool is from MCP and which server."""
    spec = MCPServerSpec(name="filesystem", command="x")
    mcp_tool = MCPToolSpec(name="read", description="Read a file", input_schema={})
    tool = mcp_tool_to_internal(spec, mcp_tool)
    assert "filesystem" in tool.description.lower() or "MCP" in tool.description


def test_adapter_fn_calls_mcp_call_tool_sync():
    spec = MCPServerSpec(name="srv", command="x")
    mcp_tool = MCPToolSpec(name="echo", description="", input_schema={})
    tool = mcp_tool_to_internal(spec, mcp_tool)

    with patch("my_agent.mcp_layer.adapter.call_tool_sync") as mock_call:
        mock_call.return_value = "echoed back"
        out = tool.fn({"x": "hello"})

    assert out == "echoed back"
    mock_call.assert_called_once_with(spec, "echo", {"x": "hello"})


def test_adapter_fn_propagates_errors():
    """Raise from underlying call_tool_sync → ToolRegistry will catch and wrap."""
    spec = MCPServerSpec(name="srv", command="x")
    mcp_tool = MCPToolSpec(name="t", description="", input_schema={})
    tool = mcp_tool_to_internal(spec, mcp_tool)

    with patch(
        "my_agent.mcp_layer.adapter.call_tool_sync",
        side_effect=RuntimeError("server died"),
    ):
        try:
            tool.fn({})
        except RuntimeError as e:
            assert "server died" in str(e)
        else:
            raise AssertionError("expected RuntimeError")


# ---------------- build_mcp_tools (full server discovery + adapter) ----------------


def test_build_mcp_tools_discovers_and_wraps(mocker):
    spec = MCPServerSpec(name="filesystem", command="x")
    mcp_tools = [
        MCPToolSpec(name="read_file", description="r", input_schema={}),
        MCPToolSpec(name="write_file", description="w", input_schema={}),
    ]
    mocker.patch(
        "my_agent.mcp_layer.adapter.fetch_tools_sync",
        return_value=mcp_tools,
    )

    tools = build_mcp_tools(spec)
    names = [t.name for t in tools]
    assert names == ["filesystem__read_file", "filesystem__write_file"]


def test_build_mcp_tools_returns_empty_on_failure(mocker):
    """A broken / unreachable MCP server should not crash startup —
    log + skip + agent continues with built-in tools."""
    spec = MCPServerSpec(name="broken", command="false")  # always exits 1
    mocker.patch(
        "my_agent.mcp_layer.adapter.fetch_tools_sync",
        side_effect=RuntimeError("could not spawn"),
    )

    tools = build_mcp_tools(spec)
    assert tools == []
