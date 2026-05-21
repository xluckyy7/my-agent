"""Per-session Conversation store for the web app.

Each `session_id` gets its own Conversation, persisted in-memory only (lost
on server restart). Iter 11+ may switch to file/db backed if cross-restart
sessions are needed.
"""

from threading import Lock

from my_agent.agent.conversation import Conversation


class SessionStore:
    """Thread-safe in-memory store of session_id → Conversation."""

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self._sessions: dict[str, Conversation] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str) -> Conversation:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = Conversation(system=self.system_prompt)
            return self._sessions[session_id]

    def reset(self, session_id: str) -> bool:
        """Drop a session. Returns True if it existed."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
