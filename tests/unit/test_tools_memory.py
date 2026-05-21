"""Tests for the `remember` tool — appends entries to user-level MEMORY.md."""

import pytest

from my_agent.agent.memory import default_user_memory_path
from my_agent.tools.memory_tool import make_remember_tool


def test_remember_creates_file_when_missing(tmp_path):
    tool = make_remember_tool(home=tmp_path)
    out = tool.fn({"content": "user prefers terse output"})
    target = default_user_memory_path(tmp_path)
    assert target.exists()
    assert "user prefers terse output" in target.read_text()
    assert "saved" in out.lower() or "ok" in out.lower()


def test_remember_appends_to_existing_file(tmp_path):
    tool = make_remember_tool(home=tmp_path)
    tool.fn({"content": "first memory"})
    tool.fn({"content": "second memory"})

    body = default_user_memory_path(tmp_path).read_text()
    assert "first memory" in body
    assert "second memory" in body
    assert body.index("first memory") < body.index("second memory")


def test_remember_includes_timestamp(tmp_path):
    tool = make_remember_tool(home=tmp_path)
    tool.fn({"content": "with timestamp"})
    body = default_user_memory_path(tmp_path).read_text()
    # Format we'll use: a bullet + ISO date prefix
    assert "with timestamp" in body
    # Should contain a recognizable date pattern (YYYY-MM-DD)
    import re

    assert re.search(r"\d{4}-\d{2}-\d{2}", body)


def test_remember_rejects_empty_content(tmp_path):
    tool = make_remember_tool(home=tmp_path)
    with pytest.raises(ValueError, match="empty"):
        tool.fn({"content": ""})
    with pytest.raises(ValueError, match="empty"):
        tool.fn({"content": "   "})


def test_remember_creates_parent_dirs(tmp_path):
    """home/.my-agent/memory/ may not exist yet."""
    tool = make_remember_tool(home=tmp_path)
    tool.fn({"content": "test"})
    assert default_user_memory_path(tmp_path).parent.exists()


def test_remember_schema_shape(tmp_path):
    tool = make_remember_tool(home=tmp_path)
    s = tool.parameters
    assert s["type"] == "object"
    assert "content" in s["properties"]
    assert s["required"] == ["content"]


def test_remember_metadata(tmp_path):
    tool = make_remember_tool(home=tmp_path)
    assert tool.name == "remember"
    assert tool.description
    assert callable(tool.fn)


def test_remember_via_registry_dispatch(tmp_path):
    from my_agent.tools.base import ToolRegistry

    tool = make_remember_tool(home=tmp_path)
    reg = ToolRegistry()
    reg.register(tool)
    res = reg.dispatch("remember", '{"content": "registry test"}')
    assert res.is_error is False
    assert "registry test" in default_user_memory_path(tmp_path).read_text()
