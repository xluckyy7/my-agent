"""Integration tests: verify hooks fire at the right points in real agent paths."""

from unittest.mock import MagicMock

import pytest

from my_agent.agent.conversation import Conversation
from my_agent.agent.hooks import HookManager, HookSpec
from my_agent.agent.loop import AgentLoop
from my_agent.llm.types import Response, ToolCall
from my_agent.tools.base import Tool, ToolRegistry


def _capture_hooks():
    """Build a HookManager whose python hook records into a list."""
    calls = []
    # Inline module trick: monkeypatch importlib via direct cache injection
    mgr = HookManager(specs={
        "PreToolUse": [HookSpec(type="python", module="m", function="f")],
        "PostToolUse": [HookSpec(type="python", module="m", function="f")],
        "PreModelCall": [HookSpec(type="python", module="m", function="f")],
        "PostModelCall": [HookSpec(type="python", module="m", function="f")],
        "UserPromptSubmit": [HookSpec(type="python", module="m", function="f")],
        "Stop": [HookSpec(type="python", module="m", function="f")],
    })
    mgr._py_cache[("m", "f")] = lambda ev: calls.append(ev)
    return mgr, calls


def test_tool_registry_fires_pre_and_post_tool_use():
    mgr, calls = _capture_hooks()
    reg = ToolRegistry(hooks=mgr)
    reg.register(Tool(name="echo", description="", parameters={}, fn=lambda a: "ok"))

    reg.dispatch("echo", '{}')

    names = [c.event for c in calls]
    assert names == ["PreToolUse", "PostToolUse"]
    assert calls[0].data["tool_name"] == "echo"
    assert calls[1].data["content"] == "ok"
    assert calls[1].data["is_error"] is False


def test_tool_registry_fires_post_even_on_error():
    mgr, calls = _capture_hooks()
    reg = ToolRegistry(hooks=mgr)
    reg.register(Tool(name="boom", description="", parameters={}, fn=lambda a: 1 / 0))

    reg.dispatch("boom", '{}')

    names = [c.event for c in calls]
    assert names == ["PreToolUse", "PostToolUse"]
    assert calls[1].data["is_error"] is True


def test_agent_loop_fires_full_event_sequence():
    """run_turn should fire UserPromptSubmit, PreModelCall, PostModelCall,
    (PreToolUse, PostToolUse), and Stop."""
    mgr, calls = _capture_hooks()

    client = MagicMock()
    client.send.side_effect = [
        Response(
            content=None,
            tool_calls=[ToolCall(id="c1", name="echo", arguments='{}')],
            finish_reason="tool_calls",
        ),
        Response(content="done", tool_calls=[], finish_reason="stop"),
    ]
    # Wire hook manager into both client and registry (real loop would too)
    client._hooks = mgr  # type: ignore

    def send_with_hooks(*, messages, tools, max_tokens):
        mgr.fire("PreModelCall", data={"messages": messages}, subject="qwen-plus")
        resp = client.send.side_effect_seq.pop(0) if hasattr(client.send, 'side_effect_seq') else None
        return resp

    # Simpler: just give it to a real LLMClient stub
    reg = ToolRegistry(hooks=mgr)
    reg.register(Tool(name="echo", description="", parameters={}, fn=lambda a: "ok"))

    # Re-stub client to actually fire model hooks (mimic real LLMClient)
    real_calls = []

    def fake_send(*, messages, tools, max_tokens):
        mgr.fire("PreModelCall", data={"messages": list(messages)}, subject="qwen-plus")
        resp = client.send.side_effect_seq.pop(0)
        mgr.fire("PostModelCall", data={"finish_reason": resp.finish_reason}, subject="qwen-plus")
        return resp

    client.send.side_effect_seq = [
        Response(
            content=None,
            tool_calls=[ToolCall(id="c1", name="echo", arguments='{}')],
            finish_reason="tool_calls",
        ),
        Response(content="done", tool_calls=[], finish_reason="stop"),
    ]
    client.send.side_effect = fake_send

    loop = AgentLoop(client=client, tools=reg, max_iterations=5, hooks=mgr)
    out = loop.run_turn(Conversation(system="s"), "hi")
    assert out == "done"

    names = [c.event for c in calls]
    # Expected: UserPromptSubmit, PreModelCall, PostModelCall,
    #           PreToolUse, PostToolUse, PreModelCall, PostModelCall, Stop
    assert names == [
        "UserPromptSubmit",
        "PreModelCall", "PostModelCall",
        "PreToolUse", "PostToolUse",
        "PreModelCall", "PostModelCall",
        "Stop",
    ]
    assert calls[0].data["prompt"] == "hi"
    assert calls[-1].data["final_text"] == "done"


def test_run_turn_default_session_id_is_default():
    """When run_turn is called without session_id, the hook events carry
    session_id='default' — preserves backwards compat for CLI callers."""
    mgr, calls = _capture_hooks()
    client = MagicMock()
    client.send.return_value = Response(content="ok", tool_calls=[], finish_reason="stop")

    loop = AgentLoop(client=client, tools=ToolRegistry(), hooks=mgr)
    loop.run_turn(Conversation(system="s"), "hi")

    submits = [c for c in calls if c.event == "UserPromptSubmit"]
    stops = [c for c in calls if c.event == "Stop"]
    assert submits[0].data["session_id"] == "default"
    assert stops[0].data["session_id"] == "default"


def test_run_turn_custom_session_id_propagates_to_hooks():
    """When run_turn is called with session_id='abc-123', both
    UserPromptSubmit and Stop events carry that exact id — this is what
    lets the langfuse plugin tag traces for cross-turn session aggregation."""
    mgr, calls = _capture_hooks()
    client = MagicMock()
    client.send.return_value = Response(content="ok", tool_calls=[], finish_reason="stop")

    loop = AgentLoop(client=client, tools=ToolRegistry(), hooks=mgr)
    loop.run_turn(Conversation(system="s"), "hi", session_id="abc-123")

    submits = [c for c in calls if c.event == "UserPromptSubmit"]
    stops = [c for c in calls if c.event == "Stop"]
    assert submits[0].data["session_id"] == "abc-123"
    assert stops[0].data["session_id"] == "abc-123"


def test_run_turn_stream_propagates_session_id_to_hooks():
    """Streaming variant must also propagate session_id end-to-end."""
    from my_agent.llm.types import FinishEvent, TextDelta

    mgr, calls = _capture_hooks()
    client = MagicMock()

    def fake_stream(*, messages, tools, max_tokens):
        yield TextDelta(text="ok")
        yield FinishEvent(finish_reason="stop")

    client.stream.side_effect = fake_stream

    loop = AgentLoop(client=client, tools=ToolRegistry(), hooks=mgr)
    list(loop.run_turn_stream(Conversation(system="s"), "hi", session_id="web-session-7"))

    submits = [c for c in calls if c.event == "UserPromptSubmit"]
    stops = [c for c in calls if c.event == "Stop"]
    assert submits[0].data["session_id"] == "web-session-7"
    assert stops[0].data["session_id"] == "web-session-7"
