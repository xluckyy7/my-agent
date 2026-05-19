"""Tests for AgentLoop.run_turn_stream — multi-round streaming agent loop."""

from unittest.mock import MagicMock

import pytest

from my_agent.agent.conversation import Conversation
from my_agent.agent.errors import AgentBudgetExceeded
from my_agent.agent.events import TurnTextDelta, TurnToolEnd, TurnToolStart
from my_agent.agent.loop import AgentLoop
from my_agent.llm.types import FinishEvent, TextDelta, ToolCallDelta
from my_agent.tools.base import Tool, ToolRegistry


def _collect_text(events):
    """Helper: join all TurnTextDelta texts from a turn event sequence."""
    return "".join(e.text for e in events if isinstance(e, TurnTextDelta))


@pytest.fixture
def echo_registry():
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="echo",
            description="echo input",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
            fn=lambda a: a.get("x", ""),
        )
    )
    return reg


def _stream(*events):
    """Helper to return an iterator the LLMClient.stream mock will yield."""
    return iter(list(events))


def test_run_turn_stream_yields_text(echo_registry):
    client = MagicMock()
    client.stream.return_value = _stream(
        TextDelta("hel"),
        TextDelta("lo"),
        FinishEvent("stop"),
    )

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    events = list(loop.run_turn_stream(Conversation(system="s"), "hi"))

    assert _collect_text(events) == "hello"


def test_run_turn_stream_runs_tool_then_finishes(echo_registry):
    """First send streams a tool call (no text); second send streams text answer."""
    client = MagicMock()
    client.stream.side_effect = [
        _stream(
            ToolCallDelta(0, "c1", "echo", '{"x":"y"}'),
            FinishEvent("tool_calls"),
        ),
        _stream(
            TextDelta("done"),
            FinishEvent("stop"),
        ),
    ]

    conv = Conversation(system="s")
    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    events = list(loop.run_turn_stream(conv, "go"))

    assert _collect_text(events) == "done"
    # New: confirm we get a TurnToolStart + TurnToolEnd pair
    starts = [e for e in events if isinstance(e, TurnToolStart)]
    ends = [e for e in events if isinstance(e, TurnToolEnd)]
    assert len(starts) == 1 and starts[0].name == "echo"
    assert len(ends) == 1 and ends[0].content == "y" and ends[0].is_error is False
    # Conversation should have system, user, assistant(tool_calls), tool, assistant
    roles = [m.role for m in conv.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert conv.messages[3].content == "y"  # echo("y") = "y"
    assert client.stream.call_count == 2


def test_run_turn_stream_yields_text_across_rounds(echo_registry):
    """Model emits narration before tool, then more text after tool."""
    client = MagicMock()
    client.stream.side_effect = [
        _stream(
            TextDelta("Let me check. "),
            ToolCallDelta(0, "c1", "echo", '{"x":"y"}'),
            FinishEvent("tool_calls"),
        ),
        _stream(
            TextDelta("Result is y."),
            FinishEvent("stop"),
        ),
    ]

    conv = Conversation(system="s")
    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    events = list(loop.run_turn_stream(conv, "go"))
    assert _collect_text(events) == "Let me check. Result is y."


def test_run_turn_stream_parallel_tool_calls(echo_registry):
    client = MagicMock()
    client.stream.side_effect = [
        _stream(
            ToolCallDelta(0, "c1", "echo", '{"x":"a"}'),
            ToolCallDelta(1, "c2", "echo", '{"x":"b"}'),
            FinishEvent("tool_calls"),
        ),
        _stream(
            TextDelta("ok"),
            FinishEvent("stop"),
        ),
    ]

    conv = Conversation(system="s")
    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    list(loop.run_turn_stream(conv, "go"))

    tool_msgs = [m for m in conv.messages if m.role == "tool"]
    assert len(tool_msgs) == 2
    assert {m.tool_call_id for m in tool_msgs} == {"c1", "c2"}


def test_run_turn_stream_budget_exceeded(echo_registry):
    client = MagicMock()
    # Always returns a tool call — never finishes
    def make_endless():
        while True:
            yield from [
                ToolCallDelta(0, "c", "echo", '{"x":"x"}'),
                FinishEvent("tool_calls"),
            ]

    iter_endless = make_endless()
    def stream_factory(*args, **kwargs):
        # Each call peels off two events (one ToolCallDelta + one FinishEvent)
        return iter([next(iter_endless), next(iter_endless)])

    client.stream.side_effect = stream_factory

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=3)
    with pytest.raises(AgentBudgetExceeded):
        list(loop.run_turn_stream(Conversation(system="s"), "go"))


def test_run_turn_stream_validates_before_each_send(echo_registry):
    from my_agent.agent.errors import ConversationInvalid

    client = MagicMock()
    client.stream.return_value = _stream(TextDelta("hi"), FinishEvent("stop"))
    conv = Conversation(system="s")
    conv.messages.clear()  # break system invariant

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    with pytest.raises(ConversationInvalid):
        list(loop.run_turn_stream(conv, "go"))


def test_run_turn_stream_passes_messages_and_tools_to_client(echo_registry):
    """Captures a snapshot at call time (not by reference) since AgentLoop
    mutates conv.messages after the call."""
    client = MagicMock()
    snapshots: list[list] = []

    def stream_side_effect(*, messages, tools, max_tokens):
        snapshots.append([m.role for m in messages])
        snapshots.append(messages[-1].content)
        snapshots.append(tools)
        return _stream(TextDelta("hi"), FinishEvent("stop"))

    client.stream.side_effect = stream_side_effect

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    list(loop.run_turn_stream(Conversation(system="s"), "go"))

    roles, last_content, tools_arg = snapshots
    assert roles == ["system", "user"]
    assert last_content == "go"
    assert any(t["function"]["name"] == "echo" for t in tools_arg)
