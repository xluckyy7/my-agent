"""Tests for the langfuse plugin — pure mock-based, no network calls."""

from unittest.mock import MagicMock

import pytest

from my_agent.agent.hooks import HookEvent
from my_agent.plugins import langfuse_plugin


def _ev(name: str, data: dict | None = None) -> HookEvent:
    return HookEvent(event=name, timestamp=0.0, data=data or {})


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """Reset plugin module state + Langfuse keys before each test."""
    langfuse_plugin._reset_for_tests()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")


@pytest.fixture
def fake_client(monkeypatch):
    """Mock the Langfuse class so _ensure_client returns a MagicMock.

    No side_effect — we want the default MagicMock auto-attr behavior so
    `client.start_observation.return_value.start_observation(...)` works as a
    nested mock chain. This lets us inspect parent→child span creation.
    """
    client = MagicMock()
    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", lambda *a, **k: client)
    return client


# ---------------- noop fallback ----------------


def test_no_keys_means_no_client(monkeypatch, caplog):
    import logging

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    langfuse_plugin._reset_for_tests()

    with caplog.at_level(logging.WARNING, logger="my_agent.plugins.langfuse_plugin"):
        # All hooks should silently no-op
        langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "hi"}))
        langfuse_plugin.on_pre_model_call(_ev("PreModelCall", {"model": "x"}))
        langfuse_plugin.on_post_model_call(_ev("PostModelCall", {}))

    msgs = " ".join(rec.message for rec in caplog.records).lower()
    assert "missing" in msgs or "disabled" in msgs


# ---------------- happy path ----------------


def test_user_prompt_submit_starts_turn_span(fake_client):
    langfuse_plugin.on_user_prompt_submit(
        _ev("UserPromptSubmit", {"prompt": "hi", "session_id": "s1"})
    )
    call = fake_client.start_observation.call_args.kwargs
    assert call["name"] == "turn"
    assert call["as_type"] == "span"
    assert call["input"]["prompt"] == "hi"


def test_pre_model_call_starts_generation_as_child(fake_client):
    """llm_call must be created via parent.start_observation, not client.* —
    that's what gives the trace tree its nesting."""
    # Open the turn first
    langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "hi"}))
    turn_span = fake_client.start_observation.return_value

    langfuse_plugin.on_pre_model_call(
        _ev(
            "PreModelCall",
            {"model": "qwen-plus", "messages": [{"role": "user", "content": "hi"}]},
        )
    )

    # client.start_observation was called ONCE (for the turn) — NOT a second time
    assert fake_client.start_observation.call_count == 1
    # The generation was created via turn_span.start_observation
    turn_span.start_observation.assert_called_once()
    call = turn_span.start_observation.call_args.kwargs
    assert call["name"] == "llm_call"
    assert call["as_type"] == "generation"
    assert call["model"] == "qwen-plus"


def test_post_model_call_ends_generation(fake_client):
    langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "x"}))
    langfuse_plugin.on_pre_model_call(_ev("PreModelCall", {"model": "m"}))

    langfuse_plugin.on_post_model_call(
        _ev("PostModelCall", {"content": "reply", "finish_reason": "stop"})
    )

    state = langfuse_plugin._sessions.get("default")
    assert state is not None
    # turn span still on stack; llm gen popped
    assert len(state["span_stack"]) == 1


def test_tool_span_starts_as_tool_type_and_child(fake_client):
    """Tool spans must be as_type='tool' (not 'span'+name='tool:...') and
    parented to the turn span."""
    langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "x"}))
    turn_span = fake_client.start_observation.return_value

    langfuse_plugin.on_pre_tool_use(
        _ev("PreToolUse", {"tool_name": "read_file", "arguments": '{"path":"x"}'})
    )

    # Came from turn_span, not client
    assert fake_client.start_observation.call_count == 1
    turn_span.start_observation.assert_called_once()
    call = turn_span.start_observation.call_args.kwargs
    assert call["name"] == "read_file"          # bare name, no "tool:" prefix
    assert call["as_type"] == "tool"            # langfuse's tool type

    langfuse_plugin.on_post_tool_use(
        _ev("PostToolUse", {"tool_name": "read_file", "content": "ok", "is_error": False})
    )
    state = langfuse_plugin._sessions.get("default")
    assert len(state["span_stack"]) == 1   # turn still open, tool popped


