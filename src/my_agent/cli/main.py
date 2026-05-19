import sys

# Side-effect import: enabling GNU readline / libedit so input() handles
# multi-byte characters (Chinese, emoji) correctly when backspacing, and gets
# arrow-key history for free. Without this, typing "写一个" then backspace
# only deletes one byte and corrupts the display.
import readline  # noqa: F401

from my_agent.agent.conversation import Conversation
from my_agent.agent.loop import AgentLoop
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


def app() -> int:
    cfg = load_config()
    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)
    loop = AgentLoop(client=client, tools=build_registry(), max_tokens=cfg.max_tokens)
    conv = Conversation(system=DEFAULT_SYSTEM_PROMPT)

    prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        prompt = input(">>> ").strip()
    if not prompt:
        return 0

    try:
        for chunk in loop.run_turn_stream(conv, prompt):
            print(chunk, end="", flush=True)
        print()  # final newline
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(app())
