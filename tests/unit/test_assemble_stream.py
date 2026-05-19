import pytest

from my_agent.llm.stream import assemble_stream
from my_agent.llm.types import (
    FinishEvent,
    Response,
    TextDelta,
    ToolCall,
    ToolCallDelta,
)


def test_assemble_text_only():
    events = [
        TextDelta("he"),
        TextDelta("llo"),
        TextDelta(" world"),
        FinishEvent("stop"),
    ]
    resp = assemble_stream(iter(events))
    assert isinstance(resp, Response)
    assert resp.content == "hello world"
    assert resp.tool_calls == []
    assert resp.finish_reason == "stop"


def test_assemble_tool_call_only_no_text():
    events = [
        ToolCallDelta(0, "c1", "read_file", ""),
        ToolCallDelta(0, None, None, '{"pa'),
        ToolCallDelta(0, None, None, 'th":"a"}'),
        FinishEvent("tool_calls"),
    ]
    resp = assemble_stream(iter(events))
    assert resp.content is None
    assert resp.tool_calls == [
        ToolCall(id="c1", name="read_file", arguments='{"path":"a"}')
    ]
    assert resp.finish_reason == "tool_calls"


def test_assemble_parallel_tool_calls_ordered_by_index():
    events = [
        ToolCallDelta(0, "c1", "echo", ""),
        ToolCallDelta(1, "c2", "echo", ""),
        ToolCallDelta(1, None, None, '{"x":"b"}'),
        ToolCallDelta(0, None, None, '{"x":"a"}'),
        FinishEvent("tool_calls"),
    ]
    resp = assemble_stream(iter(events))
    assert [tc.id for tc in resp.tool_calls] == ["c1", "c2"]
    assert resp.tool_calls[0].arguments == '{"x":"a"}'
    assert resp.tool_calls[1].arguments == '{"x":"b"}'


def test_assemble_mixed_text_and_tool_calls():
    """Some models emit narration before tool call."""
    events = [
        TextDelta("Let me check that. "),
        ToolCallDelta(0, "c1", "read_file", '{"path":"x"}'),
        FinishEvent("tool_calls"),
    ]
    resp = assemble_stream(iter(events))
    assert resp.content == "Let me check that. "
    assert resp.tool_calls[0].name == "read_file"
    assert resp.finish_reason == "tool_calls"


def test_assemble_empty_text_is_none():
    """No TextDelta at all → content is None (matches non-streaming when only tool_calls)."""
    events = [
        ToolCallDelta(0, "c1", "x", "{}"),
        FinishEvent("tool_calls"),
    ]
    resp = assemble_stream(iter(events))
    assert resp.content is None


def test_assemble_missing_finish_event_raises():
    """Stream protocol guarantees a FinishEvent. Missing it = bug."""
    events = [TextDelta("hi")]
    with pytest.raises(ValueError, match="FinishEvent"):
        assemble_stream(iter(events))


def test_assemble_handles_only_finish():
    """Edge: empty response with just a finish event."""
    events = [FinishEvent("stop")]
    resp = assemble_stream(iter(events))
    assert resp.content is None
    assert resp.tool_calls == []
    assert resp.finish_reason == "stop"
