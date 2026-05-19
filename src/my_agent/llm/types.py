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

    @classmethod
    def from_api_dict(cls, d: dict) -> "Message":
        """Reconstruct a Message from its serialized form (round-trip of to_api_dict)."""
        role = d["role"]
        if role == "tool":
            return cls(
                role="tool",
                tool_call_id=d["tool_call_id"],
                name=d.get("name"),
                content=d.get("content"),
            )
        tool_calls = None
        raw_tcs = d.get("tool_calls")
        if raw_tcs:
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                )
                for tc in raw_tcs
            ]
        return cls(
            role=role,
            content=d.get("content"),
            tool_calls=tool_calls,
        )


@dataclass
class Response:
    """Normalized result of one LLM call."""

    content: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    raw: dict = field(default_factory=dict)


# ---------- Stream events (Iter 3) ----------
#
# Streaming yields these events instead of a single Response. The caller is
# responsible for accumulating text and tool_calls; the helper assemble_events
# below turns a full event sequence back into a Response, mirroring the
# non-streaming send() return shape.


@dataclass
class TextDelta:
    """Incremental text content from the model."""

    text: str


@dataclass
class ToolCallDelta:
    """Incremental tool call info.

    The first chunk for a given tool call carries `id` and `name`. Subsequent
    chunks for the same tool call (matched by `index`) typically have id=None
    and name=None, only `arguments_delta` filled with a JSON-string fragment
    that must be string-concatenated to previous deltas at the same index.
    """

    index: int
    id: Optional[str]
    name: Optional[str]
    arguments_delta: str


@dataclass
class FinishEvent:
    """Terminal event of a streaming response.

    Always emitted exactly once at the end with the finish_reason
    ("stop" / "tool_calls" / "length" / ...).
    """

    finish_reason: str
