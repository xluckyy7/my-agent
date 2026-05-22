"""Hook framework (Claude-Code style).

Hooks let you observe / instrument the agent without modifying its core. A hook
is either a shell command or a Python callable, registered against a named
event in ~/.my-agent/hooks.json. The agent fires these events at key
lifecycle points (see HOOK_EVENTS).

Config schema (matches Claude Code's settings.json `hooks` block):

  {
    "hooks": {
      "PreToolUse": [
        {
          "matcher": "run_bash|write_file",     # optional regex; "" = all
          "type": "command",
          "command": "/usr/bin/env logger",
          "timeout": 5
        },
        {
          "type": "python",
          "module": "my_agent.plugins.langfuse_plugin",
          "function": "on_pre_tool"
        }
      ],
      "Stop": [...]
    }
  }

Each fired hook receives a HookEvent with:
  - event:      str   (e.g. "PreToolUse")
  - timestamp:  float (unix epoch seconds)
  - data:       dict  (event-specific payload; freeform)

Command hooks get the event as JSON on stdin. Python hooks get the HookEvent
object directly. Both are best-effort: failures are logged to stderr, never
raised — a broken hook must not crash the agent.
"""

import importlib
import json
import logging
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

HOOK_EVENTS = (
    "SessionStart",       # agent boot, before any turn
    "UserPromptSubmit",   # user input received (CLI/REPL/web)
    "PreModelCall",       # before LLMClient.send/stream
    "PostModelCall",      # after LLMClient.send/stream returns
    "PreToolUse",         # before ToolRegistry.dispatch
    "PostToolUse",        # after ToolRegistry.dispatch
    "Stop",               # agent finished a turn
)


class HookConfigError(ValueError):
    """Raised when ~/.my-agent/hooks.json is malformed."""


@dataclass
class HookSpec:
    """One configured hook entry."""

    type: str  # "command" | "python"
    matcher: str = ""           # regex on `subject` arg; "" = match all
    command: str = ""           # for type="command"
    timeout: int = 5            # for type="command"
    module: str = ""            # for type="python"
    function: str = ""          # for type="python"


@dataclass
class HookEvent:
    """Payload passed to each hook callback."""

    event: str
    timestamp: float
    data: dict = field(default_factory=dict)


# ===================================================================
# Config loader
# ===================================================================


def load_hooks(home: Path) -> dict[str, list[HookSpec]]:
    """Load ~/.my-agent/hooks.json → {event_name: [HookSpec, ...]}."""
    path = home / ".my-agent" / "hooks.json"
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HookConfigError(f"{path}: invalid JSON: {e}") from e

    hooks_obj = raw.get("hooks") or {}
    if not isinstance(hooks_obj, dict):
        raise HookConfigError(f"{path}: 'hooks' must be an object")

    out: dict[str, list[HookSpec]] = {}
    for event_name, entries in hooks_obj.items():
        if event_name not in HOOK_EVENTS:
            raise HookConfigError(
                f"{path}: unknown event {event_name!r}; valid: {list(HOOK_EVENTS)}"
            )
        if not isinstance(entries, list):
            raise HookConfigError(f"{path}: {event_name!r} must be a list")
        out[event_name] = [_parse_spec(e, event_name, path) for e in entries]
    return out


def _parse_spec(entry: dict, event_name: str, path: Path) -> HookSpec:
    if not isinstance(entry, dict):
        raise HookConfigError(f"{path}: {event_name} entry must be object")
    t = entry.get("type")
    if t not in ("command", "python"):
        raise HookConfigError(
            f"{path}: {event_name} entry has invalid type {t!r} (need 'command' or 'python')"
        )
    spec = HookSpec(type=t)
    spec.matcher = str(entry.get("matcher") or "")
    if t == "command":
        cmd = entry.get("command")
        if not isinstance(cmd, str) or not cmd:
            raise HookConfigError(
                f"{path}: {event_name} command hook requires non-empty 'command'"
            )
        spec.command = cmd
        spec.timeout = int(entry.get("timeout") or 5)
    else:  # python
        mod = entry.get("module")
        fn = entry.get("function")
        if not isinstance(mod, str) or not mod:
            raise HookConfigError(
                f"{path}: {event_name} python hook requires non-empty 'module'"
            )
        if not isinstance(fn, str) or not fn:
            raise HookConfigError(
                f"{path}: {event_name} python hook requires non-empty 'function'"
            )
        spec.module = mod
        spec.function = fn
    return spec


# ===================================================================
# HookManager
# ===================================================================


class HookManager:
    """Fire hooks at event boundaries. Best-effort, never raises."""

    def __init__(self, specs: dict[str, list[HookSpec]]):
        self._specs = specs
        # Cached resolved Python callables: (module, function) -> callable
        self._py_cache: dict[tuple[str, str], Callable[[HookEvent], Any]] = {}

    def fire(
        self,
        event_name: str,
        data: dict | None = None,
        *,
        subject: str = "",
    ) -> None:
        """Dispatch all matching hooks for `event_name`.

        `subject` is matched against each hook's `matcher` regex. Pass the
        tool name for tool events, the model name for model events, etc.
        Empty subject matches any (or use empty matcher).
        """
        specs = self._specs.get(event_name)
        if not specs:
            return
        event = HookEvent(event=event_name, timestamp=time.time(), data=data or {})
        for spec in specs:
            if spec.matcher and not re.search(spec.matcher, subject):
                continue
            try:
                self._run_one(spec, event)
            except Exception as e:
                logger.warning("%s via %s failed: %s", event_name, spec.type, e)

    def _run_one(self, spec: HookSpec, event: HookEvent) -> None:
        if spec.type == "command":
            self._run_command(spec, event)
        elif spec.type == "python":
            self._run_python(spec, event)

    def _run_command(self, spec: HookSpec, event: HookEvent) -> None:
        payload = json.dumps(asdict(event), ensure_ascii=False)
        subprocess.run(
            spec.command,
            shell=True,
            input=payload,
            text=True,
            timeout=spec.timeout,
            capture_output=True,
        )

    def _run_python(self, spec: HookSpec, event: HookEvent) -> None:
        key = (spec.module, spec.function)
        if key not in self._py_cache:
            mod = importlib.import_module(spec.module)
            self._py_cache[key] = getattr(mod, spec.function)
        self._py_cache[key](event)
