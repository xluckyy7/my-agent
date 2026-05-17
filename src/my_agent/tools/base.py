import json
from dataclasses import dataclass
from typing import Callable


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
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

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
        if name not in self._tools:
            return ToolResult(content=f"unknown tool: {name}", is_error=True)
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as e:
            return ToolResult(content=f"invalid JSON arguments: {e}", is_error=True)
        try:
            output = self._tools[name].fn(args)
        except Exception as e:
            return ToolResult(content=f"{type(e).__name__}: {e}", is_error=True)
        return ToolResult(content=str(output), is_error=False)
