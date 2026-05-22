"""Per-session Conversation store for the web app.

Two modes:
  - In-memory (data_dir=None): sessions live in a dict; lost on restart.
    This is the default and what tests use.
  - File-backed (data_dir=Path): each session mirrors to
    <data_dir>/<session_id>.json on every mutation. Hydrated from disk on
    construction so sessions survive uvicorn restarts.

File format (versioned wrapper around Conversation):
  {
    "meta": {"created_at": <epoch_float>, "last_used_at": <epoch_float>},
    "conversation": {"messages": [<openai-format messages>]}
  }
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

from my_agent.agent.conversation import Conversation
from my_agent.llm.types import Message

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 60

# Session IDs become filenames, so reject anything that isn't a safe slug.
# uuid4().hex slices (the only thing the app produces) match [0-9a-f]+, so
# this regex doesn't constrain real callers — it only blocks path traversal
# (../, /, \) and weird control chars from hostile inputs.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass
class SessionInfo:
    """Lightweight metadata for sidebar display."""

    id: str
    title: str
    created_at: float           # unix epoch seconds
    last_used_at: float
    message_count: int          # excludes system message


def _derive_title(conv: Conversation) -> str:
    """First non-empty user message, truncated. Fallback: '(empty)'."""
    for m in conv.messages:
        if m.role == "user" and m.content:
            text = " ".join(m.content.split())  # collapse whitespace
            if len(text) <= TITLE_MAX_CHARS:
                return text
            return text[: TITLE_MAX_CHARS - 1] + "…"
    return "(empty)"


def _validate_session_id(session_id: str) -> None:
    if not _SAFE_ID_RE.match(session_id):
        raise ValueError(
            f"invalid session_id {session_id!r}: must match {_SAFE_ID_RE.pattern}"
        )


class SessionStore:
    """Thread-safe session_id → Conversation store with optional disk mirror.

    Each entry tracks (conversation, created_at, last_used_at) so the UI can
    show sessions sorted by recency. When `data_dir` is given, all mutations
    flush to <data_dir>/<session_id>.json synchronously.
    """

    def __init__(self, system_prompt: str, data_dir: Optional[Path] = None):
        self.system_prompt = system_prompt
        self.data_dir = data_dir
        # session_id → [conv, created_at, last_used_at]
        # List (not tuple) so we can mutate last_used_at in place.
        self._sessions: dict[str, list] = {}
        self._lock = Lock()

        if self.data_dir is not None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._hydrate()

    # ---------- persistence helpers ----------

    def _path_for(self, session_id: str) -> Path:
        # data_dir presence already checked by callers
        return self.data_dir / f"{session_id}.json"  # type: ignore[union-attr]

    def _hydrate(self) -> None:
        """Load every <data_dir>/*.json into _sessions. Bad files are skipped
        with a stderr warning so one corrupt file can't block server startup."""
        for path in sorted(self.data_dir.glob("*.json")):  # type: ignore[union-attr]
            sid = path.stem
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                meta = raw["meta"]
                msgs = [Message.from_api_dict(m) for m in raw["conversation"]["messages"]]
                if not msgs or msgs[0].role != "system":
                    raise ValueError("conversation missing system message at index 0")
                conv = Conversation.__new__(Conversation)
                conv.system = msgs[0].content or ""
                conv.messages = msgs
                self._sessions[sid] = [
                    conv,
                    float(meta["created_at"]),
                    float(meta["last_used_at"]),
                ]
            except Exception as e:
                logger.warning("skipping corrupt session file %s: %s", path.name, e)

    def _flush(self, session_id: str) -> None:
        """Write one session's state to disk (caller holds the lock)."""
        if self.data_dir is None:
            return
        entry = self._sessions.get(session_id)
        if entry is None:
            return
        conv, created, last_used = entry
        payload = {
            "meta": {"created_at": created, "last_used_at": last_used},
            "conversation": {
                "messages": [m.to_api_dict() for m in conv.messages]
            },
        }
        self._path_for(session_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def persist(self, session_id: str) -> None:
        """Explicitly flush a session to disk. Safe to call when data_dir is
        None (no-op) or when session_id is unknown (no-op)."""
        if self.data_dir is None:
            return
        with self._lock:
            self._flush(session_id)

    # ---------- public API ----------

    def get_or_create(self, session_id: str) -> Conversation:
        _validate_session_id(session_id)
        now = time.time()
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = [
                    Conversation(system=self.system_prompt),
                    now,
                    now,
                ]
            else:
                self._sessions[session_id][2] = now  # touch
            self._flush(session_id)
            return self._sessions[session_id][0]

    def get(self, session_id: str) -> Optional[Conversation]:
        """Read-only access; does not touch last_used_at."""
        with self._lock:
            entry = self._sessions.get(session_id)
            return entry[0] if entry else None

    def reset(self, session_id: str) -> bool:
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
            if existed and self.data_dir is not None:
                try:
                    self._path_for(session_id).unlink(missing_ok=True)
                except OSError as e:
                    logger.warning("failed to remove %s.json: %s", session_id, e)
            return existed

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())

    def info(self, session_id: str) -> Optional[SessionInfo]:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            conv, created, last_used = entry
            return SessionInfo(
                id=session_id,
                title=_derive_title(conv),
                created_at=created,
                last_used_at=last_used,
                message_count=sum(1 for m in conv.messages if m.role != "system"),
            )

    def all_info(self) -> list[SessionInfo]:
        """All sessions, sorted by last_used_at descending (newest first)."""
        with self._lock:
            items = [
                SessionInfo(
                    id=sid,
                    title=_derive_title(conv),
                    created_at=created,
                    last_used_at=last_used,
                    message_count=sum(1 for m in conv.messages if m.role != "system"),
                )
                for sid, (conv, created, last_used) in self._sessions.items()
            ]
        items.sort(key=lambda s: s.last_used_at, reverse=True)
        return items

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
