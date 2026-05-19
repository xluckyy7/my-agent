"""ANSI rendering helpers for the CLI.

We intentionally stay dependency-free here; rich/textual integration is
deferred to Iter 4 alongside the full REPL rework.
"""

import sys
from typing import IO

RESET = "\x1b[0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"

# Colors
GRAY = "\x1b[90m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"

PREVIEW_MAX = 80


def _supports_color(stream: IO) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


def truncate(text: str, limit: int = PREVIEW_MAX) -> str:
    """Single-line preview, truncated with ellipsis."""
    flat = " ".join(text.split())  # collapse whitespace/newlines for one-liner
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def color(text: str, code: str, *, stream: IO | None = None) -> str:
    """Wrap text in an ANSI code, gracefully no-op when target isn't a TTY."""
    target = stream if stream is not None else sys.stdout
    if not _supports_color(target):
        return text
    return f"{code}{text}{RESET}"
