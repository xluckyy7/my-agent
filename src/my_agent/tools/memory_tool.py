"""The `remember` tool — lets the LLM append entries to user-level memory.

Factory-style (`make_remember_tool(home=...)`) because the target path depends
on the running user's home directory, which we want overridable in tests.
"""

from datetime import date
from pathlib import Path

from my_agent.agent.memory import default_user_memory_path

from .base import Tool


def make_remember_tool(home: Path) -> Tool:
    """Build a `remember` Tool bound to a specific home dir."""
    target = default_user_memory_path(home)

    def _remember(args: dict) -> str:
        content = (args.get("content") or "").strip()
        if not content:
            raise ValueError("remember: content is empty")

        target.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        # One memory per line, ISO-date-prefixed. Markdown-friendly.
        entry = f"- {today}: {content}\n"

        with target.open("a", encoding="utf-8") as f:
            f.write(entry)

        return f"saved memory to {target}"

    return Tool(
        name="remember",
        description=(
            "Save a long-term memory about the user or this project to "
            "~/.my-agent/memory/MEMORY.md. Use when the user shares a stable "
            "preference, role/context, ongoing project, or any fact you'd want "
            "to know in a fresh future session. Each call appends one ISO-date-"
            "prefixed line. Do NOT use for ephemeral task state — only for "
            "things worth remembering across conversations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "The memory text. Be concrete and self-contained "
                        "(future you must understand it without context). "
                        "Example: 'User is a Python developer working on a "
                        "personal CLI agent called my-agent.'"
                    ),
                },
            },
            "required": ["content"],
        },
        fn=_remember,
    )
