"""Typed events emitted by AgentLoop.run_turn_stream.

These are higher-level than LLMClient.stream's StreamEvents — they describe
"what the agent is doing this turn" rather than "what the LLM chunk just said".
The CLI uses them to render tool indicators, errors, and final text.
"""

from dataclasses import dataclass


@dataclass
class TurnTextDelta:
    """Incremental text from the model, to be printed to the user."""

    text: str


@dataclass
class TurnToolStart:
    """A tool is about to be dispatched. CLI typically prints an indicator."""

    tool_call_id: str
    name: str
    arguments: str  # JSON string as sent by model (may be truncated by UI)


@dataclass
class TurnToolEnd:
    """A tool finished. content is the observation the model will see next."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool
    duration_seconds: float
