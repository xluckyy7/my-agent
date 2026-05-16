from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class ToolCall:
    """A single tool call requested by the model.

    `arguments` is a JSON string per OpenAI protocol — not a dict. Callers must
    json.loads() before invoking the underlying function.
    """

    id: str
    name: str
    arguments: str

    def to_api_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class Message:
    """One entry in the conversation history.

    Shapes by role:
      - system / user:  content=str
      - assistant:      content=str|None, optional tool_calls=[...]
      - tool:           content=str (tool output), tool_call_id, name
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_api_dict(self) -> dict:
        if self.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": self.tool_call_id,
                "name": self.name,
                "content": self.content,
            }
        d: dict = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [tc.to_api_dict() for tc in self.tool_calls]
        return d


@dataclass
class Response:
    """Normalized result of one LLM call."""

    content: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    raw: dict = field(default_factory=dict)