def test_stop_flushes_client(fake_client):
    # Start a turn first (so there's something to pop)
    langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "x"}))
    langfuse_plugin.on_stop(_ev("Stop", {"final_text": "done"}))
    fake_client.flush.assert_called_once()


def test_post_hook_on_empty_stack_does_not_crash(fake_client):
    """Misconfigured (PostModelCall without PreModelCall) should not raise."""
    langfuse_plugin.on_post_model_call(_ev("PostModelCall", {"content": "x"}))
    langfuse_plugin.on_post_tool_use(_ev("PostToolUse", {"content": "x"}))


def test_sessions_isolated_by_id(fake_client):
    langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "a", "session_id": "s1"}))
    langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "b", "session_id": "s2"}))

    assert "s1" in langfuse_plugin._sessions
    assert "s2" in langfuse_plugin._sessions
    assert len(langfuse_plugin._sessions["s1"]["span_stack"]) == 1
    assert len(langfuse_plugin._sessions["s2"]["span_stack"]) == 1


def test_langfuse_import_error_falls_back(monkeypatch, caplog):
    """If Langfuse() raises, we log + return None, agent continues."""
    import logging

    langfuse_plugin._reset_for_tests()

    def bad_init():
        raise RuntimeError("simulated init failure")

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", lambda *a, **k: bad_init())
    with caplog.at_level(logging.ERROR, logger="my_agent.plugins.langfuse_plugin"):
        langfuse_plugin.on_pre_model_call(_ev("PreModelCall", {"model": "m"}))
    msgs = " ".join(rec.message for rec in caplog.records).lower()
    assert "fail" in msgs and "simulated" in msgs


# ---------------- self-hosted host resolution ----------------


def test_langfuse_host_env_passed_to_client(monkeypatch):
    """LANGFUSE_HOST must be forwarded to the SDK constructor."""
    langfuse_plugin._reset_for_tests()
    captured: dict = {}

    def _capturing_ctor(*args, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", _capturing_ctor)
    monkeypatch.setenv("LANGFUSE_HOST", "https://self-hosted.example.com")

    langfuse_plugin._ensure_client()
    assert captured.get("host") == "https://self-hosted.example.com"


def test_langfuse_base_url_env_also_accepted(monkeypatch):
    """LANGFUSE_BASE_URL (alternate spelling) must also be honored."""
    langfuse_plugin._reset_for_tests()
    captured: dict = {}

    def _capturing_ctor(*args, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", _capturing_ctor)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://self-hosted.example.com")

    langfuse_plugin._ensure_client()
    assert captured.get("host") == "https://self-hosted.example.com"


def test_langfuse_host_takes_priority_over_base_url(monkeypatch):
    """When both are set, LANGFUSE_HOST wins (it's the SDK's canonical name)."""
    langfuse_plugin._reset_for_tests()
    captured: dict = {}

    def _capturing_ctor(*args, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", _capturing_ctor)
    monkeypatch.setenv("LANGFUSE_HOST", "https://primary.example.com")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://secondary.example.com")

    langfuse_plugin._ensure_client()
    assert captured.get("host") == "https://primary.example.com"


def test_no_host_env_falls_back_to_sdk_default(monkeypatch):
    """When neither env var is set, host kwarg is omitted entirely so the
    SDK applies its built-in default (cloud.langfuse.com)."""
    langfuse_plugin._reset_for_tests()
    captured: dict = {}

    def _capturing_ctor(*args, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", _capturing_ctor)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)

    langfuse_plugin._ensure_client()
    assert "host" not in captured


# ---------------- format normalization for langfuse 4.x ----------------


def test_map_openai_usage_translates_keys():
    """OpenAI/Qwen usage shape → Langfuse usage shape."""
    got = langfuse_plugin._map_openai_usage(
        {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
    )
    assert got == {"input": 12, "output": 8, "total": 20}


def test_map_openai_usage_handles_none_and_empty():
    assert langfuse_plugin._map_openai_usage(None) is None
    assert langfuse_plugin._map_openai_usage({}) is None
    # Partial usage is preserved (only the present keys)
    assert langfuse_plugin._map_openai_usage({"prompt_tokens": 5}) == {"input": 5}


def test_post_model_call_passes_mapped_usage(fake_client):
    """on_post_model_call must convert OpenAI usage shape before handing to
    gen.update(usage_details=...). Otherwise Langfuse displays 0 tokens."""
    langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "x"}))
    langfuse_plugin.on_pre_model_call(_ev("PreModelCall", {"model": "m"}))
    # Grab the gen mock that was just pushed (= the parent's start_observation return)
    turn_span = fake_client.start_observation.return_value
    gen_span = turn_span.start_observation.return_value

    langfuse_plugin.on_post_model_call(
        _ev(
            "PostModelCall",
            {
                "content": "reply",
                "finish_reason": "stop",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 25,
                    "total_tokens": 125,
                },
            },
        )
    )

    gen_span.update.assert_called_once()
    update_kwargs = gen_span.update.call_args.kwargs
    assert update_kwargs["usage_details"] == {
        "input": 100,
        "output": 25,
        "total": 125,
    }


