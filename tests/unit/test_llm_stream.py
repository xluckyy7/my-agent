"""Unit tests for LLMClient.stream() — fully mocked openai chunk iterator."""

from unittest.mock import MagicMock

from my_agent.llm.client import LLMClient
from my_agent.llm.types import FinishEvent, Message, TextDelta, ToolCallDelta


def _make_chunk(*, content=None, tool_calls=None, finish_reason=None):
    """Build a MagicMock that mimics openai.ChatCompletionChunk shape."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls
    choice = MagicMock(delta=delta, finish_reason=finish_reason)
    chunk = MagicMock(choices=[choice])
    return chunk


def _make_tc_delta(index, id_=None, name=None, arguments=""):
    """Build a MagicMock that mimics ChoiceDeltaToolCall shape."""
    tc = MagicMock()
    tc.index = index
    tc.id = id_
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def test_stream_text_only(mocker):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        _make_chunk(content="he"),
        _make_chunk(content="llo"),
        _make_chunk(content="!"),
        _make_chunk(finish_reason="stop"),
    ])

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    events = list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))

    assert events == [
        TextDelta("he"),
        TextDelta("llo"),
        TextDelta("!"),
        FinishEvent(finish_reason="stop"),
    ]


def test_stream_passes_stream_true_to_api(mocker):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        _make_chunk(finish_reason="stop"),
    ])

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))

    kwargs = fake_openai.return_value.chat.completions.create.call_args.kwargs
    assert kwargs["stream"] is True


def test_stream_single_tool_call_split_arguments(mocker):
    """Arguments arrive as fragments — emit each as a delta."""
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        _make_chunk(tool_calls=[_make_tc_delta(0, id_="c1", name="read_file", arguments="")]),
        _make_chunk(tool_calls=[_make_tc_delta(0, id_=None, name=None, arguments='{"pa')]),
        _make_chunk(tool_calls=[_make_tc_delta(0, id_=None, name=None, arguments='th":"a"}')]),
        _make_chunk(finish_reason="tool_calls"),
    ])

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    events = list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))

    assert events == [
        ToolCallDelta(index=0, id="c1", name="read_file", arguments_delta=""),
        ToolCallDelta(index=0, id=None, name=None, arguments_delta='{"pa'),
        ToolCallDelta(index=0, id=None, name=None, arguments_delta='th":"a"}'),
        FinishEvent(finish_reason="tool_calls"),
    ]


def test_stream_parallel_tool_calls(mocker):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        _make_chunk(tool_calls=[
            _make_tc_delta(0, id_="c1", name="echo", arguments=""),
            _make_tc_delta(1, id_="c2", name="echo", arguments=""),
        ]),
        _make_chunk(tool_calls=[_make_tc_delta(0, arguments='{"x":"a"}')]),
        _make_chunk(tool_calls=[_make_tc_delta(1, arguments='{"x":"b"}')]),
        _make_chunk(finish_reason="tool_calls"),
    ])

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    events = list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))

    # head events for both indices, then args by index, then finish
    assert events[0] == ToolCallDelta(0, "c1", "echo", "")
    assert events[1] == ToolCallDelta(1, "c2", "echo", "")
    assert events[2] == ToolCallDelta(0, None, None, '{"x":"a"}')
    assert events[3] == ToolCallDelta(1, None, None, '{"x":"b"}')
    assert events[4] == FinishEvent(finish_reason="tool_calls")


def test_stream_emits_finish_even_with_no_content(mocker):
    """A stream that only contains a finish chunk must still emit FinishEvent."""
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        _make_chunk(finish_reason="stop"),
    ])

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    events = list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))
    assert events == [FinishEvent(finish_reason="stop")]


def test_stream_skips_empty_content_deltas(mocker):
    """Some providers emit chunks with content=None and no tool_calls (heartbeats).
    These should not produce events."""
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        _make_chunk(content=None),                # heartbeat
        _make_chunk(content="hi"),
        _make_chunk(content=None),                # heartbeat
        _make_chunk(finish_reason="stop"),
    ])

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    events = list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))
    assert events == [TextDelta("hi"), FinishEvent(finish_reason="stop")]
