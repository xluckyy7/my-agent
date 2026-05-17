from unittest.mock import MagicMock

from my_agent.llm.client import LLMClient
from my_agent.llm.types import Message


def _fake_completion(text: str | None = "hi", tool_calls=None, finish_reason: str = "stop"):
    """Build a MagicMock that mimics openai's ChatCompletion response shape."""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = tool_calls or []
    choice = MagicMock(message=msg, finish_reason=finish_reason)
    completion = MagicMock(choices=[choice])
    completion.model_dump = lambda: {"choices": [{"finish_reason": finish_reason}]}
    return completion


def _fake_tool_call(id_: str, name: str, args: str):
    tc = MagicMock()
    tc.id = id_
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = args
    return tc


def test_send_returns_text(mocker):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = _fake_completion("hello")

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    resp = client.send([Message(role="user", content="hi")], tools=[], max_tokens=100)

    assert resp.content == "hello"
    assert resp.finish_reason == "stop"
    assert resp.tool_calls == []


def test_send_passes_correct_kwargs(mocker):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = _fake_completion()

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    client.send([Message(role="user", content="hi")], tools=[], max_tokens=100)

    kwargs = fake_openai.return_value.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "qwen-plus"
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert kwargs["max_tokens"] == 100
    assert "tools" not in kwargs


def test_send_includes_tools_when_provided(mocker):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = _fake_completion()
    schemas = [{"type": "function", "function": {"name": "x", "parameters": {}}}]

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    client.send([Message(role="user", content="hi")], tools=schemas, max_tokens=100)

    kwargs = fake_openai.return_value.chat.completions.create.call_args.kwargs
    assert kwargs["tools"] == schemas


def test_send_parses_tool_calls(mocker):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = _fake_completion(
        text=None,
        tool_calls=[_fake_tool_call("call_1", "read_file", '{"path":"x"}')],
        finish_reason="tool_calls",
    )

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    resp = client.send([Message(role="user", content="hi")], tools=[], max_tokens=100)

    assert resp.content is None
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.id == "call_1"
    assert tc.name == "read_file"
    assert tc.arguments == '{"path":"x"}'


def test_send_passes_base_url_and_key(mocker):
    fake_openai_cls = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai_cls.return_value.chat.completions.create.return_value = _fake_completion()

    LLMClient(api_key="my-key", base_url="https://example.com/v1", model="qwen-plus")

    fake_openai_cls.assert_called_once_with(api_key="my-key", base_url="https://example.com/v1")


def test_debug_off_by_default(mocker, capsys, monkeypatch):
    monkeypatch.delenv("MY_AGENT_DEBUG", raising=False)
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = _fake_completion("hi")

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    client.send([Message(role="user", content="hi")], tools=[], max_tokens=10)

    err = capsys.readouterr().err
    assert "REQUEST" not in err
    assert "RESPONSE" not in err


def test_debug_on_dumps_request_and_response(mocker, capsys, monkeypatch):
    monkeypatch.setenv("MY_AGENT_DEBUG", "1")
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = _fake_completion("hi")

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    client.send([Message(role="user", content="hi")], tools=[], max_tokens=10)

    err = capsys.readouterr().err
    assert "REQUEST" in err
    assert "RESPONSE" in err
    assert '"role": "user"' in err
    assert '"content": "hi"' in err


def test_debug_falsy_values_do_not_enable(mocker, capsys, monkeypatch):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = _fake_completion("hi")

    for val in ["", "0", "false", "FALSE", "no"]:
        monkeypatch.setenv("MY_AGENT_DEBUG", val)
        client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
        client.send([Message(role="user", content="hi")], tools=[], max_tokens=10)
        err = capsys.readouterr().err
        assert "REQUEST" not in err, f"debug should be off for value {val!r}"
