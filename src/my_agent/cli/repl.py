"""Interactive REPL: multi-turn input loop with slash commands."""

import sys
import time
from pathlib import Path
from typing import IO, Callable

from my_agent.agent.conversation import Conversation
from my_agent.agent.errors import ConversationInvalid
from my_agent.agent.events import TurnTextDelta, TurnToolEnd, TurnToolStart
from my_agent.agent.loop import AgentLoop
from my_agent.cli.render import CYAN, DIM, GRAY, GREEN, RED, color, truncate

# Seconds within which a second ctrl-c at the prompt exits the REPL.
SIGINT_EXIT_WINDOW = 2.0


class Repl:
    """Stateful REPL — holds Conversation across turns until /quit or EOF."""

    def __init__(
        self,
        loop: AgentLoop,
        conv: Conversation,
        *,
        out: IO = None,
        err: IO = None,
    ):
        self.loop = loop
        self.conv = conv
        self.out = out if out is not None else sys.stdout
        self.err = err if err is not None else sys.stderr
        self._quit = False
        self._last_sigint: float = 0.0  # monotonic seconds; 0 = never

    # ------- output helpers -------

    def _println(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def _errln(self, text: str) -> None:
        print(text, file=self.err, flush=True)

    # ------- main loop -------

    def run(self) -> int:
        prompt = color(">>> ", GRAY)
        while not self._quit:
            try:
                line = input(prompt).strip()
            except EOFError:
                self._println()  # newline after ^D
                self._println(color("bye", GRAY))
                return 0
            except KeyboardInterrupt:
                # ctrl-c at the prompt: first press shows a hint, second press
                # within SIGINT_EXIT_WINDOW exits. Single-press just discards
                # the current typed line (shell-like).
                if self._should_exit_on_sigint():
                    self._println()
                    self._println(color("bye", GRAY))
                    return 0
                self._println()
                self._errln(color("[press ctrl-c again or /quit to exit]", GRAY))
                continue
            self.handle_input(line)
        return 0

    def _should_exit_on_sigint(self) -> bool:
        """True iff a previous SIGINT happened recently enough to count as 'double-tap'."""
        now = time.monotonic()
        within_window = (now - self._last_sigint) < SIGINT_EXIT_WINDOW
        self._last_sigint = now
        return within_window

    def handle_input(self, line: str) -> None:
        """Process one user input. Either dispatch slash command or run a turn.

        Public method so tests can drive the REPL without spawning input().
        """
        line = line.strip()
        if not line:
            return
        if line.startswith("/"):
            self._handle_command(line)
            return

        try:
            for ev in self.loop.run_turn_stream(self.conv, line):
                self._render_event(ev)
            self._println()
        except KeyboardInterrupt:
            # Interrupted mid-turn: print marker and keep REPL alive.
            # NOTE: Conversation may have a half-written assistant message;
            #   Iter 5 will add proper rollback. For now we leave as-is so
            #   the user can /reset if confused.
            self._errln(color("\n[interrupted]", RED))
        except ConversationInvalid as e:
            self._errln(color(f"[conversation invalid: {e}]", RED))

    # ------- dispatch -------

    def _handle_command(self, line: str) -> None:
        parts = line.split(maxsplit=1)
        cmd = parts[0][1:]  # strip leading /
        arg = parts[1] if len(parts) > 1 else ""
        handler = COMMANDS.get(cmd)
        if handler is None:
            self._errln(color(f"unknown command: /{cmd}. try /help", RED))
            return
        handler(self, arg)

    # ------- event rendering -------

    def _render_event(self, ev) -> None:
        match ev:
            case TurnTextDelta(text=t):
                print(t, end="", flush=True, file=self.out)
            case TurnToolStart(name=name, arguments=args):
                self._println("\n" + color(f"  ▸ {name} {truncate(args)}", CYAN + DIM))
            case TurnToolEnd(name=_, content=content, is_error=err, duration_seconds=dur):
                mark = "✗" if err else "✓"
                tone = RED if err else GREEN
                self._println(color(f"    {mark} {dur:.2f}s {truncate(content)}", tone + DIM))


# ===================================================================
# Commands — each is a (repl, arg_string) → None function
# ===================================================================


def cmd_quit(repl: Repl, arg: str) -> None:
    repl._quit = True


def cmd_reset(repl: Repl, arg: str) -> None:
    repl.conv = Conversation(system=repl.conv.system)
    repl._println(color("conversation reset", GRAY))


def cmd_save(repl: Repl, arg: str) -> None:
    path = arg.strip()
    if not path:
        repl._errln(color("usage: /save <path>", RED))
        return
    try:
        repl.conv.save(Path(path))
    except Exception as e:
        repl._errln(color(f"save failed: {e}", RED))
        return
    repl._println(color(f"saved {len(repl.conv.messages)} messages to {path}", GRAY))


def cmd_load(repl: Repl, arg: str) -> None:
    path = arg.strip()
    if not path:
        repl._errln(color("usage: /load <path>", RED))
        return
    try:
        repl.conv = Conversation.load(Path(path))
    except FileNotFoundError:
        repl._errln(color(f"load failed: file not found: {path}", RED))
        return
    except Exception as e:
        repl._errln(color(f"load failed: {e}", RED))
        return
    repl._println(color(f"loaded {len(repl.conv.messages)} messages from {path}", GRAY))


def cmd_help(repl: Repl, arg: str) -> None:
    lines = [
        "Available commands:",
        "  /help, /?           Show this help",
        "  /quit, /q, /exit    Exit the REPL",
        "  /reset              Clear conversation history (keep system prompt)",
        "  /save <path>        Save current conversation to a JSON file",
        "  /load <path>        Replace conversation with one loaded from file",
        "  /tokens             Show current token count vs budget",
        "  /compact            Manually trigger context compaction now",
        "",
        "Plain text (no leading /) is sent to the agent as a turn.",
        "ctrl-c: interrupt current turn  |  ctrl-d: exit REPL",
    ]
    repl._println("\n".join(lines))


def cmd_tokens(repl: Repl, arg: str) -> None:
    cm = getattr(repl.loop, "context_mgr", None)
    if cm is None:
        repl._errln(color("tokens: no ContextManager configured", RED))
        return
    used = cm.total_tokens(repl.conv)
    budget = cm.budget
    pct = (used / budget * 100) if budget else 0
    user_turns = sum(1 for m in repl.conv.messages if m.role == "user")
    repl._println(
        color(
            f"tokens: {used} / {budget} ({pct:.1f}% of budget) — "
            f"{len(repl.conv.messages)} messages, {user_turns} user turns",
            GRAY,
        )
    )


def cmd_compact(repl: Repl, arg: str) -> None:
    cm = getattr(repl.loop, "context_mgr", None)
    if cm is None:
        repl._errln(color("compact: no ContextManager configured", RED))
        return
    before = cm.total_tokens(repl.conv)
    try:
        changed = cm.force_compact(repl.conv)
    except Exception as e:
        repl._errln(color(f"compact failed: {e}", RED))
        return
    if not changed:
        repl._println(color(f"nothing to compact ({before} tokens, history too short)", GRAY))
        return
    after = cm.total_tokens(repl.conv)
    saved = before - after
    pct = (saved / before * 100) if before else 0
    repl._println(
        color(f"compacted: {before} → {after} tokens ({pct:.1f}% saved)", GRAY)
    )


COMMANDS: dict[str, Callable[[Repl, str], None]] = {
    "quit": cmd_quit,
    "q": cmd_quit,
    "exit": cmd_quit,
    "reset": cmd_reset,
    "save": cmd_save,
    "load": cmd_load,
    "help": cmd_help,
    "?": cmd_help,
    "tokens": cmd_tokens,
    "compact": cmd_compact,
}
