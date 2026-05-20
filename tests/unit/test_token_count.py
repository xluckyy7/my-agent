"""Tests for token estimation. tiktoken cl100k_base is an approximation for
Qwen (which uses a different tokenizer), good enough for compaction triggers."""

from my_agent.agent.context import count_message_tokens, count_tokens
from my_agent.llm.types import Message, ToolCall


def test_count_tokens_empty_string():
    assert count_tokens("") == 0


def test_count_tokens_ascii_simple():
    # "hello world" is 2 tokens in cl100k_base
    assert count_tokens("hello world") == 2


def test_count_tokens_chinese():
    # Chinese characters are multi-token in cl100k_base (no special CJK BPE)
    n = count_tokens("你好世界")
    assert n > 0
    assert n < 20  # sanity


def test_count_message_tokens_simple_user():
    m = Message(role="user", content="hi")
    n = count_message_tokens(m)
    # JSON-serialized + per-message overhead
    assert n >= count_tokens("hi")
    assert n < 30  # tiny message


def test_count_message_tokens_grows_with_content():
    short = count_message_tokens(Message(role="user", content="a"))
    long = count_message_tokens(Message(role="user", content="a" * 1000))
    assert long > short


def test_count_message_tokens_includes_tool_calls():
    """Assistant message with tool_calls should count the JSON serialization
    of those tool calls, not just content."""
    plain = count_message_tokens(Message(role="assistant", content="ok"))
    with_tool = count_message_tokens(
        Message(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="read_file",
                    arguments='{"path": "some/long/path/to/file.py"}',
                )
            ],
        )
    )
    assert with_tool > plain


def test_count_message_tokens_tool_message():
    m = Message(
        role="tool",
        tool_call_id="c1",
        name="read_file",
        content="line of file content " * 50,
    )
    n = count_message_tokens(m)
    assert n > 100  # 50 repeats of multi-word text


def test_count_total_tokens_for_conversation():
    """Sum of per-message counts."""
    msgs = [
        Message(role="system", content="you are helpful"),
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
    ]
    total = sum(count_message_tokens(m) for m in msgs)
    assert total > 0
    assert total > count_message_tokens(msgs[0])
