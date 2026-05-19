from my_agent.llm.types import Message, Response, ToolCall


def test_message_simple_text_user():
    m = Message(role="user", content="hello")
    assert m.to_api_dict() == {"role": "user", "content": "hello"}


def test_message_assistant_with_tool_calls():
    m = Message(
        role="assistant",
        content=None,
        tool_calls=[ToolCall(id="c1", name="read_file", arguments='{"path":"a"}')],
    )
    d = m.to_api_dict()
    assert d["role"] == "assistant"
    assert d["content"] is None
    assert d["tool_calls"] == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"a"}'},
        }
    ]


def test_message_assistant_text_only_omits_tool_calls():
    m = Message(role="assistant", content="hi")
    d = m.to_api_dict()
    assert "tool_calls" not in d
    assert d["content"] == "hi"


def test_message_tool_result():
    m = Message(role="tool", tool_call_id="c1", name="read_file", content="ok")
    assert m.to_api_dict() == {
        "role": "tool",
        "tool_call_id": "c1",
        "name": "read_file",
        "content": "ok",
    }


def test_response_defaults():
    r = Response(content="hi")
    assert r.tool_calls == []
    assert r.finish_reason == "stop"
    assert r.raw == {}


def test_toolcall_to_api_dict():
    tc = ToolCall(id="x", name="echo", arguments='{"x":1}')
    assert tc.to_api_dict() == {
        "id": "x",
        "type": "function",
        "function": {"name": "echo", "arguments": '{"x":1}'},
    }


# ---------------- from_api_dict (deserialization) ----------------


def test_message_from_api_dict_round_trip_user():
    m = Message(role="user", content="hi")
    assert Message.from_api_dict(m.to_api_dict()) == m


def test_message_from_api_dict_round_trip_assistant_text():
    m = Message(role="assistant", content="hello")
    assert Message.from_api_dict(m.to_api_dict()) == m


def test_message_from_api_dict_round_trip_assistant_tool_calls():
    m = Message(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(id="c1", name="read_file", arguments='{"path":"a"}'),
            ToolCall(id="c2", name="echo", arguments='{}'),
        ],
    )
    restored = Message.from_api_dict(m.to_api_dict())
    assert restored == m


def test_message_from_api_dict_round_trip_tool_result():
    m = Message(role="tool", tool_call_id="c1", name="read_file", content="ok")
    assert Message.from_api_dict(m.to_api_dict()) == m


def test_message_from_api_dict_system():
    m = Message(role="system", content="you are helpful")
    assert Message.from_api_dict(m.to_api_dict()) == m
