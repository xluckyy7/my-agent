"""Tests for SessionStore persistence (file-backed JSON mirror).

The store still works in-memory when data_dir is None (backwards compatible
with all existing test_web_app.py tests). When data_dir is provided, every
mutation mirrors to <data_dir>/<session_id>.json, and a fresh SessionStore
constructed against the same dir restores all sessions.
"""

import json
import time
from pathlib import Path

import pytest

from my_agent.web.sessions import SessionStore


# ---------------- in-memory mode (unchanged behavior) ----------------


def test_in_memory_mode_writes_nothing(tmp_path: Path):
    """data_dir=None must remain a pure in-memory store; no files appear."""
    store = SessionStore(system_prompt="s")
    conv = store.get_or_create("abc")
    conv.append_user("hi")
    # Nothing under tmp_path because we never told the store about it
    assert list(tmp_path.iterdir()) == []


# ---------------- file-backed mode ----------------


def test_file_backed_creates_data_dir(tmp_path: Path):
    target = tmp_path / "web-sessions"  # not pre-created
    SessionStore(system_prompt="s", data_dir=target)
    assert target.exists() and target.is_dir()


def test_file_backed_persists_on_create(tmp_path: Path):
    store = SessionStore(system_prompt="s", data_dir=tmp_path)
    store.get_or_create("alpha")
    f = tmp_path / "alpha.json"
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert "meta" in data and "conversation" in data
    assert data["conversation"]["messages"][0]["role"] == "system"


def test_file_backed_persists_on_mutation(tmp_path: Path):
    """After mutating the returned Conversation, calling get_or_create again
    (which touches last_used_at) must flush the new messages to disk."""
    store = SessionStore(system_prompt="s", data_dir=tmp_path)
    conv = store.get_or_create("alpha")
    conv.append_user("hello")
    # Touch to trigger persist
    store.get_or_create("alpha")
    data = json.loads((tmp_path / "alpha.json").read_text(encoding="utf-8"))
    roles = [m["role"] for m in data["conversation"]["messages"]]
    assert roles == ["system", "user"]


def test_hydrates_from_existing_files(tmp_path: Path):
    """A fresh SessionStore on a dir with existing JSON files must restore
    those sessions on construction."""
    store1 = SessionStore(system_prompt="s", data_dir=tmp_path)
    conv = store1.get_or_create("alpha")
    conv.append_user("first message")
    store1.persist("alpha")  # explicit save after mutation

    # New store, same dir
    store2 = SessionStore(system_prompt="s", data_dir=tmp_path)
    assert "alpha" in store2.ids()
    restored = store2.get("alpha")
    assert restored is not None
    assert restored.messages[1].role == "user"
    assert restored.messages[1].content == "first message"


def test_hydrate_preserves_timestamps(tmp_path: Path):
    """created_at / last_used_at must survive a restart."""
    store1 = SessionStore(system_prompt="s", data_dir=tmp_path)
    store1.get_or_create("alpha")
    info1 = store1.info("alpha")
    created_before = info1.created_at
    last_before = info1.last_used_at

    time.sleep(0.01)  # ensure clock advances
    store2 = SessionStore(system_prompt="s", data_dir=tmp_path)
    info2 = store2.info("alpha")
    assert info2.created_at == created_before
    assert info2.last_used_at == last_before


def test_reset_deletes_file(tmp_path: Path):
    store = SessionStore(system_prompt="s", data_dir=tmp_path)
    store.get_or_create("alpha")
    assert (tmp_path / "alpha.json").exists()
    store.reset("alpha")
    assert not (tmp_path / "alpha.json").exists()


def test_reset_unknown_session_is_noop(tmp_path: Path):
    """Reset on a non-existent session must not raise even with data_dir."""
    store = SessionStore(system_prompt="s", data_dir=tmp_path)
    assert store.reset("nonexistent") is False


def test_corrupt_file_is_skipped_not_crash(tmp_path: Path, caplog):
    """A malformed JSON file in data_dir must be skipped with a warning —
    a single bad file must not block agent startup."""
    import logging

    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "good.json").write_text(
        json.dumps(
            {
                "meta": {"created_at": 100.0, "last_used_at": 200.0},
                "conversation": {
                    "messages": [{"role": "system", "content": "s"}]
                },
            }
        ),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="my_agent.web.sessions"):
        store = SessionStore(system_prompt="s", data_dir=tmp_path)
    assert store.ids() == ["good"]
    msgs = " ".join(rec.message for rec in caplog.records)
    assert "broken" in msgs


def test_non_json_files_in_data_dir_ignored(tmp_path: Path):
    """Files without .json extension are ignored entirely."""
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("garbage", encoding="utf-8")
    store = SessionStore(system_prompt="s", data_dir=tmp_path)
    assert store.ids() == []


def test_persist_unknown_session_is_noop(tmp_path: Path):
    """persist() on a session that doesn't exist must not write a file."""
    store = SessionStore(system_prompt="s", data_dir=tmp_path)
    store.persist("nonexistent")
    assert list(tmp_path.glob("*.json")) == []


def test_session_id_path_traversal_rejected(tmp_path: Path):
    """A malicious session_id like '../etc/passwd' must not escape data_dir."""
    store = SessionStore(system_prompt="s", data_dir=tmp_path)
    with pytest.raises(ValueError):
        store.get_or_create("../escape")
    with pytest.raises(ValueError):
        store.get_or_create("a/b")


# ---------------- end-to-end: persist through real /chat endpoint ----------------


def test_chat_round_trip_survives_restart(tmp_path: Path):
    """Build app A with data_dir, POST /chat, tear down. Build app B with
    same data_dir, GET /sessions/.../messages, expect the original turn."""
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from my_agent.agent.events import TurnTextDelta
    from my_agent.web.app import build_app

    def make_stub_loop():
        loop = MagicMock()

        def _gen(conv, prompt, session_id="default"):
            conv.append_user(prompt)
            yield TurnTextDelta(text="hi back")
            conv.append_assistant(content="hi back")

        loop.run_turn_stream.side_effect = _gen
        return loop

    # App A: write
    app_a = build_app(loop_factory=make_stub_loop, system_prompt="s", data_dir=tmp_path)
    client_a = TestClient(app_a)
    # Create session, send one chat
    sid = client_a.post("/sessions").json()["session_id"]
    with client_a.stream(
        "POST", "/chat", json={"prompt": "hello", "session_id": sid}
    ) as r:
        # Drain so the generator runs to completion (and persist fires)
        list(r.iter_lines())

    # App B: read (simulates uvicorn restart)
    app_b = build_app(loop_factory=make_stub_loop, system_prompt="s", data_dir=tmp_path)
    client_b = TestClient(app_b)
    listing = client_b.get("/sessions").json()["sessions"]
    assert any(s["id"] == sid for s in listing)

    msgs = client_b.get(f"/sessions/{sid}/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "hello"
    assert msgs[1]["content"] == "hi back"
