"""Tests for MCPClient sync wrapper.

We mock the mcp SDK's async API so tests don't actually spawn subprocesses.
The thing we own and want to verify is: sync entry → async coordination →
return shape match what callers expect.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from my_agent.mcp_layer.client import MCPCallError, fetch_tools_sync, call_tool_sync
from my_agent.mcp_layer.config import MCPServerSpec


def _fake_session_factory(tools=None, call_result=None):
    """Build a MagicMock that mimics mcp.ClientSession's async context-manager
    + async methods, returning tools / call_result as we specify."""
    session = MagicMock()
    session.initialize = AsyncMock(return_value=None)

    list_resp = MagicMock()
    list_resp.tools = tools or []
    session.list_tools = AsyncMock(return_value=list_resp)

    call_resp = MagicMock()
    call_resp.content = call_result or []
    call_resp.isError = False
    session.call_tool = AsyncMock(return_value=call_resp)

    return session


def _fake_tool(name, description="", input_schema=None):
    t = MagicMock()
    t.name = name
    t.description = description
    t.inputSchema = input_schema or {"type": "object", "properties": {}}
    return t


def _fake_text_content(text):
    c = MagicMock()
    c.type = "text"
    c.text = text
    return c


# ---------------- fetch_tools_sync ----------------


def test_fetch_tools_sync_returns_tool_specs(mocker):
    spec = MCPServerSpec(name="srv", command="echo", args=["x"])

    fake_tools = [
        _fake_tool("read", "Read a thing", {"type": "object", "properties": {"path": {"type": "string"}}}),
        _fake_tool("write", "Write a thing"),
    ]
    fake_session = _fake_session_factory(tools=fake_tools)

    # Patch the SDK pieces our client relies on
    mocker.patch(
        "my_agent.mcp_layer.client._open_session",
        new=AsyncMock(return_value=fake_session),
    )
    mocker.patch("my_agent.mcp_layer.client._close_session", new=AsyncMock())

    out = fetch_tools_sync(spec)
    assert len(out) == 2
    assert out[0].name == "read"
    assert out[0].description == "Read a thing"
    assert "properties" in out[0].input_schema
    assert out[1].name == "write"


def test_fetch_tools_sync_propagates_exceptions(mocker):
    spec = MCPServerSpec(name="srv", command="bad", args=[])
    mocker.patch(
        "my_agent.mcp_layer.client._open_session",
        new=AsyncMock(side_effect=RuntimeError("spawn failed")),
    )
    with pytest.raises(RuntimeError, match="spawn failed"):
        fetch_tools_sync(spec)


# ---------------- call_tool_sync ----------------


def test_call_tool_sync_returns_text_concatenated(mocker):
    spec = MCPServerSpec(name="srv", command="x")
    fake_session = _fake_session_factory(
        call_result=[_fake_text_content("hello "), _fake_text_content("world")]
    )
    mocker.patch(
        "my_agent.mcp_layer.client._open_session",
        new=AsyncMock(return_value=fake_session),
    )
    mocker.patch("my_agent.mcp_layer.client._close_session", new=AsyncMock())

    out = call_tool_sync(spec, "do_thing", {"x": 1})
    assert out == "hello world"

    # Verify the underlying call_tool was called with our args
    fake_session.call_tool.assert_awaited_once_with("do_thing", {"x": 1})


def test_call_tool_sync_raises_on_error_result(mocker):
    spec = MCPServerSpec(name="srv", command="x")
    fake_session = _fake_session_factory(call_result=[_fake_text_content("oops")])
    fake_session.call_tool.return_value.isError = True
    mocker.patch(
        "my_agent.mcp_layer.client._open_session",
        new=AsyncMock(return_value=fake_session),
    )
    mocker.patch("my_agent.mcp_layer.client._close_session", new=AsyncMock())

    with pytest.raises(MCPCallError, match="oops"):
        call_tool_sync(spec, "broken_tool", {})


def test_call_tool_sync_handles_empty_content(mocker):
    spec = MCPServerSpec(name="srv", command="x")
    fake_session = _fake_session_factory(call_result=[])
    mocker.patch(
        "my_agent.mcp_layer.client._open_session",
        new=AsyncMock(return_value=fake_session),
    )
    mocker.patch("my_agent.mcp_layer.client._close_session", new=AsyncMock())

    out = call_tool_sync(spec, "do_thing", {})
    assert out == ""


def test_call_tool_sync_skips_non_text_content(mocker):
    """Tool returning image/resource/etc. → we just keep text portions for now."""
    spec = MCPServerSpec(name="srv", command="x")

    text = _fake_text_content("real text")
    image = MagicMock()
    image.type = "image"  # not "text"

    fake_session = _fake_session_factory(call_result=[image, text])
    mocker.patch(
        "my_agent.mcp_layer.client._open_session",
        new=AsyncMock(return_value=fake_session),
    )
    mocker.patch("my_agent.mcp_layer.client._close_session", new=AsyncMock())

    out = call_tool_sync(spec, "do_thing", {})
    assert out == "real text"
