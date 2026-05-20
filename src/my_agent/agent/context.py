"""Token counting + context compaction (Iter 5).

Uses tiktoken's cl100k_base as a coarse approximation. The exact token count
depends on each provider's tokenizer (Qwen / GPT / Claude all differ), but we
only need approximate counts to decide WHEN to compact, not exactly HOW MUCH.
A 10-20% over/under-estimate is fine.
"""

import json
from functools import lru_cache

import tiktoken

from my_agent.llm.types import Message

# Per-message protocol overhead — OpenAI's official tip is ~3 tokens for the
# role separator + ~1 for the priming token. Round up a bit for safety.
_PER_MESSAGE_OVERHEAD = 4


@lru_cache(maxsize=1)
def _enc():
    """Cached tiktoken encoder. cl100k_base is the GPT-3.5/4 default."""
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Token count of a plain string."""
    if not text:
        return 0
    return len(_enc().encode(text))


def count_message_tokens(message: Message) -> int:
    """Token count of a single Message in its serialized API form.

    We JSON-serialize the message and count that — this is what the API sees
    (modulo chat template formatting which we cannot fully model without each
    provider's tokenizer).
    """
    payload = json.dumps(message.to_api_dict(), ensure_ascii=False)
    return count_tokens(payload) + _PER_MESSAGE_OVERHEAD


# ===================================================================
# ContextManager — compaction logic
# ===================================================================

SUMMARY_PREFIX = "[CONVERSATION SUMMARY]\n"
SUMMARIZE_INSTRUCTION = (
    "You are a conversation summarizer. Summarize the following conversation "
    "between a user and an AI assistant in 200 words or less. Preserve: "
    "(1) the user's overall goal, (2) key decisions made, (3) important file "
    "paths / commands / code references, (4) any unresolved questions or "
    "in-flight work. Use third-person past tense. Output ONLY the summary text, "
    "no preamble.\n\nConversation:\n"
)


class ContextManager:
    """Compaction strategy: sliding window + LLM summarization.

    On `maybe_compact`:
      1. If total tokens < budget * trigger_ratio, do nothing.
      2. Find a safe split: keep [system] + the last K user-turn-blocks.
      3. Summarize the middle via a single LLM call.
      4. Replace the middle with a single user-role marker message containing
         the summary.

    The summary is wrapped with SUMMARY_PREFIX so the model — and humans
    reading the JSON — clearly see it's reconstructed context, not literal
    user input.

    KNOWN LIMITATIONS (see docs/notes/iter-5-retro.md "Known Limitations"):
      - A single message bigger than the budget (e.g. huge paste, huge
        tool_result) is NOT shrunk — maybe_compact returns False because the
        keep-window already covers it.
      - The "recent K turns" alone may exceed the budget, leaving conv
        oversized even after a successful summary of the middle section.
    Mitigations (iterative compaction, tool-result truncation, tool-call
    collapse) are deferred — to be added when real usage actually triggers
    these cases.
    """

    def __init__(
        self,
        client,
        budget: int = 8000,
        keep_recent_turns: int = 4,
        trigger_ratio: float = 0.8,
        summary_max_tokens: int = 600,
    ):
        self.client = client
        self.budget = budget
        self.keep_recent_turns = keep_recent_turns
        self.trigger_ratio = trigger_ratio
        self.summary_max_tokens = summary_max_tokens

    # ------- public -------

    def total_tokens(self, conv) -> int:
        return sum(count_message_tokens(m) for m in conv.messages)

    def maybe_compact(self, conv) -> bool:
        """Compact in-place if budget exceeded. Returns True if compaction happened."""
        if self.total_tokens(conv) < self.budget * self.trigger_ratio:
            return False
        return self._do_compact(conv)

    def force_compact(self, conv) -> bool:
        """Compact unconditionally (bypass trigger_ratio).

        Returns True iff conv was actually modified. Returns False when there
        is nothing compactable (history too short to summarize). Used by the
        REPL's /compact command.
        """
        return self._do_compact(conv)

    def _do_compact(self, conv) -> bool:
        """Core compaction logic. Returns True if conv was actually changed."""
        split_idx = self._find_split_index(conv)
        # split_idx <= 1 means keep window already covers everything past system
        if split_idx <= 1:
            return False

        to_compact = conv.messages[1:split_idx]
        to_keep_tail = conv.messages[split_idx:]
        if not to_compact:
            return False

        summary_text = self._summarize(to_compact)
        summary_msg = Message(
            role="user",
            content=f"{SUMMARY_PREFIX}{summary_text}",
        )

        conv.messages = [conv.messages[0], summary_msg, *to_keep_tail]
        return True

    # ------- internals -------

    def _find_split_index(self, conv) -> int:
        """Index such that conv.messages[idx:] contains the last K user-turn-blocks.

        Splitting at a user-message boundary guarantees we never break a
        (assistant.tool_calls, tool_result, ..., final_assistant) chain.
        """
        user_indices = [i for i, m in enumerate(conv.messages) if m.role == "user"]
        if len(user_indices) <= self.keep_recent_turns:
            return 1  # only system separable; rest is "recent"
        return user_indices[-self.keep_recent_turns]

    def _summarize(self, messages: list[Message]) -> str:
        prompt = SUMMARIZE_INSTRUCTION + self._render_for_summary(messages)
        resp = self.client.send(
            messages=[Message(role="user", content=prompt)],
            tools=[],
            max_tokens=self.summary_max_tokens,
        )
        return (resp.content or "(empty summary)").strip()

    @staticmethod
    def _render_for_summary(messages: list[Message]) -> str:
        """Flatten messages into a single text block for the summarizer prompt."""
        lines: list[str] = []
        for m in messages:
            role = m.role.upper()
            if m.role == "assistant" and m.tool_calls:
                tcs = ", ".join(
                    f"{tc.name}({tc.arguments})" for tc in m.tool_calls
                )
                content = m.content or ""
                lines.append(f"{role}: {content} [tool calls: {tcs}]")
            elif m.role == "tool":
                lines.append(f"TOOL[{m.name}]: {m.content}")
            else:
                lines.append(f"{role}: {m.content}")
        return "\n".join(lines)