def test_session_id_tagged_as_otel_attribute_on_root(fake_client):
    """session.id must be set as an OTel attribute on the turn span — not
    just stuffed into metadata — so Langfuse's Sessions view aggregates."""
    from langfuse import LangfuseOtelSpanAttributes

    langfuse_plugin.on_user_prompt_submit(
        _ev("UserPromptSubmit", {"prompt": "x", "session_id": "my-session-123"})
    )

    turn_span = fake_client.start_observation.return_value
    # The plugin reaches into turn_span._otel_span.set_attribute(...)
    turn_span._otel_span.set_attribute.assert_called_with(
        LangfuseOtelSpanAttributes.TRACE_SESSION_ID, "my-session-123"
    )


# ---------------- trace-level I/O (shows in the Traces list Input/Output cols) ----------------


def test_user_prompt_submit_sets_trace_input(fake_client):
    """The Traces list Input column reads TRACE_INPUT (a trace-level
    attribute), NOT the root span's observation.input. Without
    set_trace_io, the column is empty for any trace with more than one
    span (langfuse only auto-promotes single-span traces).

    The plugin must call turn_span.set_trace_io(input={"prompt": ...}) so
    the trace-level field is set explicitly."""
    langfuse_plugin.on_user_prompt_submit(
        _ev("UserPromptSubmit", {"prompt": "hello world"})
    )

    turn_span = fake_client.start_observation.return_value
    turn_span.set_trace_io.assert_called_once()
    call_kwargs = turn_span.set_trace_io.call_args.kwargs
    assert call_kwargs["input"] == {"prompt": "hello world"}


def test_stop_sets_trace_output(fake_client):
    """Same story for the Output column — it reads TRACE_OUTPUT. We must
    set it on the turn (root) span before ending it."""
    # Set up a turn first
    langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "x"}))
    turn_span = fake_client.start_observation.return_value
    # Clear the call from on_user_prompt_submit so we only see what on_stop did
    turn_span.set_trace_io.reset_mock()

    langfuse_plugin.on_stop(_ev("Stop", {"final_text": "the answer is 42"}))

    turn_span.set_trace_io.assert_called_once()
    call_kwargs = turn_span.set_trace_io.call_args.kwargs
    assert call_kwargs["output"] == {"final_text": "the answer is 42"}
