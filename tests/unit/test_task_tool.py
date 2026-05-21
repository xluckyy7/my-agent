"""Tests for the `task` tool — spawns a sub-agent in an isolated conversation."""

from unittest.mock import MagicMock

import pytest

from my_agent.llm.types import Response, ToolCall
from my_agent.tools.base import Tool
from my_agent.tools.task_tool import SUB_AGENT_SYSTEM_PROMPT, make_task_tool


def _stop(text: str) -> Response:
    return Response(content=text, tool_calls=[], finish_reason="stop")


def _echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="echo input",
        parameters={"type": "object", "properties": {}},
        fn=lambda a: "echoed",
    )


# ---------------- metadata ----------------


def test_task_tool_metadata():
    tool = make_task_tool(client=MagicMock(), base_tools=[], depth=0)
    assert tool.name == "task"
    assert tool.description
    assert "description" in tool.parameters["properties"]
    assert tool.parameters["required"] == ["description"]


# ---------------- subagent execution ----------------


def test_task_tool_spawns_subagent_returning_final_text():
    """Sub-agent runs to completion, final text bubbles up to parent."""
    client = MagicMock()
    client.send.return_value = _stop("sub-agent's final answer")

    tool = make_task_tool(client=client, base_tools=[], depth=0)
    out = tool.fn({"description": "find the largest python file"})

    assert out == "sub-agent's final answer"
    client.send.assert_called_once()


def test_task_tool_subagent_conversation_is_isolated():
    """Sub-agent's Conversation must NOT contain parent's history — only
    SUB_AGENT_SYSTEM_PROMPT + the description as user message at call time.

    Snapshot at call time via side_effect (call_args holds a reference, and
    AgentLoop appends to it after send() returns).
    """
    client = MagicMock()
    snapshot = []

    def _snap(*, messages, tools, max_tokens):
        snapshot.append([(m.role, m.content) for m in messages])
        return _stop("done")

    client.send.side_effect = _snap

    tool = make_task_tool(client=client, base_tools=[], depth=0)
    tool.fn({"description": "specific subtask"})

    roles_at_first_send = [r for r, _ in snapshot[0]]
    assert roles_at_first_send == ["system", "user"]
    assert snapshot[0][0][1] == SUB_AGENT_SYSTEM_PROMPT
    assert "specific subtask" in snapshot[0][1][1]


def test_task_tool_subagent_runs_full_loop_with_tools():
    """Sub-agent goes through tool round before final stop."""
    client = MagicMock()
    client.send.side_effect = [
        Response(
            content=None,
            tool_calls=[ToolCall(id="c1", name="echo", arguments='{}')],
            finish_reason="tool_calls",
        ),
        _stop("after using echo, here's the answer"),
    ]

    tool = make_task_tool(client=client, base_tools=[_echo_tool()], depth=0)
    out = tool.fn({"description": "use echo"})

    assert "after using echo" in out
    assert client.send.call_count == 2


# ---------------- recursion depth ----------------


def test_task_tool_subagent_at_below_max_depth_has_task_tool():
    """When depth+1 < max_depth, sub-agent's registry includes a `task` tool
    too (so it can spawn sub-sub-agents)."""
    client = MagicMock()

    # We capture the schemas passed to client.send to inspect the sub-registry.
    captured_tool_names = []

    def _capture(*, messages, tools, max_tokens):
        captured_tool_names.append(
            [t["function"]["name"] for t in tools]
        )
        return _stop("ok")

    client.send.side_effect = _capture

    tool = make_task_tool(client=client, base_tools=[_echo_tool()], depth=0, max_depth=2)
    tool.fn({"description": "x"})

    # depth=0 → next_depth=1; 1 < max_depth=2 → sub gets task tool
    assert "task" in captured_tool_names[0]
    assert "echo" in captured_tool_names[0]


def test_task_tool_subagent_at_max_depth_does_NOT_have_task_tool():
    """When depth+1 == max_depth, sub-agent's registry must NOT include task
    (otherwise infinite recursion possible)."""
    client = MagicMock()
    captured = []

    def _capture(*, messages, tools, max_tokens):
        captured.append([t["function"]["name"] for t in tools])
        return _stop("ok")

    client.send.side_effect = _capture

    # depth=1, max_depth=2 → next_depth=2; 2 < 2 FALSE → no task in sub
    tool = make_task_tool(client=client, base_tools=[_echo_tool()], depth=1, max_depth=2)
    tool.fn({"description": "x"})

    assert "task" not in captured[0]
    assert "echo" in captured[0]


# ---------------- registry integration ----------------


def test_task_tool_via_registry_dispatch():
    from my_agent.tools.base import ToolRegistry

    client = MagicMock()
    client.send.return_value = _stop("registry test answer")

    reg = ToolRegistry()
    reg.register(make_task_tool(client=client, base_tools=[], depth=0))

    res = reg.dispatch("task", '{"description": "do X"}')
    assert res.is_error is False
    assert res.content == "registry test answer"


def test_task_tool_propagates_subagent_exception():
    """If sub-agent fails (e.g., AgentBudgetExceeded), parent ToolRegistry
    catches and reports as is_error=True."""
    from my_agent.agent.errors import AgentBudgetExceeded
    from my_agent.tools.base import ToolRegistry

    client = MagicMock()
    # Sub-agent never finishes — always returns tool_calls
    client.send.return_value = Response(
        content=None,
        tool_calls=[ToolCall(id="c", name="echo", arguments='{}')],
        finish_reason="tool_calls",
    )

    reg = ToolRegistry()
    reg.register(
        make_task_tool(client=client, base_tools=[_echo_tool()], depth=0)
    )
    res = reg.dispatch("task", '{"description": "infinite"}')

    # Default sub_max_iterations is the AgentLoop default (20), then
    # AgentBudgetExceeded → caught by Registry.dispatch → is_error=True
    assert res.is_error is True
    assert "exceeded" in res.content.lower() or "AgentBudgetExceeded" in res.content


def test_task_tool_subagent_uses_provided_base_tools():
    """All tools in base_tools should appear in sub-agent's registry."""
    client = MagicMock()
    captured = []

    def _capture(*, messages, tools, max_tokens):
        captured.append([t["function"]["name"] for t in tools])
        return _stop("ok")

    client.send.side_effect = _capture

    tools = [
        Tool(name=f"t{i}", description=f"d{i}", parameters={}, fn=lambda a: f"r{i}")
        for i in range(3)
    ]
    tool = make_task_tool(client=client, base_tools=tools, depth=0, max_depth=2)
    tool.fn({"description": "x"})

    for i in range(3):
        assert f"t{i}" in captured[0]
