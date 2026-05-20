"""Tests for ContextManager — compaction trigger, splitting, summarization, invariants."""

from unittest.mock import MagicMock

import pytest

from my_agent.agent.context import ContextManager
from my_agent.agent.conversation import Conversation
from my_agent.llm.types import Response, ToolCall


@pytest.fixture
def fake_summarizer():
    """Mock LLMClient.send that returns a fixed summary."""
    client = MagicMock()
    client.send.return_value = Response(
        content="The user asked about X, agent did Y, agent recommended Z.",
        finish_reason="stop",
    )
    return client


# ---------------- trigger ----------------


def test_no_compaction_when_under_budget(fake_summarizer):
    cm = ContextManager(client=fake_summarizer, budget=10_000, keep_recent_turns=2)
    conv = Conversation(system="s")
    conv.append_user("hi")
    conv.append_assistant(content="hello")
    assert cm.maybe_compact(conv) is False
    assert len(conv.messages) == 3
    fake_summarizer.send.assert_not_called()


def test_compaction_triggers_when_over_threshold(fake_summarizer):
    cm = ContextManager(client=fake_summarizer, budget=200, keep_recent_turns=1)
    conv = Conversation(system="s")
    # Build up many turns to exceed budget
    for i in range(10):
        conv.append_user(f"please write a long answer about topic {i} " * 5)
        conv.append_assistant(content=f"detailed answer about topic {i} " * 30)

    assert cm.maybe_compact(conv) is True
    fake_summarizer.send.assert_called_once()


def test_no_compaction_when_too_little_to_compact(fake_summarizer):
    """If the keep-window already covers everything, there's nothing to summarize."""
    cm = ContextManager(client=fake_summarizer, budget=10, keep_recent_turns=5)
    conv = Conversation(system="s")
    conv.append_user("hi")
    conv.append_assistant(content="hello")
    # Over budget, but only 1 user turn — keep_recent_turns=5 covers all
    assert cm.maybe_compact(conv) is False


# ---------------- structure after compaction ----------------


def test_compaction_preserves_system_at_index_0(fake_summarizer):
    cm = ContextManager(client=fake_summarizer, budget=100, keep_recent_turns=1)
    conv = Conversation(system="original system prompt")
    for i in range(8):
        conv.append_user(f"turn {i} input " * 20)
        conv.append_assistant(content=f"turn {i} output " * 20)

    cm.maybe_compact(conv)
    assert conv.messages[0].role == "system"
    assert conv.messages[0].content == "original system prompt"


def test_compaction_inserts_summary_message(fake_summarizer):
    cm = ContextManager(client=fake_summarizer, budget=100, keep_recent_turns=1)
    conv = Conversation(system="s")
    for i in range(8):
        conv.append_user(f"turn {i} input " * 20)
        conv.append_assistant(content=f"turn {i} output " * 20)

    cm.maybe_compact(conv)
    # After system, we expect the summary marker
    summary_msg = conv.messages[1]
    assert summary_msg.role == "user"
    assert "SUMMARY" in summary_msg.content.upper()
    assert "user asked about X" in summary_msg.content  # the mocked summary


def test_compaction_keeps_recent_n_user_turns(fake_summarizer):
    """keep_recent_turns=2 → the last 2 user messages survive verbatim."""
    cm = ContextManager(client=fake_summarizer, budget=100, keep_recent_turns=2)
    conv = Conversation(system="s")
    for i in range(8):
        conv.append_user(f"u{i} " * 30)
        conv.append_assistant(content=f"a{i} " * 30)

    cm.maybe_compact(conv)

    # The last 2 user messages should be u6 and u7, intact
    user_msgs = [m for m in conv.messages if m.role == "user"]
    # First user msg is the summary itself; the others are original
    assert len(user_msgs) >= 3  # summary + 2 originals
    assert user_msgs[-2].content.startswith("u6 ")
    assert user_msgs[-1].content.startswith("u7 ")


def test_compaction_keeps_validate_passing(fake_summarizer):
    """The cardinal sin would be to leave conv in a state that fails validate()."""
    cm = ContextManager(client=fake_summarizer, budget=100, keep_recent_turns=2)
    conv = Conversation(system="s")
    for i in range(8):
        conv.append_user(f"u{i} " * 30)
        conv.append_assistant(content=f"a{i} " * 30)

    cm.maybe_compact(conv)
    conv.validate()  # must not raise


# ---------------- tool-call pairing safety ----------------


def test_compaction_does_not_split_tool_call_pair(fake_summarizer):
    """Compaction must never leave an assistant(tool_calls) without its tool message,
    nor an orphan tool message."""
    cm = ContextManager(client=fake_summarizer, budget=200, keep_recent_turns=1)
    conv = Conversation(system="s")
    # 5 complete turns, each with one tool call
    for i in range(5):
        conv.append_user(f"u{i} " * 20)
        conv.append_assistant(
            content=None,
            tool_calls=[ToolCall(id=f"c{i}", name="echo", arguments='{"x": "y"}')],
        )
        conv.append_tool_result(f"c{i}", "echo", f"result {i} " * 20)
        conv.append_assistant(content=f"final {i} " * 20)

    cm.maybe_compact(conv)
    conv.validate()  # would raise if pair split


# ---------------- summarizer prompt sanity ----------------


def test_summarizer_called_with_third_party_role(fake_summarizer):
    """The prompt sent to the LLM should be a single user-role message asking
    for a summary — not an attempt to re-run the conversation."""
    cm = ContextManager(client=fake_summarizer, budget=100, keep_recent_turns=1)
    conv = Conversation(system="s")
    for i in range(8):
        conv.append_user(f"u{i} " * 30)
        conv.append_assistant(content=f"a{i} " * 30)

    cm.maybe_compact(conv)

    call_kwargs = fake_summarizer.send.call_args.kwargs
    messages = call_kwargs["messages"]
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert "summar" in messages[0].content.lower()
    assert call_kwargs["tools"] == []


# ---------------- force_compact ----------------


def test_force_compact_ignores_trigger_ratio(fake_summarizer):
    """Under budget — maybe_compact does nothing, but force_compact still runs."""
    cm = ContextManager(client=fake_summarizer, budget=100_000, keep_recent_turns=1)
    conv = Conversation(system="s")
    for i in range(5):
        conv.append_user(f"u{i}")
        conv.append_assistant(content=f"a{i}")

    assert cm.maybe_compact(conv) is False  # way under budget
    fake_summarizer.send.assert_not_called()

    assert cm.force_compact(conv) is True
    fake_summarizer.send.assert_called_once()


def test_force_compact_returns_false_when_nothing_to_compact(fake_summarizer):
    """Even forced, can't compact a single-turn conversation."""
    cm = ContextManager(client=fake_summarizer, budget=100, keep_recent_turns=4)
    conv = Conversation(system="s")
    conv.append_user("hi")
    conv.append_assistant(content="hello")
    assert cm.force_compact(conv) is False
    fake_summarizer.send.assert_not_called()
