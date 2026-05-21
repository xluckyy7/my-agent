"""Per-session Conversation store for the web app.

Each `session_id` gets its own Conversation, persisted in-memory only (lost
on server restart). Iter 11+ may switch to file/db backed if cross-restart
sessions are needed.
"""

import time
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from my_agent.agent.conversation import Conversation

TITLE_MAX_CHARS = 60


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


class SessionStore:
    """Thread-safe in-memory store of session_id → (Conversation, timestamps).

    Each entry tracks (conversation, created_at, last_used_at) so the UI can
    show sessions sorted by recency.
    """

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        # session_id → [conv, created_at, last_used_at]
        # List (not tuple) so we can mutate last_used_at in place.
        self._sessions: dict[str, list] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str) -> Conversation:
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
            return self._sessions[session_id][0]

    def get(self, session_id: str) -> Optional[Conversation]:
        """Read-only access; does not touch last_used_at."""
        with self._lock:
            entry = self._sessions.get(session_id)
            return entry[0] if entry else None

    def reset(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

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
