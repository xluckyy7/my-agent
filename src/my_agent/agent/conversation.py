import json
from pathlib import Path

from my_agent.agent.errors import ConversationInvalid
from my_agent.llm.types import Message, ToolCall


class Conversation:
    """Mutable history of a single agent session.

    Stores a list of Message objects starting with one system message.
    Validates against four invariants the OpenAI tool-use protocol requires.
    """

    def __init__(self, system: str):
        self.system = system
        self.messages: list[Message] = [Message(role="system", content=system)]

    # ------- mutation -------

    def append_user(self, text: str) -> None:
        self.messages.append(Message(role="user", content=text))

    def append_assistant(
        self,
        content: str | None,
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        self.messages.append(
            Message(role="assistant", content=content, tool_calls=tool_calls)
        )

    def append_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        self.messages.append(
            Message(
                role="tool",
                tool_call_id=tool_call_id,
                name=name,
                content=content,
            )
        )

    # ------- serialization -------

    def to_api_format(self) -> list[dict]:
        return [m.to_api_dict() for m in self.messages]

    def save(self, path: Path) -> None:
        """Persist conversation to a JSON file. Creates parent dirs as needed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"messages": [m.to_api_dict() for m in self.messages]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Conversation":
        """Reconstruct a Conversation from a JSON file written by save().

        Raises ConversationInvalid if the file is missing required structure.
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        msgs = [Message.from_api_dict(m) for m in data.get("messages", [])]
        if not msgs:
            raise ConversationInvalid("loaded conversation has no messages")
        if msgs[0].role != "system":
            raise ConversationInvalid(
                f"loaded conversation must start with a system message, got role={msgs[0].role!r}"
            )
        # Bypass __init__ since we already have the full message list.
        instance = cls.__new__(cls)
        instance.system = msgs[0].content or ""
        instance.messages = msgs
        return instance

    # ------- validation -------

    def validate(self) -> None:
        """Check invariants. Raises ConversationInvalid on violation.

        Invariants enforced (see design §3):
          1. There is exactly one system message and it is at index 0.
          2. assistant message must have content OR tool_calls (not both empty).
          3. Every tool message must follow an assistant.tool_calls block whose
             ids include the tool message's tool_call_id, and the count of
             tool messages must match the count of tool_calls in that block.
          4. Every tool_call.id must be a non-empty string (added after a
             Qwen streaming bug leaked empty-string ids — see iter-3-retro).
        """
        # Invariant 1: system at 0, only one
        system_indices = [i for i, m in enumerate(self.messages) if m.role == "system"]
        if system_indices != [0]:
            raise ConversationInvalid(
                f"expected exactly one system message at index 0, got indices {system_indices}"
            )

        # Walk the history to validate tool round structure
        i = 0
        n = len(self.messages)
        while i < n:
            m = self.messages[i]

            # Invariant 2: assistant content/tool_calls cannot both be empty
            if m.role == "assistant":
                if not m.content and not m.tool_calls:
                    raise ConversationInvalid(
                        f"assistant message at index {i} has neither content nor tool_calls"
                    )

            # Invariant 3: tool_calls must be paired with subsequent tool messages
            if m.role == "assistant" and m.tool_calls:
                # Invariant 4: every tool_call.id must be non-empty
                for k, tc in enumerate(m.tool_calls):
                    if not tc.id:
                        raise ConversationInvalid(
                            f"assistant at index {i} tool_calls[{k}] has empty id "
                            f"— likely a streaming-protocol bug; cannot pair with tool messages"
                        )
                expected_ids = [tc.id for tc in m.tool_calls]
                expected_count = len(expected_ids)
                # The next `expected_count` messages must all be role=tool
                # with tool_call_ids matching the expected_ids in order.
                for k in range(expected_count):
                    follow_idx = i + 1 + k
                    if follow_idx >= n:
                        raise ConversationInvalid(
                            f"assistant at {i} requested {expected_count} tool calls "
                            f"but only {k} tool messages follow"
                        )
                    follow = self.messages[follow_idx]
                    if follow.role != "tool":
                        raise ConversationInvalid(
                            f"expected tool message at index {follow_idx}, got role={follow.role}"
                        )
                    if follow.tool_call_id != expected_ids[k]:
                        raise ConversationInvalid(
                            f"tool message at {follow_idx} has tool_call_id "
                            f"{follow.tool_call_id!r}, expected {expected_ids[k]!r}"
                        )
                i += 1 + expected_count
                continue

            # Invariant 3 (orphan check): a tool message must always be inside
            # the window above. Reaching one here means it has no parent assistant.
            if m.role == "tool":
                raise ConversationInvalid(
                    f"tool message at index {i} has no preceding assistant.tool_calls "
                    f"(orphan tool_call_id {m.tool_call_id!r})"
                )

            i += 1
