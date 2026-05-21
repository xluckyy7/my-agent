"""Tests for the FastAPI web app — health, sessions, /chat SSE."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from my_agent.agent.events import TurnTextDelta, TurnToolEnd, TurnToolStart
from my_agent.web.app import build_app


def _stub_loop_yielding(events_per_call):
    """Build a MagicMock AgentLoop whose run_turn_stream yields the given events."""
    loop = MagicMock()
    calls = iter(events_per_call)

    def _gen(conv, prompt):
        return iter(next(calls))

    loop.run_turn_stream.side_effect = _gen
    return loop


# ---------------- /health ----------------


def test_health_returns_ok():
    app = build_app(loop_factory=lambda: MagicMock(), system_prompt="s")
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_index_returns_html():
    app = build_app(loop_factory=lambda: MagicMock(), system_prompt="s")
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "my-agent" in r.text


def test_sessions_starts_empty():
    app = build_app(loop_factory=lambda: MagicMock(), system_prompt="s")
    r = TestClient(app).get("/sessions")
    assert r.json() == {"sessions": [], "count": 0}


def test_chat_streams_text_deltas():
    """Mock loop yields text deltas; SSE response should contain them."""
    loop = _stub_loop_yielding([[
        TurnTextDelta(text="hel"),
        TurnTextDelta(text="lo"),
    ]])
    app = build_app(loop_factory=lambda: loop, system_prompt="s")
    client = TestClient(app)

    with client.stream(
        "POST", "/chat", json={"prompt": "hi", "session_id": "s1"}
    ) as r:
        body = b"".join(r.iter_bytes()).decode()

    assert 'data: {"type": "text_delta", "text": "hel"}' in body
    assert 'data: {"type": "text_delta", "text": "lo"}' in body
    assert 'data: {"type": "done"}' in body


def test_chat_emits_tool_events():
    loop = _stub_loop_yielding([[
        TurnToolStart(tool_call_id="c1", name="read_file", arguments='{"path":"x"}'),
        TurnToolEnd(
            tool_call_id="c1", name="read_file",
            content="result", is_error=False, duration_seconds=0.42,
        ),
        TurnTextDelta(text="ok"),
    ]])
    app = build_app(loop_factory=lambda: loop, system_prompt="s")
    client = TestClient(app)

    with client.stream(
        "POST", "/chat", json={"prompt": "read x", "session_id": "s1"}
    ) as r:
        body = b"".join(r.iter_bytes()).decode()

    assert "tool_start" in body
    assert "read_file" in body
    assert "tool_end" in body
    assert "0.42" in body


def test_chat_session_persists_across_calls():
    """Same session_id → same Conversation passed each time."""
    loop = _stub_loop_yielding([
        [TurnTextDelta(text="reply1")],
        [TurnTextDelta(text="reply2")],
    ])
    app = build_app(loop_factory=lambda: loop, system_prompt="s")
    client = TestClient(app)

    for _ in range(2):
        with client.stream(
            "POST", "/chat", json={"prompt": "p", "session_id": "shared"}
        ) as r:
            list(r.iter_bytes())  # exhaust

    # Both calls should have used the SAME Conversation instance
    convs = [c.args[0] for c in loop.run_turn_stream.call_args_list]
    assert convs[0] is convs[1]


def test_chat_different_sessions_isolated():
    loop = _stub_loop_yielding([
        [TurnTextDelta(text="a")],
        [TurnTextDelta(text="b")],
    ])
    app = build_app(loop_factory=lambda: loop, system_prompt="s")
    client = TestClient(app)

    for sid in ("s1", "s2"):
        with client.stream(
            "POST", "/chat", json={"prompt": "p", "session_id": sid}
        ) as r:
            list(r.iter_bytes())

    convs = [c.args[0] for c in loop.run_turn_stream.call_args_list]
    assert convs[0] is not convs[1]


def test_chat_emits_error_on_loop_failure():
    loop = MagicMock()
    loop.run_turn_stream.side_effect = RuntimeError("agent went boom")
    app = build_app(loop_factory=lambda: loop, system_prompt="s")
    client = TestClient(app)

    with client.stream(
        "POST", "/chat", json={"prompt": "hi", "session_id": "s"}
    ) as r:
        body = b"".join(r.iter_bytes()).decode()

    assert '"type": "error"' in body
    assert "agent went boom" in body


def test_delete_session_removes_it():
    loop = _stub_loop_yielding([[TurnTextDelta(text="ok")]])
    app = build_app(loop_factory=lambda: loop, system_prompt="s")
    client = TestClient(app)

    # Create the session first by chatting
    with client.stream("POST", "/chat", json={"prompt": "p", "session_id": "X"}) as r:
        list(r.iter_bytes())

    assert client.get("/sessions").json()["count"] == 1
    r = client.delete("/sessions/X")
    assert r.status_code == 200
    assert client.get("/sessions").json()["count"] == 0


def test_delete_unknown_session_returns_404():
    app = build_app(loop_factory=lambda: MagicMock(), system_prompt="s")
    client = TestClient(app)
    r = client.delete("/sessions/nonexistent")
    assert r.status_code == 404
