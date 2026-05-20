from unittest.mock import MagicMock

import pytest

from my_agent.agent.conversation import Conversation
from my_agent.agent.errors import AgentBudgetExceeded
from my_agent.agent.loop import AgentLoop
from my_agent.llm.types import Response, ToolCall
from my_agent.tools.base import Tool, ToolRegistry


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


def test_loop_stops_immediately_when_finish_stop(echo_registry):
    client = MagicMock()
    client.send.return_value = Response(content="hi", tool_calls=[], finish_reason="stop")

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    out = loop.run_turn(Conversation(system="s"), "hello")

    assert out == "hi"
    assert client.send.call_count == 1


def test_loop_runs_two_tool_rounds(echo_registry):
    client = MagicMock()
    client.send.side_effect = [
        Response(
            content=None,
            tool_calls=[ToolCall(id="c1", name="echo", arguments='{"x":"1"}')],
            finish_reason="tool_calls",
        ),
        Response(
            content=None,
            tool_calls=[ToolCall(id="c2", name="echo", arguments='{"x":"2"}')],
            finish_reason="tool_calls",
        ),
        Response(content="done", tool_calls=[], finish_reason="stop"),
    ]

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    out = loop.run_turn(Conversation(system="s"), "go")

    assert out == "done"
    assert client.send.call_count == 3


def test_loop_handles_parallel_tool_calls(echo_registry):
    client = MagicMock()
    client.send.side_effect = [
        Response(
            content=None,
            tool_calls=[
                ToolCall(id="c1", name="echo", arguments='{"x":"a"}'),
                ToolCall(id="c2", name="echo", arguments='{"x":"b"}'),
            ],
            finish_reason="tool_calls",
        ),
        Response(content="ok", tool_calls=[], finish_reason="stop"),
    ]

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    out = loop.run_turn(Conversation(system="s"), "go")

    assert out == "ok"
    second_call_kwargs = client.send.call_args_list[1].kwargs
    second_call_msgs = second_call_kwargs.get("messages") or client.send.call_args_list[1].args[0]
    tool_msgs = [m for m in second_call_msgs if m.role == "tool"]
    assert len(tool_msgs) == 2
    assert [t.tool_call_id for t in tool_msgs] == ["c1", "c2"]


def test_loop_budget_exceeded_raises(echo_registry):
    """Model keeps requesting tools forever — must hit hard limit."""
    client = MagicMock()
    client.send.return_value = Response(
        content=None,
        tool_calls=[ToolCall(id="c", name="echo", arguments='{"x":"x"}')],
        finish_reason="tool_calls",
    )

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=3)
    with pytest.raises(AgentBudgetExceeded):
        loop.run_turn(Conversation(system="s"), "go")


def test_loop_passes_tool_schemas_to_client(echo_registry):
    client = MagicMock()
    client.send.return_value = Response(content="hi", tool_calls=[], finish_reason="stop")

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    loop.run_turn(Conversation(system="s"), "hi")

    kwargs = client.send.call_args.kwargs
    if "tools" in kwargs:
        tools_arg = kwargs["tools"]
    else:
        tools_arg = client.send.call_args.args[1]
    assert any(t["function"]["name"] == "echo" for t in tools_arg)


def test_loop_appends_tool_results_with_correct_ids(echo_registry):
    client = MagicMock()
    client.send.side_effect = [
        Response(
            content=None,
            tool_calls=[ToolCall(id="abc", name="echo", arguments='{"x":"y"}')],
            finish_reason="tool_calls",
        ),
        Response(content="done", tool_calls=[], finish_reason="stop"),
    ]
    conv = Conversation(system="s")

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    loop.run_turn(conv, "go")

    # Conversation should contain: system, user, assistant(tool_calls), tool, assistant(stop)
    roles = [m.role for m in conv.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert conv.messages[3].tool_call_id == "abc"
    assert conv.messages[3].content == "y"


def test_loop_unknown_finish_reason_returns_content(echo_registry):
    """e.g. content_filter or length should not loop forever."""
    client = MagicMock()
    client.send.return_value = Response(
        content="truncated", tool_calls=[], finish_reason="length"
    )

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    out = loop.run_turn(Conversation(system="s"), "go")
    assert out == "truncated"
    assert client.send.call_count == 1


def test_loop_validates_conversation_before_each_send(echo_registry):
    """If validate() raises, the error propagates (helps debug bad histories)."""
    from my_agent.agent.errors import ConversationInvalid

    client = MagicMock()
    client.send.return_value = Response(content="x", tool_calls=[], finish_reason="stop")
    conv = Conversation(system="s")
    # Forcibly break invariant: remove system
    conv.messages.clear()

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    with pytest.raises(ConversationInvalid):
        loop.run_turn(conv, "go")


# ---------------- context manager integration ----------------


def test_loop_calls_maybe_compact_before_each_send(echo_registry):
    """If context_mgr is provided, maybe_compact() must be called before every
    client.send so we never exceed budget."""
    client = MagicMock()
    client.send.side_effect = [
        Response(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments='{"x":"y"}')], finish_reason="tool_calls"),
        Response(content="done", tool_calls=[], finish_reason="stop"),
    ]
    cm = MagicMock()
    cm.maybe_compact.return_value = False

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5, context_mgr=cm)
    loop.run_turn(Conversation(system="s"), "go")

    # Two send calls → two maybe_compact calls
    assert cm.maybe_compact.call_count == 2


def test_loop_without_context_mgr_works(echo_registry):
    """context_mgr defaults to None — loop should still work normally."""
    client = MagicMock()
    client.send.return_value = Response(content="ok", tool_calls=[], finish_reason="stop")

    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    assert loop.context_mgr is None
    out = loop.run_turn(Conversation(system="s"), "go")
    assert out == "ok"
