"""Tests for ~/.my-agent/mcp.json loader."""

import json

import pytest

from my_agent.mcp_layer.config import (
    MCPConfigError,
    MCPServerSpec,
    default_mcp_config_path,
    load_mcp_config,
)


def _write_config(home, payload):
    path = home / ".my-agent" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_mcp_config_returns_empty_when_missing(tmp_path):
    """No mcp.json → no MCP servers; agent still works fine."""
    assert load_mcp_config(tmp_path) == []


def test_default_mcp_config_path_under_home(tmp_path):
    p = default_mcp_config_path(tmp_path)
    assert p == tmp_path / ".my-agent" / "mcp.json"


def test_load_mcp_config_parses_servers(tmp_path):
    _write_config(tmp_path, {
        "servers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                "env": {"DEBUG": "1"},
            },
            "fetch": {
                "command": "uvx",
                "args": ["mcp-server-fetch"],
            },
        }
    })

    specs = load_mcp_config(tmp_path)
    by_name = {s.name: s for s in specs}

    assert "filesystem" in by_name
    assert by_name["filesystem"].command == "npx"
    assert by_name["filesystem"].args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    assert by_name["filesystem"].env == {"DEBUG": "1"}

    assert "fetch" in by_name
    assert by_name["fetch"].command == "uvx"
    assert by_name["fetch"].args == ["mcp-server-fetch"]
    assert by_name["fetch"].env == {}  # default empty


def test_load_mcp_config_rejects_missing_command(tmp_path):
    _write_config(tmp_path, {"servers": {"bad": {"args": ["x"]}}})
    with pytest.raises(MCPConfigError, match="command"):
        load_mcp_config(tmp_path)


def test_load_mcp_config_rejects_non_string_command(tmp_path):
    _write_config(tmp_path, {"servers": {"bad": {"command": 123}}})
    with pytest.raises(MCPConfigError, match="command"):
        load_mcp_config(tmp_path)


def test_load_mcp_config_rejects_non_list_args(tmp_path):
    _write_config(tmp_path, {"servers": {"bad": {"command": "x", "args": "not-a-list"}}})
    with pytest.raises(MCPConfigError, match="args"):
        load_mcp_config(tmp_path)


def test_load_mcp_config_rejects_invalid_json(tmp_path):
    path = tmp_path / ".my-agent" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json{{", encoding="utf-8")
    with pytest.raises(MCPConfigError):
        load_mcp_config(tmp_path)


def test_load_mcp_config_empty_file_treated_as_no_servers(tmp_path):
    path = tmp_path / ".my-agent" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    assert load_mcp_config(tmp_path) == []


def test_mcp_server_spec_defaults():
    s = MCPServerSpec(name="x", command="cmd")
    assert s.args == []
    assert s.env == {}
