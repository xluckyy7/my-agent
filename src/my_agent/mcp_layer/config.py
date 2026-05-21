"""Loader for ~/.my-agent/mcp.json — list of MCP servers to spawn at startup.

Schema (matches Claude Desktop's claude_desktop_config.json):

  {
    "servers": {
      "<name>": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
        "env": {"FOO": "bar"}                  // optional
      },
      ...
    }
  }

Missing file → no MCP servers; agent works fine without any.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


class MCPConfigError(ValueError):
    """Raised when ~/.my-agent/mcp.json is present but malformed."""


@dataclass
class MCPServerSpec:
    """One configured MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


def default_mcp_config_path(home: Path) -> Path:
    return home / ".my-agent" / "mcp.json"


def load_mcp_config(home: Path) -> list[MCPServerSpec]:
    path = default_mcp_config_path(home)
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise MCPConfigError(f"{path}: invalid JSON: {e}") from e

    servers_obj = raw.get("servers") or {}
    if not isinstance(servers_obj, dict):
        raise MCPConfigError(f"{path}: 'servers' must be an object")

    specs: list[MCPServerSpec] = []
    for name, body in servers_obj.items():
        specs.append(_parse_one(name, body, path))
    return specs


def _parse_one(name: str, body: dict, source: Path) -> MCPServerSpec:
    if not isinstance(body, dict):
        raise MCPConfigError(f"{source}: server {name!r} must be an object")

    command = body.get("command")
    if not isinstance(command, str) or not command:
        raise MCPConfigError(
            f"{source}: server {name!r} missing required string 'command'"
        )

    args = body.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise MCPConfigError(
            f"{source}: server {name!r} 'args' must be a list of strings"
        )

    env_obj = body.get("env", {}) or {}
    if not isinstance(env_obj, dict):
        raise MCPConfigError(f"{source}: server {name!r} 'env' must be an object")
    env: dict[str, str] = {str(k): str(v) for k, v in env_obj.items()}

    return MCPServerSpec(name=name, command=command, args=list(args), env=env)
