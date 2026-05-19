import sys

# Side-effect import: enabling GNU readline / libedit so input() handles
# multi-byte characters (Chinese, emoji) correctly when backspacing, and gets
# arrow-key history for free. Without this, typing "写一个" then backspace
# only deletes one byte and corrupts the display.
import readline  # noqa: F401

from my_agent.agent.conversation import Conversation
from my_agent.agent.events import TurnTextDelta, TurnToolEnd, TurnToolStart
from my_agent.agent.loop import AgentLoop
from my_agent.cli.render import CYAN, DIM, GRAY, GREEN, RED, color, truncate
from my_agent.config import load_config
from my_agent.llm.client import LLMClient
from my_agent.tools.base import ToolRegistry
from my_agent.tools.files import read_file_tool, write_file_tool
from my_agent.tools.shell import run_bash_tool

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful coding assistant. "
    "Use the available tools to read files, write files, and run shell "
    "commands when the task requires it. When you have enough information, "
    "give the user a final answer."
)


def build_registry() -> ToolRegistry:
    """Wire up the v0.3 tool set."""
    reg = ToolRegistry()
    reg.register(read_file_tool)
    reg.register(write_file_tool)
    reg.register(run_bash_tool)
    return reg


def _render_event(event) -> None:
    """Print a single TurnEvent with appropriate styling."""
    match event:
        case TurnTextDelta(text=t):
            print(t, end="", flush=True)
        case TurnToolStart(name=name, arguments=args):
            args_preview = truncate(args)
            print(
                "\n" + color(f"  ▸ {name} {args_preview}", CYAN + DIM),
                flush=True,
            )
        case TurnToolEnd(name=name, content=content, is_error=err, duration_seconds=dur):
            mark = "✗" if err else "✓"
            tone = RED if err else GREEN
            preview = truncate(content)
            print(
                color(f"    {mark} {dur:.2f}s {preview}", tone + DIM),
                flush=True,
            )


def app() -> int:
    cfg = load_config()
    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)
    loop = AgentLoop(client=client, tools=build_registry(), max_tokens=cfg.max_tokens)
    conv = Conversation(system=DEFAULT_SYSTEM_PROMPT)

    prompt_arg = " ".join(sys.argv[1:]).strip()
    if prompt_arg:
        user_input = prompt_arg
    else:
        prompt_label = color(">>> ", GRAY)
        user_input = input(prompt_label).strip()
    if not user_input:
        return 0

    try:
        for ev in loop.run_turn_stream(conv, user_input):
            _render_event(ev)
        print()  # final newline
    except KeyboardInterrupt:
        print(color("\n[interrupted]", RED), file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(app())
