import os
import sys
from pathlib import Path

# Side-effect import: enabling GNU readline / libedit so input() handles
# multi-byte characters (Chinese, emoji) correctly when backspacing, and gets
# arrow-key history for free. Without this, typing "写一个" then backspace
# only deletes one byte and corrupts the display.
import readline  # noqa: F401

from my_agent.agent.context import ContextManager
from my_agent.agent.conversation import Conversation
from my_agent.agent.loop import AgentLoop
from my_agent.agent.memory import (
    compose_system_prompt,
    load_project_memory,
    load_user_memory,
)
from my_agent.cli.repl import Repl
from my_agent.config import load_config
from my_agent.llm.client import LLMClient
from my_agent.mcp_layer.adapter import build_mcp_tools
from my_agent.mcp_layer.config import MCPConfigError, load_mcp_config
from my_agent.tools.base import ToolRegistry
from my_agent.tools.files import read_file_tool, write_file_tool
from my_agent.tools.memory_tool import make_remember_tool
from my_agent.tools.shell import run_bash_tool
from my_agent.tools.web import web_fetch_tool, web_search_tool

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful coding assistant. "
    "Use the available tools to read files, write files, run shell commands, "
    "fetch web pages, and remember long-term facts when the task requires it. "
    "When you have enough information, give the user a final answer."
)


def build_registry(home: Path) -> ToolRegistry:
    """Wire up the v0.8 tool set: built-ins + any configured MCP servers.

    web_search is only registered when TAVILY_API_KEY is present.
    `remember` is bound to the given home dir.
    MCP tools come from ~/.my-agent/mcp.json — each remote tool is namespaced
    `<server>__<tool>`. A misbehaving MCP server logs to stderr and is skipped,
    so the agent stays alive on built-ins.
    """
    reg = ToolRegistry()
    reg.register(read_file_tool)
    reg.register(write_file_tool)
    reg.register(run_bash_tool)
    reg.register(web_fetch_tool)
    if os.environ.get("TAVILY_API_KEY"):
        reg.register(web_search_tool)
    reg.register(make_remember_tool(home=home))

    # MCP servers (Iter 8)
    try:
        mcp_specs = load_mcp_config(home)
    except MCPConfigError as e:
        print(f"[mcp] config error: {e}", file=sys.stderr)
        mcp_specs = []
    for spec in mcp_specs:
        for tool in build_mcp_tools(spec):
            reg.register(tool)

    return reg


def app() -> int:
    cfg = load_config()
    home = Path(os.environ.get("HOME", str(Path.home())))
    cwd = Path.cwd()

    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)
    # Summarizer shares the same client/model by default (cheap to swap later).
    context_mgr = ContextManager(
        client=client,
        budget=cfg.context_budget,
        keep_recent_turns=cfg.keep_recent_turns,
    )
    loop = AgentLoop(
        client=client,
        tools=build_registry(home=home),
        max_tokens=cfg.max_tokens,
        context_mgr=context_mgr,
    )

    # Iter 7: weave project + user memory into the system prompt at startup.
    system = compose_system_prompt(
        base=DEFAULT_SYSTEM_PROMPT,
        project=load_project_memory(cwd),
        user=load_user_memory(home),
    )
    conv = Conversation(system=system)
    repl = Repl(loop=loop, conv=conv)

    prompt_arg = " ".join(sys.argv[1:]).strip()
    if prompt_arg:
        # One-shot mode: process the argv prompt and exit.
        repl.handle_input(prompt_arg)
        return 0

    # Interactive REPL mode.
    return repl.run()


if __name__ == "__main__":
    sys.exit(app())
