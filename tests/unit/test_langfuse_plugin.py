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
    """Mock the Langfuse class so _ensure_client returns a MagicMock."""
    client = MagicMock()
    # start_observation returns a new span/generation mock each call
    client.start_observation.side_effect = lambda **kw: MagicMock(name=f"obs:{kw.get('name')}")
    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", lambda *a, **k: client)
    return client


# ---------------- noop fallback ----------------


def test_no_keys_means_no_client(monkeypatch, capsys):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    langfuse_plugin._reset_for_tests()

    # All hooks should silently no-op
    langfuse_plugin.on_user_prompt_submit(_ev("UserPromptSubmit", {"prompt": "hi"}))
    langfuse_plugin.on_pre_model_call(_ev("PreModelCall", {"model": "x"}))
    langfuse_plugin.on_post_model_call(_ev("PostModelCall", {}))

    err = capsys.readouterr().err
    assert "missing" in err.lower() or "disabled" in err.lower()


# ---------------- happy path ----------------


def test_user_prompt_submit_starts_turn_span(fake_client):
    langfuse_plugin.on_user_prompt_submit(
        _ev("UserPromptSubmit", {"prompt": "hi", "session_id": "s1"})
    )
    call = fake_client.start_observation.call_args.kwargs
    assert call["name"] == "turn"
    assert call["as_type"] == "span"
    assert call["input"]["prompt"] == "hi"


def test_pre_model_call_starts_generation(fake_client):
    langfuse_plugin.on_pre_model_call(
        _ev("PreModelCall", {"model": "qwen-plus", "messages": [{"role": "user", "content": "hi"}]})
    )
    call = fake_client.start_observation.call_args.kwargs
    assert call["name"] == "llm_call"
    assert call["as_type"] == "generation"
    assert call["model"] == "qwen-plus"


def test_post_model_call_ends_generation(fake_client):
    langfuse_plugin.on_pre_model_call(_ev("PreModelCall", {"model": "m"}))
    started_obs = fake_client.start_observation.return_value or fake_client.start_observation.side_effect

    langfuse_plugin.on_post_model_call(
        _ev("PostModelCall", {"content": "reply", "finish_reason": "stop"})
    )

    # The generation mock should have been .end()'d
    # find the span pushed
    state = langfuse_plugin._sessions.get("default")
    assert state is not None
    assert state["span_stack"] == []  # popped


def test_tool_span_starts_and_ends(fake_client):
    langfuse_plugin.on_pre_tool_use(
        _ev("PreToolUse", {"tool_name": "read_file", "arguments": '{"path":"x"}'})
    )
    call = fake_client.start_observation.call_args.kwargs
    assert call["name"] == "tool:read_file"
    assert call["as_type"] == "span"

    langfuse_plugin.on_post_tool_use(
        _ev("PostToolUse", {"tool_name": "read_file", "content": "ok", "is_error": False})
    )
    state = langfuse_plugin._sessions.get("default")
    assert state["span_stack"] == []


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


def test_langfuse_import_error_falls_back(monkeypatch, capsys):
    """If Langfuse() raises, we log + return None, agent continues."""
    langfuse_plugin._reset_for_tests()

    def bad_init():
        raise RuntimeError("simulated init failure")

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", lambda *a, **k: bad_init())
    langfuse_plugin.on_pre_model_call(_ev("PreModelCall", {"model": "m"}))
    err = capsys.readouterr().err
    assert "langfuse" in err.lower() and "fail" in err.lower()
