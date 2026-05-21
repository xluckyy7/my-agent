"""Cross-session memory (Iter 7).

Two files get injected into the system prompt on startup:

  ./AGENT.md
      Project-level memory. Git-tracked, editable by humans. Use for things
      like "in this codebase we always use tabs" or "API key is in vault://foo".
      Optional — agent works fine without it.

  ~/.my-agent/memory/MEMORY.md
      User-level memory. Edited via the `remember` tool by the LLM (Iter 7.2)
      or directly by you. Use for things like "I prefer terse output" or
      "I'm working on the my-agent project". Optional.

Both files are plain Markdown — no YAML frontmatter, no per-memory file
splitting (yet). Iter 8+ may evolve toward a Claude-Code-style indexed
memory directory if usage demands it.
"""

from pathlib import Path
from typing import Optional

DEFAULT_PROJECT_MEMORY_NAME = "AGENT.md"
DEFAULT_USER_MEMORY_DIR = ".my-agent/memory"
DEFAULT_USER_MEMORY_FILE = "MEMORY.md"


def default_user_memory_path(home: Path) -> Path:
    """Return the canonical user-memory file path under a given home dir."""
    return home / DEFAULT_USER_MEMORY_DIR / DEFAULT_USER_MEMORY_FILE


def _read_if_non_empty(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    content = path.read_text(encoding="utf-8").strip()
    return content or None


def load_project_memory(cwd: Path) -> Optional[str]:
    """Read ./AGENT.md from the given working directory."""
    return _read_if_non_empty(cwd / DEFAULT_PROJECT_MEMORY_NAME)


def load_user_memory(home: Path) -> Optional[str]:
    """Read ~/.my-agent/memory/MEMORY.md from the given home directory."""
    return _read_if_non_empty(default_user_memory_path(home))


def compose_system_prompt(
    base: str,
    project: Optional[str],
    user: Optional[str],
) -> str:
    """Stitch the base system prompt with optional memory sections.

    Order is intentional:
      1. base   — core agent identity / capabilities
      2. project — what's specific to THIS codebase / task
      3. user   — what's specific to THIS user (lowest priority,
                  but persistent across sessions)
    """
    parts = [base]
    if project:
        parts.append(
            "## Project memory (from ./AGENT.md)\n"
            "Apply the following rules and context whenever they are relevant:\n\n"
            f"{project}"
        )
    if user:
        parts.append(
            "## User memory (from ~/.my-agent/memory/MEMORY.md)\n"
            "Long-term facts about the user. Refer to them naturally; "
            "do not quote them verbatim unless asked:\n\n"
            f"{user}"
        )
    return "\n\n".join(parts)
