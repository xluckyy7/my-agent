import pytest

from my_agent.agent.conversation import Conversation
from my_agent.agent.errors import ConversationInvalid
from my_agent.llm.types import ToolCall


def test_conversation_starts_with_system():
    c = Conversation(system="you are helpful")
    assert len(c.messages) == 1
    assert c.messages[0].role == "system"
    assert c.messages[0].content == "you are helpful"


def test_append_user_and_assistant_text():
    c = Conversation(system="s")
    c.append_user("hi")
    c.append_assistant(content="hello")
    api = c.to_api_format()
    assert api[0] == {"role": "system", "content": "s"}
    assert api[1] == {"role": "user", "content": "hi"}
    assert api[2]["role"] == "assistant"
    assert api[2]["content"] == "hello"
    assert "tool_calls" not in api[2]


def test_append_assistant_with_tool_calls():
    c = Conversation(system="s")
    c.append_user("u")
    c.append_assistant(
        content=None,
        tool_calls=[ToolCall(id="c1", name="read_file", arguments='{}')],
    )
    api = c.to_api_format()
    assert api[2]["tool_calls"][0]["id"] == "c1"


def test_append_tool_result():
    c = Conversation(system="s")
    c.append_user("u")
    c.append_assistant(
        content=None,
        tool_calls=[ToolCall(id="c1", name="read_file", arguments='{}')],
    )
    c.append_tool_result(tool_call_id="c1", name="read_file", content="data")
    api = c.to_api_format()
    assert api[3]["role"] == "tool"
    assert api[3]["tool_call_id"] == "c1"
    assert api[3]["content"] == "data"


# ---------------- validate() ----------------


def test_validate_accepts_well_formed_history():
    c = Conversation(system="s")
    c.append_user("u")
    c.append_assistant(content="hi")
    c.validate()  # must not raise


def test_validate_accepts_tool_round_paired():
    c = Conversation(system="s")
    c.append_user("u")
    c.append_assistant(
        content=None,
        tool_calls=[
            ToolCall(id="c1", name="x", arguments='{}'),
            ToolCall(id="c2", name="y", arguments='{}'),
        ],
    )
    c.append_tool_result("c1", "x", "ok")
    c.append_tool_result("c2", "y", "ok")
    c.validate()


def test_validate_rejects_assistant_with_both_empty():
    c = Conversation(system="s")
    c.append_user("u")
    c.append_assistant(content=None, tool_calls=None)
    with pytest.raises(ConversationInvalid, match="content"):
        c.validate()


def test_validate_rejects_orphan_tool_message():
    """tool message without preceding assistant.tool_calls."""
    c = Conversation(system="s")
    c.append_user("u")
    c.append_assistant(content="hi")
    c.append_tool_result("c1", "x", "ok")  # no matching tool_call
    with pytest.raises(ConversationInvalid, match="tool_call_id"):
        c.validate()


def test_validate_rejects_unmatched_tool_count():
    """assistant.tool_calls says 2, but only 1 tool message follows."""
    c = Conversation(system="s")
    c.append_user("u")
    c.append_assistant(
        content=None,
        tool_calls=[
            ToolCall(id="c1", name="x", arguments='{}'),
            ToolCall(id="c2", name="y", arguments='{}'),
        ],
    )
    c.append_tool_result("c1", "x", "ok")  # missing c2
    with pytest.raises(ConversationInvalid):
        c.validate()


def test_validate_rejects_wrong_tool_call_id():
    c = Conversation(system="s")
    c.append_user("u")
    c.append_assistant(
        content=None,
        tool_calls=[ToolCall(id="c1", name="x", arguments='{}')],
    )
    c.append_tool_result("WRONG", "x", "ok")
    with pytest.raises(ConversationInvalid, match="tool_call_id"):
        c.validate()


def test_validate_rejects_missing_system():
    c = Conversation(system="s")
    c.messages.pop(0)  # forcibly remove system
    with pytest.raises(ConversationInvalid, match="system"):
        c.validate()


def test_validate_rejects_duplicate_system():
    c = Conversation(system="s")
    from my_agent.llm.types import Message

    c.messages.append(Message(role="system", content="another"))
    with pytest.raises(ConversationInvalid, match="system"):
        c.validate()
