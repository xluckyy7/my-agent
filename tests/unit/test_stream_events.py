from my_agent.llm.types import FinishEvent, TextDelta, ToolCallDelta


def test_text_delta_equality():
    assert TextDelta("hi") == TextDelta("hi")
    assert TextDelta("hi") != TextDelta("bye")


def test_tool_call_delta_basics():
    e = ToolCallDelta(index=0, id="c1", name="read_file", arguments_delta='{"pa')
    assert e.index == 0
    assert e.id == "c1"
    assert e.name == "read_file"
    assert e.arguments_delta == '{"pa'


def test_tool_call_delta_optional_fields():
    """First chunk of a tool call has id+name; later chunks only have args delta."""
    head = ToolCallDelta(index=0, id="c1", name="read_file", arguments_delta="")
    tail = ToolCallDelta(index=0, id=None, name=None, arguments_delta='{"path"')
    assert head.id == "c1"
    assert tail.id is None


def test_finish_event_carries_reason():
    e = FinishEvent(finish_reason="stop")
    assert e.finish_reason == "stop"
    assert FinishEvent(finish_reason="tool_calls").finish_reason == "tool_calls"
