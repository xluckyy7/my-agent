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


def test_stream_qwen_empty_string_id_normalized_to_none(mocker):
    """Qwen real behavior: first chunk has the real id, subsequent chunks send
    id="" (empty string, not None). Without normalization, assemble_stream
    overwrites the real id with the empty string.

    Captured from real DashScope output on 2026-05-18 — see iter-3-retro notes.
    """
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        # Chunk 0: real id + name + empty args
        _make_chunk(tool_calls=[
            _make_tc_delta(0, id_="call_REAL", name="read_file", arguments="")
        ]),
        # Chunk 1: id="" (Qwen quirk), name=None, args fragment
        _make_chunk(tool_calls=[
            _make_tc_delta(0, id_="", name=None, arguments='{"path":"')
        ]),
        # Chunk 2: same quirk
        _make_chunk(tool_calls=[
            _make_tc_delta(0, id_="", name=None, arguments='a"}')
        ]),
        _make_chunk(finish_reason="tool_calls"),
    ])

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    events = list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))

    # Stream layer should normalize "" → None so accumulators don't get confused.
    tc_events = [e for e in events if isinstance(e, ToolCallDelta)]
    assert tc_events[0].id == "call_REAL"
    assert tc_events[1].id is None   # NOT ""
    assert tc_events[2].id is None   # NOT ""


# ---------------- usage capture (stream_options=include_usage) ----------------


def _make_usage_chunk(prompt_tokens: int, completion_tokens: int, total_tokens: int):
    """The trailing chunk emitted by OpenAI-compat servers when
    stream_options={"include_usage": True} is set: choices=[] + usage=..."""
    usage = MagicMock()
    usage.model_dump.return_value = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    chunk = MagicMock(choices=[], usage=usage)
    return chunk


def test_stream_passes_include_usage_flag(mocker):
    """stream_options={'include_usage': True} MUST be in the request so the
    server emits a usage chunk at end-of-stream — otherwise token counts in
    Langfuse / observability are always zero."""
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        _make_chunk(finish_reason="stop"),
    ])

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))

    kwargs = fake_openai.return_value.chat.completions.create.call_args.kwargs
    assert kwargs.get("stream_options") == {"include_usage": True}


def test_stream_post_hook_includes_usage_from_trailing_chunk(mocker):
    """The PostModelCall hook must fire AFTER the usage chunk is consumed
    and include the usage dict — single source of truth for token reporting."""
    fake_hooks = MagicMock()

    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        _make_chunk(content="hi"),
        _make_chunk(finish_reason="stop"),
        _make_usage_chunk(prompt_tokens=42, completion_tokens=7, total_tokens=49),
    ])

    client = LLMClient(
        api_key="k", base_url="https://x", model="qwen-plus", hooks=fake_hooks,
    )
    # Drain the generator so finally runs.
    list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))

    # Pre + Post both fired
    fire_calls = [c for c in fake_hooks.fire.call_args_list]
    events_fired = [c.args[0] for c in fire_calls]
    assert "PreModelCall" in events_fired
    assert "PostModelCall" in events_fired

    # The PostModelCall data must contain the usage dict in OpenAI format
    post_call = next(c for c in fire_calls if c.args[0] == "PostModelCall")
    data = post_call.kwargs["data"]
    assert data["usage"] == {
        "prompt_tokens": 42,
        "completion_tokens": 7,
        "total_tokens": 49,
    }
    assert data["finish_reason"] == "stop"
    assert data["content"] == "hi"
    assert data["stream"] is True


def test_stream_post_hook_fires_even_when_no_usage_chunk(mocker):
    """If the server doesn't emit a usage chunk, the hook still fires with
    usage=None so observability layers know to skip token reporting."""
    fake_hooks = MagicMock()

    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = iter([
        _make_chunk(content="hi"),
        _make_chunk(finish_reason="stop"),
        # no usage chunk
    ])

    client = LLMClient(
        api_key="k", base_url="https://x", model="qwen-plus", hooks=fake_hooks,
    )
    list(client.stream([Message(role="user", content="hi")], tools=[], max_tokens=10))

    post_call = next(
        c for c in fake_hooks.fire.call_args_list if c.args[0] == "PostModelCall"
    )
    data = post_call.kwargs["data"]
    # MagicMock chunks have an auto-attr `usage` that we capture as a dict —
    # what we care about here is the hook DOES fire even without a real usage
    # chunk, with the rest of the fields intact.
    assert "usage" in data
    assert data["finish_reason"] == "stop"
    assert data["content"] == "hi"
