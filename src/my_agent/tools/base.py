import json
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ToolResult:
    """Outcome of a single tool dispatch.

    `content` is always a string (what the model will see as observation).
    `is_error=True` signals failure but does NOT raise — the model gets the
    error text and is expected to recover (retry, change strategy, give up
    gracefully).
    """

    content: str
    is_error: bool = False


@dataclass
class Tool:
    """A callable capability the model can invoke.

    `parameters` is a JSON Schema (the same one we ship to the API as part of
    the tool schema). `fn` receives the parsed dict and returns a string.
    """

    name: str
    description: str
    parameters: dict
    fn: Callable[[dict], str]


class ToolRegistry:
    """Name → Tool mapping plus safe dispatch.

    Dispatch never raises: every failure path (unknown tool, bad JSON, fn
    exception) becomes a ToolResult(is_error=True) so the agent loop stays
    simple — it just appends the result and keeps going.

    Optional `hooks` (HookManager) lets observers see PreToolUse / PostToolUse
    events without modifying the loop. Hooks are best-effort and cannot block.
    """

    def __init__(self, hooks: Optional["HookManager"] = None) -> None:  # noqa: F821
        self._tools: dict[str, Tool] = {}
        self._hooks = hooks

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def dispatch(self, name: str, args_json: str) -> ToolResult:
        if self._hooks is not None:
            self._hooks.fire(
                "PreToolUse",
                data={"tool_name": name, "arguments": args_json},
                subject=name,
            )

        if name not in self._tools:
            result = ToolResult(content=f"unknown tool: {name}", is_error=True)
        else:
            try:
                args = json.loads(args_json)
            except json.JSONDecodeError as e:
                result = ToolResult(content=f"invalid JSON arguments: {e}", is_error=True)
            else:
                try:
                    output = self._tools[name].fn(args)
                    result = ToolResult(content=str(output), is_error=False)
                except Exception as e:
                    result = ToolResult(content=f"{type(e).__name__}: {e}", is_error=True)

        if self._hooks is not None:
            self._hooks.fire(
                "PostToolUse",
                data={
                    "tool_name": name,
                    "arguments": args_json,
                    "content": result.content,
                    "is_error": result.is_error,
                },
                subject=name,
            )
        return result
